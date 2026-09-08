"""Bounded draft-caption generation from the existing local ASR adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from releaseseal.captions import CaptionCue, SpeechSegment, serialize_caption_cues

_DRAFT_SIGNING_KEY = secrets.token_bytes(32)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class GeneratedCaptionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    UNAVAILABLE = "UNAVAILABLE"


class GeneratedCaptionCue(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    index: int = Field(ge=1)
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def positive_interval(self) -> "GeneratedCaptionCue":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("generated caption cues must have positive intervals")
        return self


class GeneratedCaptionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    status: GeneratedCaptionStatus
    reason: str = Field(min_length=1, max_length=500)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal["LOCAL_MACHINE_TRANSCRIPT"] = "LOCAL_MACHINE_TRANSCRIPT"
    engine: Literal["faster-whisper"] = "faster-whisper"
    model: str = Field(min_length=1, max_length=200)
    cues: list[GeneratedCaptionCue] = Field(default_factory=list, max_length=5000)
    cue_count: int = Field(ge=0, le=5000)
    covered_seconds: float = Field(ge=0, allow_inf_nan=False)
    srt_text: str = Field(default="", max_length=500_000)
    download_filename: str = Field(min_length=1, max_length=255)
    runtime_seconds: float = Field(ge=0, allow_inf_nan=False)
    reuse_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def consistent_draft(self) -> "GeneratedCaptionDraft":
        if self.cue_count != len(self.cues):
            raise ValueError("generated caption cue count is inconsistent")
        if self.status is GeneratedCaptionStatus.COMPLETED:
            if not self.cues or not self.srt_text or not self.reuse_token:
                raise ValueError("completed generated captions require cues, SRT, and reuse identity")
        elif self.cues or self.srt_text or self.reuse_token:
            raise ValueError("unavailable generated captions cannot contain draft evidence")
        return self


def build_generated_caption_draft(
    *,
    artifact_path: Path,
    original_filename: str | None,
    segments: list[SpeechSegment],
    model: str,
    maximum_cues: int,
    maximum_characters: int,
    started_at: float | None = None,
) -> GeneratedCaptionDraft:
    started = started_at if started_at is not None else perf_counter()
    artifact_sha256 = _file_sha256(artifact_path)
    cues: list[CaptionCue] = []
    used_characters = 0
    previous_end = 0.0
    for segment in sorted(segments, key=lambda item: (item.start_seconds, item.end_seconds)):
        if len(cues) >= maximum_cues:
            break
        if not math.isfinite(segment.start_seconds) or not math.isfinite(segment.end_seconds):
            continue
        text = _sanitize_text(segment.text)
        start = max(0.0, float(segment.start_seconds), previous_end)
        end = max(0.0, float(segment.end_seconds))
        if not text or end <= start or used_characters + len(text) > maximum_characters:
            continue
        cues.append(CaptionCue(start, end, text, source_format="srt"))
        previous_end = end
        used_characters += len(text)
    filename = generated_caption_filename(original_filename)
    if not cues:
        return GeneratedCaptionDraft(
            status=GeneratedCaptionStatus.UNAVAILABLE,
            reason="Local transcription did not produce usable timed caption cues.",
            artifact_sha256=artifact_sha256,
            model=model,
            cue_count=0,
            covered_seconds=0,
            download_filename=filename,
            runtime_seconds=perf_counter() - started,
        )
    generated = [
        GeneratedCaptionCue(index=index, start_seconds=cue.start_seconds, end_seconds=cue.end_seconds, text=cue.text)
        for index, cue in enumerate(cues, 1)
    ]
    payload = _reuse_payload(artifact_sha256, model, generated)
    return GeneratedCaptionDraft(
        status=GeneratedCaptionStatus.COMPLETED,
        reason="Machine-generated captions are ready to preview and download.",
        artifact_sha256=artifact_sha256,
        model=model,
        cues=generated,
        cue_count=len(generated),
        covered_seconds=round(sum(cue.end_seconds - cue.start_seconds for cue in cues), 3),
        srt_text=serialize_caption_cues(cues, source_format="srt"),
        download_filename=filename,
        runtime_seconds=perf_counter() - started,
        reuse_token=hmac.new(_DRAFT_SIGNING_KEY, payload, hashlib.sha256).hexdigest(),
    )


def unavailable_generated_caption_draft(
    *, artifact_path: Path, original_filename: str | None, model: str, reason: str, started_at: float
) -> GeneratedCaptionDraft:
    return GeneratedCaptionDraft(
        status=GeneratedCaptionStatus.UNAVAILABLE,
        reason=reason,
        artifact_sha256=_file_sha256(artifact_path),
        model=model,
        cue_count=0,
        covered_seconds=0,
        download_filename=generated_caption_filename(original_filename),
        runtime_seconds=perf_counter() - started_at,
    )


def verified_reusable_segments(
    draft: GeneratedCaptionDraft, *, artifact_sha256: str, expected_model: str
) -> list[SpeechSegment]:
    if (
        draft.status is not GeneratedCaptionStatus.COMPLETED
        or draft.artifact_sha256 != artifact_sha256
        or draft.model != expected_model
        or draft.reuse_token is None
    ):
        raise ValueError("generated caption draft does not match this artifact and transcription configuration")
    payload = _reuse_payload(draft.artifact_sha256, draft.model, draft.cues)
    expected = hmac.new(_DRAFT_SIGNING_KEY, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(draft.reuse_token, expected):
        raise ValueError("generated caption draft identity is invalid")
    return [SpeechSegment(item.start_seconds, item.end_seconds, item.text) for item in draft.cues]


def generated_caption_filename(filename: str | None) -> str:
    stem = Path(filename or "video").stem
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or "video"
    return f"{safe}.generated.srt"


def _sanitize_text(text: str) -> str:
    cleaned = _CONTROL_CHARACTERS.sub("", str(text)).replace("\r", " ").replace("\n", " ")
    return " ".join(cleaned.split())[:1000]


def _reuse_payload(artifact_sha256: str, model: str, cues: list[Any]) -> bytes:
    values = [
        {"start_seconds": cue.start_seconds, "end_seconds": cue.end_seconds, "text": cue.text}
        for cue in cues
    ]
    return json.dumps(
        {"artifact_sha256": artifact_sha256, "model": model, "cues": values},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
