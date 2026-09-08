from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from releaseseal.captions import CaptionCue, SpeechSegment
from releaseseal.models import CaptionSummary, MediaInspection, PublishingPackage
from releaseseal.release_contract import (
    ContractStatus,
    EvidenceSource,
    ForbiddenText,
    MaxDuration,
    ReleaseContract,
    RequiredBeforeTime,
    RequiredExactToken,
    RequiredTalkingPoint,
    RequiredText,
    RequiredUrl,
    evaluate_release_contract,
)
from releaseseal.release_evidence import (
    EvidenceRecoveryStatus,
    confirm_machine_candidate,
    recover_machine_evidence,
)
from releaseseal.release_plan import ReleasePlanCategory, build_release_plan
from releaseseal.repair_models import RepairPlan


SHA = "a" * 64


def _evaluation(requirements):
    return evaluate_release_contract(
        ReleaseContract(requirements=requirements),
        package=PublishingPackage(title="Title", description="Description"),
        media=MediaInspection(
            duration_seconds=60, format_name="mp4", file_size_bytes=1,
            has_video=True, video_stream_count=1, video_codec="h264", width=1280, height=720,
            has_audio=True, audio_stream_count=1, audio_codec="aac",
        ),
        caption_cues=[], caption_summary=None, caption_findings=[],
    )


def _caption_evaluation(requirements, cues):
    return evaluate_release_contract(
        ReleaseContract(requirements=requirements),
        package=PublishingPackage(title="Title", description="Description"),
        media=MediaInspection(
            duration_seconds=60, format_name="mp4", file_size_bytes=1,
            has_video=True, video_stream_count=1, video_codec="h264", width=1280, height=720,
            has_audio=True, audio_stream_count=1, audio_codec="aac",
        ),
        caption_cues=cues,
        caption_summary=CaptionSummary(
            source_format="srt", cue_count=len(cues), first_caption_seconds=cues[0].start_seconds,
            last_caption_seconds=cues[-1].end_seconds,
            covered_duration_seconds=sum(cue.end_seconds - cue.start_seconds for cue in cues),
            timeline_coverage_percent=10,
        ),
        caption_findings=[],
    )


def _recover(requirements, segments):
    evaluation = _evaluation(requirements)
    return recover_machine_evidence(
        artifact_path=Path("unused.mp4"), artifact_sha256=SHA,
        contract=evaluation.contract, current_evaluation=evaluation,
        segments=segments, model="tiny.en", maximum_candidates_per_requirement=3,
        maximum_transcript_characters=20_000,
    )


def test_machine_evidence_candidates_are_advisory_and_provenance_bound():
    requirements = [
        RequiredExactToken(id="code", type="REQUIRED_EXACT_TOKEN", instruction="Use SAVE25", value="SAVE25"),
        RequiredBeforeTime(id="early", type="REQUIRED_BEFORE_TIME", instruction="Mention AcmeVPN by 30 seconds", value="AcmeVPN", before_seconds=30),
        ForbiddenText(id="forbidden", type="FORBIDDEN_TEXT", instruction="Avoid guaranteed protection", value="guaranteed protection"),
    ]
    state, evaluation = _recover(requirements, [
        SpeechSegment(12.25, 14.0, "Use SAVE25 today"),
        SpeechSegment(42.18, 44.0, "AcmeVPN is available"),
        SpeechSegment(50.0, 52.0, "guaranteed protection"),
    ])
    assert state.status is EvidenceRecoveryStatus.COMPLETED
    assert len(state.candidates) == 3
    assert all(item.artifact_sha256 == SHA for item in state.candidates)
    assert all(item.engine == "faster-whisper" and item.model == "tiny.en" for item in state.candidates)
    assert [item.status for item in evaluation.results] == [ContractStatus.NEEDS_REVIEW] * 3
    assert all(item.evidence_source is EvidenceSource.LOCAL_MACHINE_TRANSCRIPT for item in evaluation.results)
    assert "00:42.18" in evaluation.results[1].evidence
    assert not any(item.status is ContractStatus.PASS for item in evaluation.results)
    assert not any(item.status is ContractStatus.FAIL for item in evaluation.results)


