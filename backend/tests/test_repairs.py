import hashlib
from pathlib import Path

import pytest

from creator_preflight.media import MediaInspector
from creator_preflight.models import Finding, FindingSeverity, FindingStatus
from creator_preflight.repair_models import RepairOperation, RepairOperationType, Repairability
from creator_preflight.repairs import (
    FFmpegRepairEngine,
    RepairError,
    build_repair_plan,
    validate_repair_operations,
)


def _finding(code: str, start: float | None, end: float | None, details=None) -> Finding:
    return Finding(
        code=code,
        severity=FindingSeverity.WARNING,
        status=FindingStatus.NEEDS_REVIEW,
        message="Review this evidence.",
        source="test.source",
        timestamp_start_seconds=start,
        timestamp_end_seconds=end,
        details=details or {"title": "Test finding"},
    )


def _remove(start: float, end: float) -> RepairOperation:
    return RepairOperation(
        operation_type=RepairOperationType.REMOVE_RANGE,
        start_seconds=start,
        end_seconds=end,
    )


def test_accidental_repetition_maps_to_safe_repeated_occurrence_removal() -> None:
    plan = build_repair_plan([
        _finding(
            "AI_ACCIDENTAL_REPETITION",
            36,
            48,
            {
                "title": "Possible duplicated segment",
                "original_start_seconds": 24,
                "original_end_seconds": 36,
                "evidence": ["The later sequence repeats the earlier sequence."],
            },
        )
    ])

    proposal = plan.proposals[0]
    assert proposal.repairability is Repairability.SAFE
    assert proposal.operation == _remove(36, 48)
    assert proposal.original_start_seconds == 24
    assert proposal.original_end_seconds == 36
    assert proposal.expected_duration_change_seconds == -12


def test_black_segment_maps_to_preview_required_and_other_findings_are_human_only() -> None:
    plan = build_repair_plan([
        _finding("VIDEO_BLACK_SEGMENT", 12, 15.1),
        _finding("AUDIO_LONG_SILENCE", 20, 24),
        _finding("AI_CLAIM_POSSIBLE_CONFLICT", 30, None),
    ])

    assert plan.preview_required_count == 1
    assert plan.human_only_count == 2
    assert plan.proposals[0].repairability is Repairability.PREVIEW_REQUIRED
    assert plan.proposals[0].operation == _remove(12, 15.1)
    assert all(item.operation is None for item in plan.proposals[1:])


def test_unsafe_repetition_reference_degrades_to_human_only() -> None:
    plan = build_repair_plan([
        _finding(
            "AI_ACCIDENTAL_REPETITION",
            36,
            48,
            {
                "title": "Possible duplicated segment",
                "original_start_seconds": 35,
                "original_end_seconds": 40,
            },
        )
    ])
    assert plan.proposals[0].repairability is Repairability.HUMAN_ONLY
    assert plan.proposals[0].operation is None


@pytest.mark.parametrize(
    ("operations", "code"),
    [
        ([_remove(1, 1.05)], "repair_range_too_short"),
        ([_remove(1, 11)], "repair_range_out_of_bounds"),
        ([_remove(0, 9.6)], "repair_would_remove_entire_video"),
        ([_remove(1, 3), _remove(2, 4)], "repair_ranges_overlap"),
    ],
)
def test_invalid_repair_operations_are_rejected(operations, code: str) -> None:
    with pytest.raises(RepairError) as error:
        validate_repair_operations(operations, 10)
    assert error.value.code == code


def test_valid_operations_are_sorted_in_original_timeline_order() -> None:
    assert validate_repair_operations([_remove(7, 8), _remove(2, 3)], 12) == [
        _remove(2, 3),
        _remove(7, 8),
    ]


def test_ffmpeg_render_removes_multiple_ranges_and_preserves_video_audio(
    api_anomaly_video: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "repaired.mp4"
    source_digest = hashlib.sha256(api_anomaly_video.read_bytes()).hexdigest()
    result = FFmpegRepairEngine().render(
        api_anomaly_video,
        output,
        [_remove(7, 8), _remove(2, 5)],
    )
    inspection = MediaInspector().inspect(output)

    assert api_anomaly_video.exists()
    assert hashlib.sha256(api_anomaly_video.read_bytes()).hexdigest() == source_digest
    assert result.original_duration_seconds == pytest.approx(12, abs=0.2)
    assert result.removed_duration_seconds == pytest.approx(4, abs=0.01)
    assert result.output_duration_seconds == pytest.approx(8, abs=0.3)
    assert inspection.has_video is True
    assert inspection.has_audio is True
    assert inspection.video_codec == "h264"
    assert inspection.audio_codec == "aac"


def test_ffmpeg_preview_is_short_playable_mp4(
    api_anomaly_video: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "preview.mp4"
    result = FFmpegRepairEngine().render_preview(
        api_anomaly_video,
        output,
        _remove(2, 5),
    )
    inspection = MediaInspector().inspect(output)

    assert 5.5 <= result.output_duration_seconds <= 6.5
    assert inspection.has_video is True
    assert inspection.has_audio is True


def test_ffmpeg_repair_handles_video_without_audio(
    video_without_audio: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "video-only-repaired.mp4"
    result = FFmpegRepairEngine().render(
        video_without_audio,
        output,
        [_remove(0.2, 0.4)],
    )
    inspection = MediaInspector().inspect(output)
    assert result.output_duration_seconds == pytest.approx(0.8, abs=0.2)
    assert inspection.has_video is True
    assert inspection.has_audio is False
