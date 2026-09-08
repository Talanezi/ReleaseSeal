from __future__ import annotations

import json

import pytest

from releaseseal.config import RevisionCheckConfig
from releaseseal.revision_check import (
    RevisionCheckError,
    RevisionCheckService,
    insertion_previous_anchor,
    parse_revision_notes,
)
from releaseseal.revision_check_models import RevisionRequestStatus
from releaseseal.revision_models import (
    RevisionMap,
    RevisionSamplingPolicy,
    RevisionSegment,
    RevisionSegmentKind,
    RevisionStreamSummary,
)
from releaseseal.repair_models import RepairOperation
from releaseseal.repairs import FFmpegRepairEngine
from releaseseal.revision_fixture import (
    generate_revision_source,
    insert_revision_section,
    replace_revision_picture,
)


def _segment(
    number: int,
    kind: RevisionSegmentKind,
    previous: tuple[float, float] | None,
    revised: tuple[float, float] | None,
    *,
    visual: bool = False,
    audio: bool = False,
) -> RevisionSegment:
    return RevisionSegment(
        segment_id=f"segment-{number:04d}",
        kind=kind,
        previous_start_seconds=previous[0] if previous else None,
        previous_end_seconds=previous[1] if previous else None,
        revised_start_seconds=revised[0] if revised else None,
        revised_end_seconds=revised[1] if revised else None,
        visual_distance=0.4 if visual else 0.01,
        audio_distance=0.4 if audio else 0.01,
        visual_changed=visual,
        audio_changed=audio,
        match_confidence=0.9,
        boundary_confidence="approximate" if kind is not RevisionSegmentKind.UNCHANGED else "high",
    )


def _revision_map() -> RevisionMap:
    streams = RevisionStreamSummary(width=320, height=180, video_codec="h264", has_audio=True, audio_codec="aac")
    return RevisionMap(
        previous_sha256="a" * 64,
        revised_sha256="b" * 64,
        previous_duration_seconds=60,
        revised_duration_seconds=59,
        previous_streams=streams,
        revised_streams=streams,
        sampling_policy=RevisionSamplingPolicy(
            visual_samples_per_second=2,
            maximum_visual_samples=1200,
            descriptor_width=17,
            descriptor_height=9,
            audio_sample_rate=8000,
            refinement_samples_per_second=6,
            maximum_refinement_samples=240,
        ),
        previous_sample_count=120,
        revised_sample_count=118,
        estimated_unchanged_duration_seconds=50,
        unchanged_ratio=5 / 6,
        segments=[
            _segment(1, RevisionSegmentKind.UNCHANGED, (0, 10), (0, 10)),
            _segment(2, RevisionSegmentKind.REMOVED, (10, 15), None, visual=True, audio=True),
            _segment(3, RevisionSegmentKind.UNCHANGED, (15, 30), (10, 25)),
            _segment(4, RevisionSegmentKind.INSERTED, None, (25, 29), visual=True, audio=True),
            _segment(5, RevisionSegmentKind.UNCHANGED, (30, 41), (29, 40)),
            _segment(6, RevisionSegmentKind.CHANGED, (41, 46), (40, 45), visual=True),
            _segment(7, RevisionSegmentKind.UNCHANGED, (46, 60), (45, 59)),
        ],
        analysis_runtime_seconds=0.75,
    )


def test_note_parser_accepts_points_ranges_dashes_decimals_and_hours() -> None:
    notes = "\n".join(
        [
            "00:34 Remove the old logo",
            "01:12.25 Lower the music",
            "00:34-00:39 Remove this section",
            "00:34–00:39 Replace this section",
            "00:34—00:39 Shorten this section",
            "1:02:14 Replace the end card",
            "Replace the outdated statistic",
        ]
    )
    parsed = parse_revision_notes(notes, 4000)
    assert [(item.start_seconds, item.end_seconds, item.explicit_range) for item in parsed] == [
        (34, 34, False),
        (72.25, 72.25, False),
        (34, 39, True),
        (34, 39, True),
        (34, 39, True),
        (3734, 3734, False),
        (None, None, False),
    ]


@pytest.mark.parametrize(
    "line",
    [
        "00:99 Bad seconds",
        "1:60:00 Bad minutes",
        "-00:10 Negative",
        "NaN Impossible",
        "00:20-00:10 Reversed",
        "02:00 Outside duration",
    ],
)
def test_malformed_or_impossible_timecodes_are_rejected_safely(line: str) -> None:
    with pytest.raises(RevisionCheckError):
        parse_revision_notes(line, 60)