def test_machine_transcript_absence_never_proves_absence():
    requirements = [
        RequiredText(id="required", type="REQUIRED_TEXT", instruction="Mention Acme", value="Acme"),
        ForbiddenText(id="forbidden", type="FORBIDDEN_TEXT", instruction="Avoid claim", value="absolute guarantee"),
    ]
    state, evaluation = _recover(requirements, [SpeechSegment(1, 2, "unrelated words")])
    assert state.candidates == []
    assert "does not prove" in state.reason
    assert [item.status for item in evaluation.results] == [ContractStatus.NOT_EVALUATED] * 2


def test_supplied_caption_truth_remains_deterministic_but_missing_positive_text_can_recover():
    requirement = RequiredExactToken(
        id="required", type="REQUIRED_EXACT_TOKEN", instruction="Use SAVE25", value="SAVE25",
    )
    present = _caption_evaluation([requirement], [CaptionCue(1, 2, "SAVE25")])
    present_state, unchanged = recover_machine_evidence(
        artifact_path=Path("unused.mp4"), artifact_sha256=SHA, contract=present.contract,
        current_evaluation=present, segments=[SpeechSegment(3, 4, "SAVE25")], model="tiny.en",
        maximum_candidates_per_requirement=3, maximum_transcript_characters=20_000,
    )
    assert present_state.status is EvidenceRecoveryStatus.NOT_NEEDED
    assert unchanged.results[0].status is ContractStatus.PASS

    missing = _caption_evaluation([requirement], [CaptionCue(1, 2, "SAVE20")])
    assert missing.results[0].status is ContractStatus.FAIL
    recovered_state, recovered = recover_machine_evidence(
        artifact_path=Path("unused.mp4"), artifact_sha256=SHA, contract=missing.contract,
        current_evaluation=missing, segments=[SpeechSegment(3, 4, "SAVE25")], model="tiny.en",
        maximum_candidates_per_requirement=3, maximum_transcript_characters=20_000,
    )
    assert recovered_state.status is EvidenceRecoveryStatus.COMPLETED
    assert recovered.results[0].status is ContractStatus.NEEDS_REVIEW
    assert recovered.results[0].evidence_source is EvidenceSource.LOCAL_MACHINE_TRANSCRIPT


def test_human_confirmation_upgrades_only_the_bounded_proposition():
    requirements = [
        RequiredExactToken(id="code", type="REQUIRED_EXACT_TOKEN", instruction="Use SAVE25", value="SAVE25"),
        RequiredBeforeTime(id="early", type="REQUIRED_BEFORE_TIME", instruction="Mention AcmeVPN by 30 seconds", value="AcmeVPN", before_seconds=30),
        ForbiddenText(id="forbidden", type="FORBIDDEN_TEXT", instruction="Avoid prohibited phrase", value="guaranteed protection"),
    ]
    state, evaluation = _recover(requirements, [
        SpeechSegment(12, 13, "SAVE25"), SpeechSegment(42, 43, "AcmeVPN"),
        SpeechSegment(50, 51, "guaranteed protection"),
    ])
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    by_requirement = {item.requirement_id: item for item in state.candidates}
    state, evaluation = confirm_machine_candidate(
        evaluation=evaluation, state=state, candidate_id=by_requirement["code"].candidate_id,
        artifact_sha256=SHA, confirmed_at=now,
    )
    assert evaluation.results[0].status is ContractStatus.PASS
    assert evaluation.results[0].evidence_source is EvidenceSource.HUMAN_CONFIRMED_AUDIO_EVIDENCE
    assert evaluation.results[0].audio_evidence.confirmed_at == now
    state, evaluation = confirm_machine_candidate(
        evaluation=evaluation, state=state, candidate_id=by_requirement["early"].candidate_id,
        artifact_sha256=SHA, confirmed_at=now,
    )
    assert evaluation.results[1].status is ContractStatus.NEEDS_REVIEW
    assert "cannot prove there was no earlier occurrence" in evaluation.results[1].evidence
    state, evaluation = confirm_machine_candidate(
        evaluation=evaluation, state=state, candidate_id=by_requirement["forbidden"].candidate_id,
        artifact_sha256=SHA, confirmed_at=now,
    )
    assert evaluation.results[2].status is ContractStatus.FAIL
    assert evaluation.results[2].evidence_source is EvidenceSource.HUMAN_CONFIRMED_AUDIO_EVIDENCE


