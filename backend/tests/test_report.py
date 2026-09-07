import json
from pathlib import Path

import pytest

from creator_preflight.config import PreflightConfig
from creator_preflight.engine import PreflightScanner
from creator_preflight.models import FindingStatus, PublishingPackage


def _test_config() -> PreflightConfig:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    config.rules.video.allowed_aspect_ratios = ["16:9"]
    return config


def _valid_package(**changes) -> PublishingPackage:
    values = {"title": "A valid title", "description": "A valid description"}
    values.update(changes)
    return PublishingPackage(**values)


def test_ready_report_and_passed_check_accounting(video_with_audio: Path) -> None:
    report = PreflightScanner(config=_test_config()).scan(
        video_with_audio, _valid_package()
    )

    assert report.verdict is FindingStatus.READY
    assert report.warning_count == 0
    assert report.critical_count == 0
    assert report.checks_run_count == 14
    assert report.passed_check_count == 14
    assert all(check.passed for check in report.checks)


def test_needs_review_report_counts_warning(video_with_audio: Path) -> None:
    config = _test_config()
    config.rules.title.maximum_recommended_length = 5
    report = PreflightScanner(config=config).scan(
        video_with_audio, _valid_package(title="A title that is long")
    )

    assert report.verdict is FindingStatus.NEEDS_REVIEW
    assert report.warning_count == 1
    assert report.critical_count == 0
    assert report.passed_check_count == report.checks_run_count - 1


def test_blocked_report_counts_critical_findings(video_with_audio: Path) -> None:
    report = PreflightScanner(config=_test_config()).scan(
        video_with_audio, PublishingPackage()
    )

    assert report.verdict is FindingStatus.BLOCKED
    assert report.warning_count == 1
    assert report.critical_count == 1
    assert report.passed_check_count == report.checks_run_count - 2


def test_missing_description_only_needs_review(video_with_audio: Path) -> None:
    report = PreflightScanner(config=_test_config()).scan(
        video_with_audio, PublishingPackage(title="A valid title")
    )

    assert report.verdict is FindingStatus.NEEDS_REVIEW
    assert report.warning_count == 1
    assert report.critical_count == 0
    assert [finding.code for finding in report.findings] == ["DESCRIPTION_REQUIRED"]


def test_reconciliation_ordering_and_json_serialization(anomaly_video: Path) -> None:
    config = _test_config()
    report = PreflightScanner(config=config).scan(anomaly_video, _valid_package())
    codes = [finding.code for finding in report.findings]

    freezes = [
        finding
        for finding in report.findings
        if finding.code == "VIDEO_FREEZE_SEGMENT"
    ]
    assert len(freezes) == 1
    assert freezes[0].timestamp_start_seconds == pytest.approx(7.0, abs=0.2)
    assert codes == [
        "VIDEO_BLACK_SEGMENT",
        "AUDIO_LONG_SILENCE",
        "VIDEO_FREEZE_SEGMENT",
        "AUDIO_PEAK_WARNING",
    ]
    payload = json.loads(report.model_dump_json())
    assert payload["verdict"] == "NEEDS_REVIEW"
    assert payload["schema_version"] == "1.9"
    assert payload["scan_completeness"] == "COMPLETE"
    assert payload["ai_review"]["status"] == "disabled"
    assert payload["repair_plan"]["preview_required_count"] == 1
    black_repair = payload["repair_plan"]["proposals"][0]
    assert black_repair["finding_code"] == "VIDEO_BLACK_SEGMENT"
    assert black_repair["repairability"] == "PREVIEW_REQUIRED"
    assert black_repair["operation"] == {
        "operation_type": "REMOVE_RANGE",
        "start_seconds": pytest.approx(2.0, abs=0.2),
        "end_seconds": pytest.approx(5.0, abs=0.2),
    }

    repeated = PreflightScanner(config=config).scan(anomaly_video, _valid_package())
    assert [finding.code for finding in repeated.findings] == codes


def test_unified_report_does_not_duplicate_missing_stream_finding(
    video_without_audio: Path,
) -> None:
    report = PreflightScanner(config=_test_config()).scan(
        video_without_audio, _valid_package()
    )

    assert [
        finding.code
        for finding in report.findings
        if finding.code == "AUDIO_STREAM_MISSING"
    ] == ["AUDIO_STREAM_MISSING"]


def test_caption_findings_checks_summary_and_json_are_integrated(
    video_with_audio: Path, tmp_path: Path
) -> None:
    captions = tmp_path / "large-gap.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:00,100\nStart\n\n"
        "2\n00:00:00,900 --> 00:00:01,000\nEnd\n",
        encoding="utf-8",
    )
    config = _test_config()
    config.rules.captions.maximum_uncovered_gap_seconds = 0.5
    report = PreflightScanner(config=config).scan(
        video_with_audio, _valid_package(captions_path=captions)
    )

    assert report.verdict is FindingStatus.NEEDS_REVIEW
    assert "CAPTION_LARGE_GAP" in [finding.code for finding in report.findings]
    assert report.checks_run_count == 20
    assert report.passed_check_count == 19
    assert report.warning_count == 1
    assert report.caption_summary is not None
    assert report.caption_summary.cue_count == 2
    payload = json.loads(report.model_dump_json())
    assert payload["caption_summary"]["timeline_coverage_percent"] <= 100
    assert isinstance(payload["findings"][0]["timestamp_start_seconds"], float)
