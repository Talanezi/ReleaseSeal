from pathlib import Path

import pytest

from creator_preflight.config import DetectorConfig
from creator_preflight.detectors import (
    DetectorExecutionError,
    detect_black_segments,
    detect_freeze_segments,
    detect_long_silences,
    inspect_audio_peak,
)
from creator_preflight.engine import MediaAnomalyScanner
from creator_preflight.media import MediaInspector
from creator_preflight.models import Finding


def _finding(findings: list[Finding], code: str, near: float | None = None) -> Finding:
    matches = [finding for finding in findings if finding.code == code]
    if near is None:
        assert len(matches) == 1
        return matches[0]
    return min(
        matches,
        key=lambda finding: abs((finding.timestamp_start_seconds or 0) - near),
    )


def test_normal_short_video_has_no_anomaly_findings(video_with_audio: Path) -> None:
    result = MediaAnomalyScanner().scan(video_with_audio)

    assert result.findings == []


def test_black_segment_timestamp_and_duration(anomaly_video: Path) -> None:
    findings = detect_black_segments(
        anomaly_video, DetectorConfig().black
    )
    finding = _finding(findings, "VIDEO_BLACK_SEGMENT", near=2.0)

    assert finding.timestamp_start_seconds == pytest.approx(2.0, abs=0.15)
    assert finding.timestamp_end_seconds == pytest.approx(5.0, abs=0.15)
    assert finding.details is not None
    assert finding.details["duration_seconds"] == pytest.approx(3.0, abs=0.15)
    assert len(findings) == 1


def test_long_silence_timestamp_and_duration(anomaly_video: Path) -> None:
    media = MediaInspector().inspect(anomaly_video)
    findings = detect_long_silences(
        anomaly_video, media, DetectorConfig().silence
    )
    finding = _finding(findings, "AUDIO_LONG_SILENCE", near=3.0)

    assert finding.timestamp_start_seconds == pytest.approx(3.0, abs=0.15)
    assert finding.timestamp_end_seconds == pytest.approx(6.0, abs=0.15)
    assert finding.details is not None
    assert finding.details["duration_seconds"] == pytest.approx(3.0, abs=0.15)
    assert len(findings) == 1


def test_silence_reaching_end_has_complete_interval(
    silence_at_end_video: Path,
) -> None:
    media = MediaInspector().inspect(silence_at_end_video)
    findings = detect_long_silences(
        silence_at_end_video, media, DetectorConfig().silence
    )
    finding = _finding(findings, "AUDIO_LONG_SILENCE", near=2.0)

    assert finding.timestamp_start_seconds == pytest.approx(2.0, abs=0.15)
    assert finding.timestamp_end_seconds == pytest.approx(4.0, abs=0.15)


def test_freeze_segment_timestamp_and_duration(anomaly_video: Path) -> None:
    media = MediaInspector().inspect(anomaly_video)
    findings = detect_freeze_segments(
        anomaly_video, media, DetectorConfig().freeze
    )
    finding = _finding(findings, "VIDEO_FREEZE_SEGMENT", near=7.0)

    assert finding.timestamp_start_seconds == pytest.approx(7.0, abs=0.20)
    assert finding.timestamp_end_seconds == pytest.approx(10.0, abs=0.20)
    assert finding.details is not None
    assert finding.details["duration_seconds"] == pytest.approx(3.0, abs=0.20)
    assert len(findings) <= 2


def test_sustained_near_full_scale_audio_is_global_and_contains_density_evidence(
    anomaly_video: Path,
) -> None:
    media = MediaInspector().inspect(anomaly_video)
    findings = inspect_audio_peak(
        anomaly_video, media, DetectorConfig().audio_peak
    )
    finding = _finding(findings, "AUDIO_PEAK_WARNING")

    assert finding.timestamp_start_seconds is None
    assert finding.timestamp_end_seconds is None
    assert finding.details is not None
    assert finding.details["measurement_scope"] == "global"
    assert float(finding.details["measured_peak_dbfs"]) >= -1.0
    assert (
        float(finding.details["near_full_scale_sample_fraction"])
        >= DetectorConfig().audio_peak.minimum_near_full_scale_sample_fraction
    )
    assert int(finding.details["near_full_scale_sample_count"]) > 0
    assert int(finding.details["decoded_sample_count"]) > 0