def test_confirmation_rejects_stale_artifact_or_changed_requirement():
    requirement = RequiredExactToken(id="code", type="REQUIRED_EXACT_TOKEN", instruction="Use SAVE25", value="SAVE25")
    state, evaluation = _recover([requirement], [SpeechSegment(12, 13, "SAVE25")])
    candidate = state.candidates[0]
    with pytest.raises(ValueError, match="artifact"):
        confirm_machine_candidate(evaluation=evaluation, state=state, candidate_id=candidate.candidate_id, artifact_sha256="b" * 64)
    changed = _evaluation([RequiredExactToken(id="code", type="REQUIRED_EXACT_TOKEN", instruction="Use SAVE20", value="SAVE20")])
    with pytest.raises(ValueError, match="changed"):
        confirm_machine_candidate(evaluation=changed, state=state, candidate_id=candidate.candidate_id, artifact_sha256=SHA)

    changed_range = state.model_copy(update={
        "candidates": [candidate.model_copy(update={"start_seconds": 13})],
    })
    with pytest.raises(ValueError, match="range or proposition"):
        confirm_machine_candidate(
            evaluation=evaluation, state=changed_range,
            candidate_id=candidate.candidate_id, artifact_sha256=SHA,
        )

    changed_proposition = state.model_copy(update={
        "candidates": [candidate.model_copy(update={"proposition": "This region says something else."})],
    })
    with pytest.raises(ValueError, match="range or proposition"):
        confirm_machine_candidate(
            evaluation=evaluation, state=changed_proposition,
            candidate_id=candidate.candidate_id, artifact_sha256=SHA,
        )


def test_release_plan_separates_blockers_safe_actions_evidence_and_review():
    state, evaluation = _recover(
        [
            RequiredExactToken(id="code", type="REQUIRED_EXACT_TOKEN", instruction="Use SAVE25", value="SAVE25"),
            MaxDuration(id="duration", type="MAX_DURATION", instruction="Under ten seconds", maximum_seconds=10),
            RequiredTalkingPoint(id="semantic", type="REQUIRED_TALKING_POINT", instruction="Discuss privacy", value="privacy"),
            RequiredUrl(id="spoken-url", type="REQUIRED_URL", instruction="Say the URL", value="https://example.com/deal"),
        ],
        [SpeechSegment(12, 13, "SAVE25")],
    )
    safe_proposal = SimpleNamespace(
        proposal_id="safe", finding_code="AI_ACCIDENTAL_REPETITION",
        operation=object(), repairability=SimpleNamespace(value="SAFE"),
        finding_title="Accidental duplicate", start_seconds=20,
    )
    human_proposal = SimpleNamespace(
        proposal_id="human", finding_code="AI_VISIBLE_PLACEHOLDER",
        operation=None, repairability=SimpleNamespace(value="HUMAN_ONLY"),
        finding_title="Needs editorial judgment", start_seconds=30,
    )
    plan = build_release_plan(
        contract=evaluation, repair_plan=SimpleNamespace(proposals=[safe_proposal, human_proposal]), audio_evidence=state
    )
    assert [item.category for item in plan.items] == [
        ReleasePlanCategory.BLOCKING_REQUIREMENT,
        ReleasePlanCategory.SAFE_AUTOMATION,
        ReleasePlanCategory.CONFIRM_EVIDENCE,
        ReleasePlanCategory.HUMAN_REVIEW,
        ReleasePlanCategory.HUMAN_REVIEW,
        ReleasePlanCategory.INFORMATIONAL,
    ]
    assert plan.blocking_requirement_count == 1
    assert plan.safe_automation_count == 1
    assert plan.confirm_evidence_count == 1
    assert plan.human_review_count == 2
    assert plan.informational_count == 1


def test_candidate_matching_is_bounded_and_fast():
    requirements = [RequiredText(id="required", type="REQUIRED_TEXT", instruction="Mention Acme", value="Acme")]
    segments = [SpeechSegment(index, index + .5, "Acme mention") for index in range(100)]
    state, _ = _recover(requirements, segments)
    assert len(state.candidates) == 3
    assert state.runtime_seconds < .1
