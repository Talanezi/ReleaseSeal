import subprocess
from pathlib import Path

import pytest

from releaseseal.engine import PreflightScanner
from releaseseal.media import MediaInspector
from releaseseal.models import Finding, FindingSeverity, FindingStatus, PublishingPackage
from releaseseal.repair_models import RepairOperation
from releaseseal.repairs import FFmpegRepairEngine, build_repair_plan
from releaseseal.verification import (
    TimelineTransform,
    build_review_reel_manifest,
    compare_findings,
    detect_unexpected_visual_changes,
    transform_caption_cues,
    transform_caption_file,
    verify_repair,
)
from releaseseal.captions import CaptionCue, parse_caption_text
from releaseseal.verification_models import FindingComparison, FindingComparisonStatus, RepairVerificationStatus


def _remove(start: float, end: float) -> RepairOperation:
    return RepairOperation(operation_type="REMOVE_RANGE", start_seconds=start, end_seconds=end)


def test_timeline_transform_no_and_one_removal() -> None:
    identity = TimelineTransform(10, [])
    assert identity.original_to_repaired(4) == 4
    transform = TimelineTransform(10, [_remove(2, 5)])
    assert transform.expected_duration == 7
    assert transform.original_to_repaired(1) == 1
    assert transform.original_to_repaired(3) is None
    assert transform.original_to_repaired(7) == 4
    assert transform.repaired_to_original(4) == 7
    assert transform.interval_removed(2, 5)


def test_timeline_transform_multiple_ranges_and_round_trip() -> None:
    transform = TimelineTransform(60, [_remove(36, 48), _remove(12, 15)])
    assert transform.expected_duration == 45
    assert transform.original_to_repaired(20) == 17
    assert transform.original_to_repaired(50) == 35
    for timestamp in (0, 10, 16, 30, 49, 59):
        mapped = transform.original_to_repaired(timestamp)
        assert mapped is not None
        assert transform.repaired_to_original(mapped) == pytest.approx(timestamp)


def test_caption_cues_follow_one_remove_range_without_mutating_source() -> None:
    source = [
        CaptionCue(0, 1, "Before", source_format="srt"),
        CaptionCue(6, 8, "After", source_format="srt"),
        CaptionCue(3, 4, "Inside", source_format="srt"),
        CaptionCue(1, 3, "Overlaps start", source_format="srt"),
        CaptionCue(4, 6, "Overlaps end", source_format="srt"),
        CaptionCue(1, 6, "Spans cut", source_format="srt"),
    ]
    snapshot = list(source)

    transformed = transform_caption_cues(source, TimelineTransform(10, [_remove(2, 5)]))
    by_text = {cue.text: (cue.start_seconds, cue.end_seconds) for cue in transformed}

    assert by_text == {
        "Before": (0, 1),
        "After": (3, 5),
        "Overlaps start": (1, 2),
        "Overlaps end": (2, 3),
        "Spans cut": (1, 3),
    }
    assert "Inside" not in by_text
    assert source == snapshot


def test_caption_cues_follow_multiple_ranges_and_stay_inside_repaired_duration() -> None:
    source = [CaptionCue(1, 9, "Across both", source_format="vtt"), CaptionCue(9, 10, "Ending", source_format="vtt")]
    transform = TimelineTransform(10, [_remove(2, 4), _remove(7, 8)])

    transformed = transform_caption_cues(source, transform)

    assert [(cue.start_seconds, cue.end_seconds) for cue in transformed] == [(1, 6), (6, 7)]
    assert transformed[-1].end_seconds == transform.expected_duration


def test_caption_file_transform_serializes_valid_repaired_timeline(tmp_path: Path) -> None:
    source = tmp_path / "source.srt"
    destination = tmp_path / "repaired.srt"
    original_text = "1\n00:00:01,000 --> 00:00:06,000\nAcross the cut\n\n2\n00:00:09,000 --> 00:00:10,000\nEnding\n"
    source.write_text(original_text, encoding="utf-8")

    result_path = transform_caption_file(source, destination, original_duration=10, operations=[_remove(2, 5)])
    parsed = parse_caption_text(result_path.read_text(encoding="utf-8"))

    assert [(cue.start_seconds, cue.end_seconds) for cue in parsed.cues] == [(1, 3), (6, 7)]
    assert source.read_text(encoding="utf-8") == original_text