def test_brief_near_full_scale_transient_does_not_warn(
    near_full_scale_transient_video: Path,
) -> None:
    media = MediaInspector().inspect(near_full_scale_transient_video)

    assert inspect_audio_peak(
        near_full_scale_transient_video, media, DetectorConfig().audio_peak
    ) == []


def test_legitimate_low_motion_video_is_not_reported_as_frozen(
    low_motion_video: Path,
) -> None:
    result = MediaAnomalyScanner().scan(low_motion_video)

    assert "VIDEO_FREEZE_SEGMENT" not in [finding.code for finding in result.findings]


def test_speech_style_pauses_over_ambient_audio_are_not_reported_as_silence(
    ambient_pause_video: Path,
) -> None:
    result = MediaAnomalyScanner().scan(ambient_pause_video)

    assert "AUDIO_LONG_SILENCE" not in [finding.code for finding in result.findings]


def test_short_black_edit_transition_is_below_interval_thresholds(
    short_black_transition_video: Path,
) -> None:
    result = MediaAnomalyScanner().scan(short_black_transition_video)

    assert "VIDEO_BLACK_SEGMENT" not in [finding.code for finding in result.findings]
    assert "VIDEO_FREEZE_SEGMENT" not in [finding.code for finding in result.findings]


def test_brief_black_flash_is_a_review_candidate(black_flash_video: Path) -> None:
    result = MediaAnomalyScanner().scan(black_flash_video)
    finding = _finding(result.findings, "VIDEO_SHORT_BLACK_FLASH", near=2.0)
    assert finding.timestamp_start_seconds == pytest.approx(2.0, abs=0.08)
    assert finding.timestamp_end_seconds == pytest.approx(2.12, abs=0.08)
    assert finding.status.value == "NEEDS_REVIEW"


def test_video_without_audio_returns_only_missing_audio_finding(
    video_without_audio: Path,
) -> None:
    result = MediaAnomalyScanner().scan(video_without_audio)

    assert [finding.code for finding in result.findings] == ["AUDIO_STREAM_MISSING"]
    assert result.findings[0].severity.value == "warning"


def test_audio_only_media_returns_missing_video_finding(audio_only_media: Path) -> None:
    result = MediaAnomalyScanner().scan(audio_only_media)

    assert [finding.code for finding in result.findings] == ["VIDEO_STREAM_MISSING"]
    assert result.findings[0].severity.value == "error"


def test_media_shorter_than_thresholds_has_no_interval_findings(
    video_with_audio: Path,
) -> None:
    config = DetectorConfig()
    config.black.min_duration_seconds = 10
    config.silence.min_duration_seconds = 10
    config.freeze.min_duration_seconds = 10

    result = MediaAnomalyScanner(config=config).scan(video_with_audio)

    assert result.findings == []


def test_detector_missing_tool_failure_is_structured(video_with_audio: Path) -> None:
    with pytest.raises(DetectorExecutionError) as captured:
        detect_black_segments(
            video_with_audio,
            DetectorConfig().black,
            ffmpeg_binary="creator-preflight-ffmpeg-does-not-exist",
        )

    assert captured.value.code == "media_tool_unavailable"
    assert captured.value.details == {
        "tool": "creator-preflight-ffmpeg-does-not-exist"
    }


def test_integrated_scan_findings_conform_to_schema(anomaly_video: Path) -> None:
    result = MediaAnomalyScanner().scan(anomaly_video)
    codes = [finding.code for finding in result.findings]

    assert "VIDEO_BLACK_SEGMENT" in codes
    assert "AUDIO_LONG_SILENCE" in codes
    assert "VIDEO_FREEZE_SEGMENT" in codes
    assert "AUDIO_PEAK_WARNING" in codes
    assert result.model_dump_json()
