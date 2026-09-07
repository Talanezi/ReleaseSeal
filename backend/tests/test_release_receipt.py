import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from creator_preflight.config import PreflightConfig
from creator_preflight.engine import PreflightScanner
from creator_preflight.models import PublishingPackage
from creator_preflight.release_contract import MaxDuration, ReleaseContract, ReleaseContractEvaluation
from creator_preflight.release_receipt import (
    RECEIPT_ADAPTER,
    ReceiptVerificationStatus,
    ReceiptVerifier,
    build_final_export_receipt,
    build_revision_receipt,
    canonical_json_bytes,
    package_fingerprint,
)
from creator_preflight.repair_models import RepairOperation
from creator_preflight.revision_check import RevisionCheckService
from creator_preflight.revision_models import RevisionMap, RevisionSamplingPolicy, RevisionSegment, RevisionStreamSummary
from creator_preflight.verification_models import (
    RepairIntegrityResult,
    ReviewReelManifest,
    VerificationReport,
)


CONTROLLED_TIME = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def ready_report(video_with_audio: Path):
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    config.rules.video.allowed_aspect_ratios = ["16:9"]
    report = PreflightScanner(config=config).scan(
        video_with_audio,
        PublishingPackage(title="Exact title", description="Exact description"),
    )
    return report, config


def _receipt(video: Path, report, config, **kwargs):
    return build_final_export_receipt(
        shipping_video_path=video,
        report=report,
        config=config,
        title="Exact title",
        description="Exact description",
        created_at=CONTROLLED_TIME,
        **kwargs,
    )


def test_canonical_receipt_is_repeatable_and_valid(video_with_audio: Path, ready_report) -> None:
    report, config = ready_report
    first = _receipt(video_with_audio, report, config)
    second = _receipt(video_with_audio, report, config)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert ReceiptVerifier().verify(first.model_dump(mode="json"), video_path=video_with_audio).status is ReceiptVerificationStatus.VALID


@pytest.mark.parametrize("verdict", ["READY", "NEEDS_REVIEW", "BLOCKED"])
def test_receipt_preserves_recorded_verdict(video_with_audio: Path, ready_report, verdict: str) -> None:
    report, config = ready_report
    receipt = _receipt(video_with_audio, report.model_copy(update={"verdict": verdict}), config)
    assert receipt.verdict.value == verdict


def test_verification_without_required_video_is_incomplete(video_with_audio: Path, ready_report) -> None:
    report, config = ready_report
    receipt = _receipt(video_with_audio, report, config)
    assert ReceiptVerifier().verify(receipt.model_dump(mode="json")).status is ReceiptVerificationStatus.INCOMPLETE_VERIFICATION


@pytest.mark.parametrize("replacement", [b"one byte changed", b"entirely wrong video"])
def test_changed_or_wrong_video_mismatches(video_with_audio: Path, ready_report, tmp_path: Path, replacement: bytes) -> None:
    report, config = ready_report
    receipt = _receipt(video_with_audio, report, config)
    wrong = tmp_path / "wrong.mp4"
    wrong.write_bytes(replacement)
    result = ReceiptVerifier().verify(receipt.model_dump(mode="json"), video_path=wrong)
    assert result.status is ReceiptVerificationStatus.MISMATCH


def test_single_byte_media_mutation_mismatches(video_with_audio: Path, ready_report, tmp_path: Path) -> None:
    report, config = ready_report
    receipt = _receipt(video_with_audio, report, config)
    payload = bytearray(video_with_audio.read_bytes())
    payload[-1] ^= 1
    changed = tmp_path / "one-byte-changed.mp4"
    changed.write_bytes(payload)
    assert ReceiptVerifier().verify(receipt.model_dump(mode="json"), video_path=changed).status is ReceiptVerificationStatus.MISMATCH


def test_optional_assets_are_explicit_and_changes_mismatch(video_with_audio: Path, ready_report, tmp_path: Path) -> None:
    report, config = ready_report
    thumbnail = tmp_path / "thumb.jpg"; thumbnail.write_bytes(b"thumbnail")
    captions = tmp_path / "captions.srt"; captions.write_text("caption", encoding="utf-8")
    receipt = _receipt(video_with_audio, report, config, thumbnail_path=thumbnail, captions_path=captions)
    assert receipt.package.thumbnail.presence.value == "PRESENT"
    assert receipt.package.captions.presence.value == "PRESENT"
    changed_thumbnail = tmp_path / "changed.jpg"; changed_thumbnail.write_bytes(b"changed")
    changed_captions = tmp_path / "changed.srt"; changed_captions.write_text("changed", encoding="utf-8")
    assert ReceiptVerifier().verify(receipt.model_dump(mode="json"), video_path=video_with_audio, thumbnail_path=changed_thumbnail).status is ReceiptVerificationStatus.MISMATCH
    assert ReceiptVerifier().verify(receipt.model_dump(mode="json"), video_path=video_with_audio, captions_path=changed_captions).status is ReceiptVerificationStatus.MISMATCH