def test_clean_black_repair_verifies_and_compares_findings(api_anomaly_video: Path, tmp_path: Path) -> None:
    package = PublishingPackage(title="Repair verification", description="A valid package")
    scanner = PreflightScanner()
    original = scanner.scan(api_anomaly_video, package)
    operation = _remove(2, 5)
    repaired_path = tmp_path / "repaired.mp4"
    FFmpegRepairEngine().render(api_anomaly_video, repaired_path, [operation])
    repaired = scanner.scan(repaired_path, package)

    report = verify_repair(api_anomaly_video, repaired_path, [operation], original, repaired)

    assert report.integrity.passed is True
    assert report.repaired_duration_seconds == pytest.approx(9, abs=0.35)
    assert next(item for item in report.resolved if item.original_finding.code == "VIDEO_BLACK_SEGMENT").deterministically_verified
    freeze = next(item for item in report.remaining if item.original_finding.code == "VIDEO_FREEZE_SEGMENT")
    assert freeze.expected_repaired_start_seconds == pytest.approx(4, abs=0.2)
    assert report.new == []
    assert report.unexpected_changes == []
    assert report.review_reel_manifest.entries


def test_ai_absence_is_not_blindly_classified_resolved(api_anomaly_video: Path) -> None:
    scanner = PreflightScanner()
    base = scanner.scan(api_anomaly_video, PublishingPackage(title="Title", description="Description"))
    ai_finding = Finding(code="AI_VISIBLE_PLACEHOLDER", severity=FindingSeverity.WARNING, status=FindingStatus.NEEDS_REVIEW, message="Placeholder", source="ai.gemini.viewer", timestamp_start_seconds=7, timestamp_end_seconds=8)
    original = base.model_copy(update={"findings": [ai_finding]})
    repaired = base.model_copy(update={"findings": []})
    _, remaining, _ = compare_findings(original, repaired, TimelineTransform(12, [_remove(2, 5)]), [_remove(2, 5)])
    assert remaining[0].original_finding.code == "AI_VISIBLE_PLACEHOLDER"


def test_visual_regression_detects_deliberate_unaffected_mutation(api_anomaly_video: Path, tmp_path: Path) -> None:
    operation = _remove(2, 5)
    repaired = tmp_path / "repaired.mp4"
    mutated = tmp_path / "mutated.mp4"
    FFmpegRepairEngine().render(api_anomaly_video, repaired, [operation])
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(repaired),
        "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=magenta:t=fill:enable='between(t,0.5,1.5)'",
        "-c:v", "libx264", "-crf", "20", "-c:a", "aac", str(mutated),
    ], check=True, timeout=30)
    changes = detect_unexpected_visual_changes(api_anomaly_video, mutated, TimelineTransform(12, [operation]))
    assert len(changes) == 1
    assert changes[0].start_seconds == pytest.approx(0.5, abs=0.3)
    assert changes[0].end_seconds == pytest.approx(1.5, abs=0.3)
    package = PublishingPackage(title="Title", description="Description")
    scanner = PreflightScanner()
    verification = verify_repair(api_anomaly_video, mutated, [operation], scanner.scan(api_anomaly_video, package), scanner.scan(mutated, package))
    assert verification.status is RepairVerificationStatus.NEEDS_REVIEW
    assert verification.review_reel_manifest.entries[0].category == "unexpected"
    assert "Unexpected visual change" in verification.review_reel_manifest.entries[0].reason


def test_visual_regression_aligns_hard_cuts_after_fractional_frame_removal(tmp_path: Path) -> None:
    source = tmp_path / "hard-cuts.mp4"
    repaired = tmp_path / "hard-cuts-repaired.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=24:d=10",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=10",
        "-vf",
        "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,2,3.041667)',"
        "drawbox=x=0:y=0:w=iw:h=ih:color=red:t=fill:enable='between(t,4.25,5.25)',"
        "drawbox=x=0:y=0:w=iw:h=ih:color=green:t=fill:enable='between(t,7.25,8.25)'",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
    ], check=True, timeout=30)
    operation = _remove(2, 3.041667)
    FFmpegRepairEngine().render(source, repaired, [operation])

    assert detect_unexpected_visual_changes(
        source,
        repaired,
        TimelineTransform(MediaInspector().inspect(source).duration_seconds or 10, [operation]),
    ) == []


