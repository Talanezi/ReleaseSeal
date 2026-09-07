"""Bounded local-audio evidence recovery and artifact-bound confirmation."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from creator_preflight.presentation import format_timecode
from creator_preflight.release_contract import (
    ContractRequirementResult,
    ContractStatus,
    EvidenceSource,
    EvaluationClass,
    ReleaseContract,
    ReleaseContractEvaluation,
    _phrase_present,
    _token_present,
)

SHA256_PATTERN = r"^[0-9a-f]{64}$"
RECOVERABLE_TYPES = {
    "REQUIRED_TEXT", "REQUIRED_EXACT_TOKEN", "REQUIRED_BEFORE_TIME", "FORBIDDEN_TEXT",
}
_CANDIDATE_SIGNING_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class _EvidenceSegment:
    start_seconds: float
    end_seconds: float
    text: str


class EvidenceRecoveryStatus(str, Enum):
    NOT_NEEDED = "NOT_NEEDED"
    COMPLETED = "COMPLETED"
    UNAVAILABLE = "UNAVAILABLE"


class MachineEvidenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_id: str = Field(pattern=r"^audio-[0-9a-f]{16}$")
    artifact_sha256: str = Field(pattern=SHA256_PATTERN)
    requirement_id: str = Field(min_length=1, max_length=64)
    requirement_sha256: str = Field(pattern=SHA256_PATTERN)
    requirement_type: Literal[
        "REQUIRED_TEXT", "REQUIRED_EXACT_TOKEN", "REQUIRED_BEFORE_TIME", "FORBIDDEN_TEXT"
    ]
    proposition: str = Field(min_length=1, max_length=700)
    expected_value: str = Field(min_length=1, max_length=500)
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    machine_text: str = Field(min_length=1, max_length=500)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    engine: Literal["faster-whisper"] = "faster-whisper"
    model: str = Field(min_length=1, max_length=200)
    evidence_source: Literal[EvidenceSource.LOCAL_MACHINE_TRANSCRIPT] = EvidenceSource.LOCAL_MACHINE_TRANSCRIPT

    @model_validator(mode="after")
    def valid_interval(self) -> "MachineEvidenceCandidate":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("candidate evidence must have a positive source interval")
        return self


class HumanAudioConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    confirmation_id: str = Field(pattern=r"^confirm-[0-9a-f]{16}$")
    artifact_sha256: str = Field(pattern=SHA256_PATTERN)
    requirement_id: str = Field(min_length=1, max_length=64)
    requirement_sha256: str = Field(pattern=SHA256_PATTERN)
    requirement_type: Literal[
        "REQUIRED_TEXT", "REQUIRED_EXACT_TOKEN", "REQUIRED_BEFORE_TIME", "FORBIDDEN_TEXT"
    ]
    proposition: str = Field(min_length=1, max_length=700)
    confirmed_value: str = Field(min_length=1, max_length=500)
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    confirmed_at: datetime
    evidence_source: Literal[EvidenceSource.HUMAN_CONFIRMED_AUDIO_EVIDENCE] = EvidenceSource.HUMAN_CONFIRMED_AUDIO_EVIDENCE

    @model_validator(mode="after")
    def valid_confirmation(self) -> "HumanAudioConfirmation":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("confirmed evidence must have a positive source interval")
        if self.confirmed_at.tzinfo is None or self.confirmed_at.utcoffset() is None:
            raise ValueError("confirmation timestamp must include a timezone")
        return self


class AudioEvidenceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: EvidenceRecoveryStatus = EvidenceRecoveryStatus.NOT_NEEDED
    reason: str = Field(default="No local audio evidence recovery was requested.", min_length=1, max_length=500)
    artifact_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    engine: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    transcript_character_count: int = Field(default=0, ge=0)
    transcript_truncated: bool = False
    candidates: list[MachineEvidenceCandidate] = Field(default_factory=list, max_length=90)
    confirmations: list[HumanAudioConfirmation] = Field(default_factory=list, max_length=90)
    runtime_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def consistent_identity(self) -> "AudioEvidenceState":
        identities = {item.artifact_sha256 for item in [*self.candidates, *self.confirmations]}
        if self.artifact_sha256:
            identities.add(self.artifact_sha256)
        if len(identities) > 1:
            raise ValueError("all audio evidence must identify one exact artifact")
        ids = [item.candidate_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("machine evidence candidate ids must be unique")
        confirmation_requirements = [item.requirement_id for item in self.confirmations]
        if len(confirmation_requirements) != len(set(confirmation_requirements)):
            raise ValueError("only one active confirmation is allowed per requirement")
        return self


def recover_machine_evidence(
    *,
    artifact_path: Path,
    artifact_sha256: str,
    contract: ReleaseContract | None,
    current_evaluation: ReleaseContractEvaluation,
    segments: list[Any],
    model: str,
    maximum_candidates_per_requirement: int,
    maximum_transcript_characters: int,
    started_at: float | None = None,
) -> tuple[AudioEvidenceState, ReleaseContractEvaluation]:
    started = started_at if started_at is not None else perf_counter()
    del artifact_path
    eligible = _eligible_requirements(contract, current_evaluation)
    if not eligible:
        state = AudioEvidenceState(
            status=EvidenceRecoveryStatus.NOT_NEEDED,
            reason="No unresolved caption-dependent requirements need local audio evidence.",
            artifact_sha256=artifact_sha256,
            runtime_seconds=perf_counter() - started,
        )
        return state, current_evaluation

    bounded_segments, character_count, truncated = _bounded_segments(
        segments, maximum_transcript_characters
    )
    candidates: list[MachineEvidenceCandidate] = []
    stored_candidate_characters = 0
    for requirement in eligible:
        matches = [segment for segment in bounded_segments if _matches(requirement, segment.text)]
        for segment in matches[:maximum_candidates_per_requirement]:
            candidate = _candidate(artifact_sha256, requirement, segment, model)
            if stored_candidate_characters + len(candidate.machine_text) > maximum_transcript_characters:
                break
            candidates.append(candidate)
            stored_candidate_characters += len(candidate.machine_text)
    state = AudioEvidenceState(
        status=EvidenceRecoveryStatus.COMPLETED,
        reason=(
            f"Local transcription suggested {len(candidates)} bounded evidence candidate(s)."
            if candidates else
            "Local transcription found no reliable candidate; this does not prove the required text is absent."
        ),
        artifact_sha256=artifact_sha256,
        engine="faster-whisper",
        model=model,
        transcript_character_count=character_count,
        transcript_truncated=truncated,
        candidates=candidates,
        runtime_seconds=perf_counter() - started,
    )
    return state, apply_machine_candidates(current_evaluation, state)


def unavailable_evidence_state(*, artifact_sha256: str, code: str, message: str, runtime_seconds: float) -> AudioEvidenceState:
    return AudioEvidenceState(
        status=EvidenceRecoveryStatus.UNAVAILABLE,
        reason=f"{message} ({code})",
        artifact_sha256=artifact_sha256,
        runtime_seconds=runtime_seconds,
    )


def apply_machine_candidates(
    evaluation: ReleaseContractEvaluation,
    state: AudioEvidenceState,
) -> ReleaseContractEvaluation:
    by_requirement = {item.requirement_id: item for item in state.candidates}
    results: list[ContractRequirementResult] = []
    for result in evaluation.results:
        candidate = by_requirement.get(result.requirement_id)
        recoverable_missing_caption = (
            result.status is ContractStatus.FAIL
            and result.evidence_source is EvidenceSource.SUPPLIED_CAPTIONS
            and result.requirement_type in {"REQUIRED_TEXT", "REQUIRED_EXACT_TOKEN", "REQUIRED_BEFORE_TIME"}
        )
        if candidate is None or not (
            result.status is ContractStatus.NOT_EVALUATED or recoverable_missing_caption
        ):
            results.append(result)
            continue
        timing = format_timecode(candidate.start_seconds)
        qualifier = (
            " after the requested deadline" if candidate.requirement_type == "REQUIRED_BEFORE_TIME"
            and _deadline(evaluation.contract, candidate.requirement_id) is not None
            and candidate.start_seconds > _deadline(evaluation.contract, candidate.requirement_id) else ""
        )
        results.append(result.model_copy(update={
            "status": ContractStatus.NEEDS_REVIEW,
            "evidence": f'Local transcription suggests “{candidate.machine_text}” at {timing}{qualifier}. Confirm the source audio before relying on it.',
            "evidence_source": EvidenceSource.LOCAL_MACHINE_TRANSCRIPT,
            "timestamp_seconds": candidate.start_seconds,
            "confidence": candidate.confidence,
            "reason_code": "machine_audio_evidence_candidate",
            "audio_evidence": _candidate_reference(candidate),
        }))
    return _evaluation(evaluation.contract, results, evaluation.runtime_seconds + state.runtime_seconds)


def confirm_machine_candidate(
    *,
    evaluation: ReleaseContractEvaluation,
    state: AudioEvidenceState,
    candidate_id: str,
    artifact_sha256: str,
    confirmed_at: datetime | None = None,
) -> tuple[AudioEvidenceState, ReleaseContractEvaluation]:
    candidate = next((item for item in state.candidates if item.candidate_id == candidate_id), None)
    if candidate is None:
        raise ValueError("The selected evidence candidate is not part of this report.")
    if candidate.candidate_id != _candidate_id(candidate):
        raise ValueError("The evidence range or proposition changed after recovery.")
    if state.artifact_sha256 != artifact_sha256 or candidate.artifact_sha256 != artifact_sha256:
        raise ValueError("The evidence confirmation does not belong to this video artifact.")
    requirement = next(
        (item for item in (evaluation.contract.requirements if evaluation.contract else []) if item.id == candidate.requirement_id),
        None,
    )
    if requirement is None or requirement_sha256(requirement) != candidate.requirement_sha256:
        raise ValueError("The release requirement changed after this evidence was recovered.")
    if requirement.type != candidate.requirement_type or getattr(requirement, "value", None) != candidate.expected_value:
        raise ValueError("The evidence proposition no longer matches the release requirement.")

    now = confirmed_at or datetime.now(timezone.utc)
    confirmation = HumanAudioConfirmation(
        confirmation_id="confirm-" + hashlib.sha256(
            f"{candidate.candidate_id}|{artifact_sha256}|{now.isoformat()}".encode()
        ).hexdigest()[:16],
        artifact_sha256=artifact_sha256,
        requirement_id=requirement.id,
        requirement_sha256=candidate.requirement_sha256,
        requirement_type=requirement.type,
        proposition=candidate.proposition,
        confirmed_value=candidate.expected_value,
        start_seconds=candidate.start_seconds,
        end_seconds=candidate.end_seconds,
        confirmed_at=now,
    )
    confirmations = [item for item in state.confirmations if item.requirement_id != requirement.id]
    confirmations.append(confirmation)
    updated_state = state.model_copy(update={"confirmations": confirmations})
    updated_results: list[ContractRequirementResult] = []
    for result in evaluation.results:
        if result.requirement_id != requirement.id:
            updated_results.append(result)
            continue
        if requirement.type == "FORBIDDEN_TEXT":
            status = ContractStatus.FAIL
            evidence = f'You confirmed that “{requirement.value}” occurs in the source audio at {format_timecode(candidate.start_seconds)}.'
            reason = "human_confirmed_forbidden_presence"
        elif requirement.type == "REQUIRED_BEFORE_TIME" and candidate.start_seconds > requirement.before_seconds:
            status = ContractStatus.NEEDS_REVIEW
            evidence = (
                f'You confirmed “{requirement.value}” at {format_timecode(candidate.start_seconds)}, after the '
                f'{format_timecode(requirement.before_seconds)} deadline. This clip cannot prove there was no earlier occurrence.'
            )
            reason = "human_confirmed_after_deadline"
        else:
            status = ContractStatus.PASS
            evidence = f'You confirmed that “{requirement.value}” occurs in the source audio at {format_timecode(candidate.start_seconds)}.'
            reason = "human_confirmed_presence"
        updated_results.append(result.model_copy(update={
            "status": status,
            "evidence": evidence,
            "evidence_source": EvidenceSource.HUMAN_CONFIRMED_AUDIO_EVIDENCE,
            "timestamp_seconds": candidate.start_seconds,
            "confidence": None,
            "reason_code": reason,
            "audio_evidence": _confirmation_reference(confirmation),
        }))
    return updated_state, _evaluation(evaluation.contract, updated_results, evaluation.runtime_seconds)


def requirement_sha256(requirement: Any) -> str:
    encoded = json.dumps(
        requirement.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _eligible_requirements(contract, evaluation):
    if contract is None:
        return []
    recoverable = {
        item.requirement_id for item in evaluation.results
        if (
            item.status is ContractStatus.NOT_EVALUATED
            and item.reason_code == "text_evidence_unavailable"
        ) or (
            item.status is ContractStatus.FAIL
            and item.evidence_source is EvidenceSource.SUPPLIED_CAPTIONS
            and item.requirement_type in {"REQUIRED_TEXT", "REQUIRED_EXACT_TOKEN", "REQUIRED_BEFORE_TIME"}
        )
    }
    return [item for item in contract.requirements if item.id in recoverable and item.type in RECOVERABLE_TYPES]


def _bounded_segments(segments: list[Any], maximum_characters: int):
    kept: list[_EvidenceSegment] = []
    count = 0
    truncated = False
    for segment in sorted(segments, key=lambda item: (item.start_seconds, item.end_seconds)):
        text = " ".join(segment.text.split())
        if not text:
            continue
        remaining = maximum_characters - count
        if remaining <= 0:
            truncated = True
            break
        if len(text) > remaining:
            text = text[:remaining].rstrip()
            truncated = True
        if text:
            kept.append(_EvidenceSegment(segment.start_seconds, segment.end_seconds, text))
            count += len(text)
        if truncated:
            break
    return kept, count, truncated


def _matches(requirement, text: str) -> bool:
    return _token_present(text, requirement.value) if requirement.type == "REQUIRED_EXACT_TOKEN" else _phrase_present(text, requirement.value)


def _candidate(artifact_sha256: str, requirement, segment: _EvidenceSegment, model: str):
    requirement_digest = requirement_sha256(requirement)
    proposition = f'This source-audio region contains “{requirement.value}”.'
    candidate = MachineEvidenceCandidate(
        candidate_id="audio-0000000000000000",
        artifact_sha256=artifact_sha256,
        requirement_id=requirement.id,
        requirement_sha256=requirement_digest,
        requirement_type=requirement.type,
        proposition=proposition,
        expected_value=requirement.value,
        start_seconds=segment.start_seconds,
        end_seconds=segment.end_seconds,
        machine_text=segment.text[:500].rstrip(),
        confidence=None,
        model=model,
    )
    return candidate.model_copy(update={"candidate_id": _candidate_id(candidate)})


def _candidate_id(candidate: MachineEvidenceCandidate) -> str:
    identity = (
        f"{candidate.artifact_sha256}|{candidate.requirement_sha256}|{candidate.requirement_type}|"
        f"{candidate.expected_value}|{candidate.start_seconds:.6f}|{candidate.end_seconds:.6f}|"
        f"{candidate.proposition}|{candidate.machine_text}|{candidate.engine}|{candidate.model}"
    )
    return "audio-" + hmac.new(
        _CANDIDATE_SIGNING_KEY, identity.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:16]


def _candidate_reference(candidate: MachineEvidenceCandidate):
    from creator_preflight.release_contract import ContractAudioEvidence
    return ContractAudioEvidence(
        artifact_sha256=candidate.artifact_sha256,
        start_seconds=candidate.start_seconds,
        end_seconds=candidate.end_seconds,
        proposition=candidate.proposition,
        machine_text=candidate.machine_text,
        transcription_engine=candidate.engine,
        transcription_model=candidate.model,
    )


def _confirmation_reference(confirmation: HumanAudioConfirmation):
    from creator_preflight.release_contract import ContractAudioEvidence
    return ContractAudioEvidence(
        artifact_sha256=confirmation.artifact_sha256,
        start_seconds=confirmation.start_seconds,
        end_seconds=confirmation.end_seconds,
        proposition=confirmation.proposition,
        confirmation_id=confirmation.confirmation_id,
        confirmed_at=confirmation.confirmed_at,
    )


def _deadline(contract: ReleaseContract | None, requirement_id: str) -> float | None:
    requirement = next((item for item in (contract.requirements if contract else []) if item.id == requirement_id), None)
    return getattr(requirement, "before_seconds", None)


def _evaluation(contract, results, runtime):
    return ReleaseContractEvaluation(
        contract=contract,
        results=results,
        passed_count=sum(item.status is ContractStatus.PASS for item in results),
        failed_count=sum(item.status is ContractStatus.FAIL for item in results),
        needs_review_count=sum(item.status is ContractStatus.NEEDS_REVIEW for item in results),
        not_evaluated_count=sum(item.status is ContractStatus.NOT_EVALUATED for item in results),
        runtime_seconds=runtime,
    )