def test_package_fingerprint_changes_for_every_bound_component(video_with_audio: Path, ready_report, tmp_path: Path) -> None:
    report, config = ready_report
    absent = _receipt(video_with_audio, report, config)
    assert absent.package.thumbnail.presence.value == "ABSENT" and absent.package.thumbnail.sha256 is None
    variants = [
        build_final_export_receipt(shipping_video_path=video_with_audio, report=report, config=config, title="Changed title", description="Exact description", created_at=CONTROLLED_TIME),
        build_final_export_receipt(shipping_video_path=video_with_audio, report=report, config=config, title="Exact title", description="Changed description", created_at=CONTROLLED_TIME),
    ]
    thumb = tmp_path / "thumb.jpg"; thumb.write_bytes(b"")
    variants.append(_receipt(video_with_audio, report, config, thumbnail_path=thumb))
    captions = tmp_path / "captions.srt"; captions.write_text("caption", encoding="utf-8")
    variants.append(_receipt(video_with_audio, report, config, captions_path=captions))
    contract_a = ReleaseContract(requirements=[MaxDuration(id="duration", type="MAX_DURATION", instruction="Under ten", maximum_seconds=10)])
    contract_b = ReleaseContract(requirements=[MaxDuration(id="duration", type="MAX_DURATION", instruction="Under twenty", maximum_seconds=20)])
    report_a = report.model_copy(update={"release_contract": ReleaseContractEvaluation(contract=contract_a)})
    report_b = report.model_copy(update={"release_contract": ReleaseContractEvaluation(contract=contract_b)})
    variants.extend([_receipt(video_with_audio, report_a, config), _receipt(video_with_audio, report_b, config)])
    fingerprints = {absent.package.package_fingerprint_sha256, *(item.package.package_fingerprint_sha256 for item in variants)}
    assert len(fingerprints) == len(variants) + 1
    assert package_fingerprint(absent.package) == absent.package.package_fingerprint_sha256