def test_global_finding_matches_and_repaired_only_finding_is_new(api_anomaly_video: Path) -> None:
    base = PreflightScanner().scan(api_anomaly_video, PublishingPackage(title="Title", description="Description"))
    global_finding = next(finding for finding in base.findings if finding.timestamp_start_seconds is None)
    new_finding = Finding(code="REPAIRED_ONLY", severity=FindingSeverity.WARNING, status=FindingStatus.NEEDS_REVIEW, message="New", source="test", timestamp_start_seconds=1, timestamp_end_seconds=2)
    original = base.model_copy(update={"findings": [global_finding]})
    repaired = base.model_copy(update={"findings": [global_finding, new_finding], "execution_issues": []})
    _, remaining, new = compare_findings(original, repaired, TimelineTransform(12, [_remove(2, 5)]), [_remove(2, 5)])
    assert remaining[0].original_finding.code == global_finding.code
    assert new[0].repaired_finding.code == "REPAIRED_ONLY"
    assert "newly detected during the repaired scan" in new[0].explanation
    assert "unexpected" not in new[0].explanation.lower()
    assert "regression" not in new[0].explanation.lower()
    assert new[0].model_dump(mode="json")["status"] == "NEW"


def test_review_reel_manifest_merges_context_and_is_bounded() -> None:
    transform = TimelineTransform(60, [_remove(12, 15)])
    finding = Finding(code="NEW", severity=FindingSeverity.WARNING, status=FindingStatus.NEEDS_REVIEW, message="New evidence", source="test", timestamp_start_seconds=13, timestamp_end_seconds=14)
    comparison = FindingComparison(status=FindingComparisonStatus.NEW, repaired_finding=finding, explanation="New")
    manifest = build_review_reel_manifest(57, [_remove(12, 15)], transform, [], [comparison], [])
    assert len(manifest.entries) == 1
    assert manifest.total_duration_seconds <= 180


def test_review_reel_renders_playable_video_and_audio(api_anomaly_video: Path, tmp_path: Path) -> None:
    output = tmp_path / "reel.mp4"
    result = FFmpegRepairEngine().render_segments(api_anomaly_video, output, [(0, 2), (6, 8)])
    media = MediaInspector().inspect(output)
    assert result.output_duration_seconds == pytest.approx(4, abs=0.3)
    assert media.has_video and media.has_audio


def test_video_only_review_reel(video_without_audio: Path, tmp_path: Path) -> None:
    output = tmp_path / "reel.mp4"
    FFmpegRepairEngine().render_segments(video_without_audio, output, [(0, 0.8)])
    media = MediaInspector().inspect(output)
    assert media.has_video and not media.has_audio


def test_duplicate_style_integrity_preserves_reference_interval(api_anomaly_video: Path, tmp_path: Path) -> None:
    finding = Finding(code="AI_ACCIDENTAL_REPETITION", severity=FindingSeverity.WARNING, status=FindingStatus.NEEDS_REVIEW, message="Repeated", source="ai.gemini.viewer", timestamp_start_seconds=7, timestamp_end_seconds=10, details={"original_start_seconds": 0, "original_end_seconds": 2})
    scanner = PreflightScanner(); package = PublishingPackage(title="Title", description="Description")
    original = scanner.scan(api_anomaly_video, package).model_copy(update={"findings": [finding], "repair_plan": build_repair_plan([finding])})
    operation = original.repair_plan.proposals[0].operation
    assert operation is not None
    output = tmp_path / "duplicate-removed.mp4"
    FFmpegRepairEngine().render(api_anomaly_video, output, [operation])
    repaired = scanner.scan(output, package).model_copy(update={"findings": []})
    verified = verify_repair(api_anomaly_video, output, [operation], original, repaired)
    assert verified.integrity.reference_intervals_survived is True
    assert verified.resolved[0].deterministically_verified is True