def test_point_uses_configured_neighborhood_and_range_uses_small_tolerance() -> None:
    service = RevisionCheckService(config=RevisionCheckConfig(point_neighborhood_seconds=3, explicit_range_tolerance_seconds=0.25))
    point = service.from_map(_revision_map(), "00:08 Inspect the cut")
    explicit = service.from_map(_revision_map(), "00:06-00:08 Inspect the cut")
    assert point.revision_requests[0].status is RevisionRequestStatus.CHANGE_DETECTED
    assert explicit.revision_requests[0].status is RevisionRequestStatus.NO_CHANGE_DETECTED


def test_notes_match_removed_changed_and_insertion_anchor() -> None:
    report = RevisionCheckService().from_map(
        _revision_map(),
        "00:12 Remove section\n00:30 Add insert\n00:43 Replace graphic",
    )
    assert [request.status for request in report.revision_requests] == [
        RevisionRequestStatus.CHANGE_DETECTED,
        RevisionRequestStatus.CHANGE_DETECTED,
        RevisionRequestStatus.CHANGE_DETECTED,
    ]
    assert report.revision_requests[0].matched_segment_ids == ["segment-0002"]
    assert report.revision_requests[1].matched_segment_ids == ["segment-0004"]
    assert report.revision_requests[2].matched_segment_ids == ["segment-0006"]
    assert insertion_previous_anchor("segment-0004", report.revision_map) == 30
    assert report.additional_change_count == 0


def test_no_change_untimed_and_additional_change_semantics() -> None:
    report = RevisionCheckService().from_map(
        _revision_map(),
        "00:04 Adjust opening\nReplace the outdated statistic\n00:12 Remove section",
    )
    assert report.revision_requests[0].status is RevisionRequestStatus.NO_CHANGE_DETECTED
    assert report.revision_requests[1].status is RevisionRequestStatus.NEEDS_LOCATION
    assert report.revision_requests[1].previous_start_seconds is None
    assert [item.segment_id for item in report.additional_changes] == ["segment-0004", "segment-0006"]
    assert report.additional_change_count == 2


def test_one_segment_can_account_for_multiple_overlapping_notes_without_becoming_additional() -> None:
    report = RevisionCheckService().from_map(
        _revision_map(),
        "00:42 Replace the number\n00:44 Correct the graphic",
    )
    assert all(request.matched_segment_ids == ["segment-0006"] for request in report.revision_requests)
    assert "segment-0006" not in [item.segment_id for item in report.additional_changes]


def test_no_notes_produces_pure_media_diff_and_identical_map_is_clean() -> None:
    changed = RevisionCheckService().from_map(_revision_map())
    assert changed.revision_requests == []
    assert changed.additional_change_count == 3

    source = _revision_map()
    identical = source.model_copy(
        update={
            "revised_sha256": source.previous_sha256,
            "revised_duration_seconds": 60,
            "estimated_unchanged_duration_seconds": 60,
            "unchanged_ratio": 1,
            "segments": [_segment(1, RevisionSegmentKind.UNCHANGED, (0, 60), (0, 60))],
            "identical_file_fast_path": True,
        }
    )
    report = RevisionCheckService().from_map(identical)
    assert report.additional_change_count == 0
    assert report.requested_change_count == 0


def test_matching_and_serialization_are_stable() -> None:
    service = RevisionCheckService()
    first = service.from_map(_revision_map(), "00:30 Insert card\n00:12 Remove old shot")
    second = service.from_map(_revision_map(), "00:30 Insert card\n00:12 Remove old shot")
    assert json.loads(first.model_dump_json()) == json.loads(second.model_dump_json())


def test_real_multi_edit_pair_supports_notes_and_pure_media_diff(tmp_path) -> None:
    source = generate_revision_source(tmp_path / "source.mp4")
    removed = tmp_path / "removed.mp4"
    inserted = tmp_path / "inserted.mp4"
    revised = tmp_path / "revised.mp4"
    FFmpegRepairEngine().render(
        source,
        removed,
        [RepairOperation(operation_type="REMOVE_RANGE", start_seconds=10, end_seconds=15)],
    )
    insert_revision_section(removed, inserted, at_seconds=25, insert_duration_seconds=4)
    replace_revision_picture(inserted, revised, start_seconds=40, end_seconds=45)

    service = RevisionCheckService()
    report = service.check(
        source,
        revised,
        "00:12 Remove old section\n00:30 Add card\n00:43 Replace graphic\n00:04 Adjust opening\nReplace statistic",
    )
    assert report.requested_changes_detected_count == 3
    assert report.requested_changes_not_detected_count == 1
    assert report.requests_needing_location_count == 1
    assert report.additional_change_count == 0

    no_notes = service.from_map(report.revision_map)
    assert no_notes.revision_requests == []
    assert no_notes.additional_change_count == 3

    partially_noted = service.from_map(report.revision_map, "00:12 Remove old section")
    assert partially_noted.additional_change_count == 2