def test_embedded_contract_cannot_differ_from_recorded_digest(video_with_audio: Path, ready_report) -> None:
    report, config = ready_report
    contract = ReleaseContract(requirements=[MaxDuration(id="duration", type="MAX_DURATION", instruction="Under ten", maximum_seconds=10)])
    report = report.model_copy(update={"release_contract": ReleaseContractEvaluation(contract=contract)})
    payload = _receipt(video_with_audio, report, config).model_dump(mode="json")
    payload["package"]["contract"]["contract"]["requirements"][0]["maximum_seconds"] = 20
    # Recomputing only the outer receipt digest cannot repair the internal contract binding.
    payload["receipt_content_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        RECEIPT_ADAPTER.validate_python(payload)


def test_contract_requirement_result_edit_invalidates_receipt(video_with_audio: Path, ready_report) -> None:
    _, config = ready_report
    contract = ReleaseContract(requirements=[MaxDuration(id="duration", type="MAX_DURATION", instruction="Under half a second", maximum_seconds=.5)])
    report = PreflightScanner(config=config).scan(
        video_with_audio,
        PublishingPackage(title="Exact title", description="Exact description", release_contract=contract),
    )
    payload = _receipt(video_with_audio, report, config).model_dump(mode="json")
    payload["package"]["contract"]["deterministic_results"][0]["status"] = "PASS"
    assert ReceiptVerifier().verify(payload, video_path=video_with_audio).status is ReceiptVerificationStatus.INVALID_RECEIPT


@pytest.mark.parametrize("path,value", [("verdict", "BLOCKED"), ("deterministic_results.contract_failed", 9)])
def test_modified_receipt_with_stale_digest_is_invalid(video_with_audio: Path, ready_report, path: str, value) -> None:
    report, config = ready_report
    payload = _receipt(video_with_audio, report, config).model_dump(mode="json")
    target = payload
    parts = path.split(".")
    for part in parts[:-1]: target = target[part]
    target[parts[-1]] = value
    assert ReceiptVerifier().verify(payload, video_path=video_with_audio).status is ReceiptVerificationStatus.INVALID_RECEIPT


def test_malformed_receipt_is_invalid(video_with_audio: Path) -> None:
    assert ReceiptVerifier().verify(b'{"receipt_kind":"UNKNOWN"}', video_path=video_with_audio).status is ReceiptVerificationStatus.INVALID_RECEIPT


def test_repaired_receipt_binds_both_roles_and_wrong_artifact_mismatches(video_with_audio: Path, ready_report, tmp_path: Path) -> None:
    report, config = ready_report
    repaired = tmp_path / "repaired.mp4"; repaired.write_bytes(video_with_audio.read_bytes() + b"repaired")
    operation = RepairOperation(operation_type="REMOVE_RANGE", start_seconds=.1, end_seconds=.2)
    repaired_report = report.model_copy(update={"media": report.media.model_copy(update={"file_size_bytes": repaired.stat().st_size})})
    verification = VerificationReport(
        status="VERIFIED", approved_repair_count=1, original_duration_seconds=1,
        repaired_duration_seconds=.9, expected_duration_seconds=.9,
        integrity=RepairIntegrityResult(passed=True, duration_matches=True, streams_match=True, resolution_matches=True, operations_verified=1, reference_intervals_survived=True, explanation="Valid"),
        repaired_preflight_report=repaired_report, regression_analysis_completeness="COMPLETE",
        review_reel_manifest=ReviewReelManifest(), review_reel_available=False,
    )
    receipt = _receipt(repaired, report, config, original_video_path=video_with_audio, operations=[operation], verification=verification)
    assert receipt.package.shipping_role == "REPAIRED"
    assert receipt.package.shipping_video == receipt.repair.repaired_video
    assert ReceiptVerifier().verify(receipt.model_dump(mode="json"), video_path=repaired).status is ReceiptVerificationStatus.VALID
    assert ReceiptVerifier().verify(receipt.model_dump(mode="json"), video_path=video_with_audio).status is ReceiptVerificationStatus.MISMATCH
    swapped = receipt.model_dump(mode="json")
    swapped["repair"]["original_video"], swapped["repair"]["repaired_video"] = swapped["repair"]["repaired_video"], swapped["repair"]["original_video"]
    assert ReceiptVerifier().verify(swapped, video_path=repaired).status is ReceiptVerificationStatus.INVALID_RECEIPT


def _revision_report(previous: Path, revised: Path):
    previous_hash = hashlib.sha256(previous.read_bytes()).hexdigest()
    revised_hash = hashlib.sha256(revised.read_bytes()).hexdigest()
    streams = RevisionStreamSummary(width=160, height=90, video_codec="h264", has_audio=True, audio_codec="aac")
    revision_map = RevisionMap(
        previous_sha256=previous_hash, revised_sha256=revised_hash,
        previous_duration_seconds=1, revised_duration_seconds=1,
        previous_streams=streams, revised_streams=streams,
        sampling_policy=RevisionSamplingPolicy(visual_samples_per_second=2, maximum_visual_samples=10, descriptor_width=17, descriptor_height=9, audio_sample_rate=8000, refinement_samples_per_second=6, maximum_refinement_samples=10),
        previous_sample_count=2, revised_sample_count=2, estimated_unchanged_duration_seconds=1, unchanged_ratio=1,
        segments=[RevisionSegment(segment_id="segment-0001", kind="UNCHANGED", previous_start_seconds=0, previous_end_seconds=1, revised_start_seconds=0, revised_end_seconds=1, visual_changed=False, audio_changed=False, match_confidence=1, boundary_confidence="high")],
        analysis_runtime_seconds=.1,
    )
    return RevisionCheckService().from_map(revision_map, "")


def test_revision_receipt_binds_roles_and_notes(tmp_path: Path) -> None:
    previous = tmp_path / "previous.mp4"; previous.write_bytes(b"previous")
    revised = tmp_path / "revised.mp4"; revised.write_bytes(b"revised")
    report = _revision_report(previous, revised)
    receipt = build_revision_receipt(previous_path=previous, revised_path=revised, notes="00:10 Restore title", report=report, config=PreflightConfig(), created_at=CONTROLLED_TIME)
    verifier = ReceiptVerifier()
    assert verifier.verify(receipt.model_dump(mode="json"), video_path=previous, revised_path=revised, revision_notes="00:10 Restore title").status is ReceiptVerificationStatus.VALID
    assert verifier.verify(receipt.model_dump(mode="json"), video_path=revised, revised_path=previous).status is ReceiptVerificationStatus.MISMATCH
    assert verifier.verify(receipt.model_dump(mode="json"), video_path=previous, revised_path=revised, revision_notes="00:11 Restore title").status is ReceiptVerificationStatus.MISMATCH


def test_receipt_generation_performs_no_provider_work(video_with_audio: Path, ready_report, monkeypatch) -> None:
    report, config = ready_report
    monkeypatch.setattr("creator_preflight.ai_review.GeminiVideoReviewer", lambda *args, **kwargs: pytest.fail("provider invoked"))
    assert _receipt(video_with_audio, report, config).receipt_content_sha256
