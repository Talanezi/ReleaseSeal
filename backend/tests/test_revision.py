from __future__ import annotations

from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from creator_preflight import revision
from creator_preflight.config import RevisionMapConfig
from creator_preflight.revision import (
    AlignmentStep,
    RevisionMapError,
    RevisionMapper,
    RevisionSample,
    _steps_to_segments,
    align_sample_sequences,
    effective_visual_sampling_rate,
)
from creator_preflight.revision_models import RevisionSegment, RevisionSegmentKind
from creator_preflight.repair_models import RepairOperation
from creator_preflight.repairs import FFmpegRepairEngine
from creator_preflight.revision_fixture import (
    generate_revision_source,
    insert_revision_section,
    reencode_revision,
    replace_revision_audio,
    replace_revision_picture,
)


def _sample(value: int, index: int, *, low_information: bool = False) -> RevisionSample:
    descriptor = bytes(((value * 37 + position * 17) % 256) for position in range(17 * 9))
    perceptual_hash = int.from_bytes(descriptor[:18], "big") & ((1 << 144) - 1)
    return RevisionSample(
        timestamp_seconds=index * 0.5,
        perceptual_hash=perceptual_hash,
        descriptor=descriptor,
        mean_luminance=sum(descriptor) / len(descriptor),
        luminance_variance=500,
        edge_energy=20,
        low_information=low_information,
    )


def _samples(values: list[int], *, low_indices: set[int] | None = None) -> list[RevisionSample]:
    low_indices = low_indices or set()
    return [_sample(value, index, low_information=index in low_indices) for index, value in enumerate(values)]


def _pairs(steps: list[AlignmentStep]) -> list[tuple[int | None, int | None]]:
    return [(step.previous_index, step.revised_index) for step in steps]


@pytest.mark.parametrize(
    ("previous", "revised", "expected"),
    [
        ([1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]),
        ([1, 2, 3, 4, 5], [1, 2, 4, 5], [(0, 0), (1, 1), (2, None), (3, 2), (4, 3)]),
        ([1, 2, 3, 4, 5], [1, 2, 9, 3, 4, 5], [(0, 0), (1, 1), (None, 2), (2, 3), (3, 4), (4, 5)]),
        ([1, 2, 3, 4, 5, 6, 7, 8], [1, 4, 5, 6, 7, 8], [(0, 0), (1, None), (2, None), (3, 1), (4, 2), (5, 3), (6, 4), (7, 5)]),
    ],
)
def test_alignment_primitive_handles_core_monotonic_edits(previous, revised, expected) -> None:
    assert _pairs(align_sample_sequences(_samples(previous), _samples(revised))) == expected


def test_alignment_multiple_edits_does_not_cascade() -> None:
    previous = _samples([1, 2, 3, 4, 5, 6, 7, 8])
    revised = _samples([1, 2, 9, 4, 6, 10, 8])
    steps = align_sample_sequences(previous, revised)
    pairs = _pairs(steps)
    assert pairs[:2] == [(0, 0), (1, 1)]
    assert (4, None) in pairs
    assert pairs[-1] == (7, 6)
    assert [pair for pair in pairs if pair[0] == 7] == [(7, 6)]


def test_alignment_repeated_and_low_information_material_is_stable() -> None:
    previous = _samples([1, 1, 2, 3, 1, 4], low_indices={0, 1, 4})
    revised = _samples([1, 1, 2, 9, 3, 1, 4], low_indices={0, 1, 5})
    first = _pairs(align_sample_sequences(previous, revised))
    second = _pairs(align_sample_sequences(previous, revised))
    assert first == second
    assert all(
        earlier[0] is None or later[0] is None or earlier[0] <= later[0]
        for earlier, later in zip(first, first[1:])
    )
    assert all(
        earlier[1] is None or later[1] is None or earlier[1] <= later[1]
        for earlier, later in zip(first, first[1:])
    )


def test_coarse_steps_form_typed_removed_inserted_and_changed_segments() -> None:
    previous = _samples([1, 2, 3, 4])
    revised = _samples([1, 9, 4, 8])
    steps = [AlignmentStep(0, 0), AlignmentStep(1, None), AlignmentStep(2, 1), AlignmentStep(3, 2), AlignmentStep(None, 3)]
    segments = _steps_to_segments(steps, previous, revised, 2, 2, 2, RevisionMapConfig(), False, False)
    assert [segment.kind for segment in segments] == [
        RevisionSegmentKind.UNCHANGED,
        RevisionSegmentKind.REMOVED,
        RevisionSegmentKind.CHANGED,
        RevisionSegmentKind.UNCHANGED,
        RevisionSegmentKind.INSERTED,
    ]


def test_revision_segment_rejects_invalid_timeline_shape() -> None:
    with pytest.raises(ValidationError):
        RevisionSegment(
            segment_id="segment-0001",
            kind=RevisionSegmentKind.REMOVED,
            previous_start_seconds=1,
            previous_end_seconds=2,
            revised_start_seconds=1,
            revised_end_seconds=2,
            visual_changed=True,
            audio_changed=False,
            match_confidence=0.8,
            boundary_confidence="approximate",
        )


def test_revision_threshold_order_is_validated() -> None:
    with pytest.raises(ValidationError, match="strong match threshold"):
        RevisionMapConfig(strong_match_threshold=0.4, plausible_match_threshold=0.2)


def test_unreadable_revision_input_has_safe_typed_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp4"
    with pytest.raises(RevisionMapError) as raised:
        RevisionMapper().map(missing, missing)
    assert raised.value.code == "revision_previous_unreadable"
    assert str(missing) not in raised.value.message


@pytest.fixture(scope="module")
def revision_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate_revision_source(tmp_path_factory.mktemp("revision-map") / "source.mp4")


def _segments(revision_map, kind: RevisionSegmentKind) -> list[RevisionSegment]:
    return [segment for segment in revision_map.segments if segment.kind is kind]


def _duration_on(segment: RevisionSegment, timeline: str) -> float:
    start = getattr(segment, f"{timeline}_start_seconds")
    end = getattr(segment, f"{timeline}_end_seconds")
    assert start is not None and end is not None
    return end - start


def test_identical_file_uses_hash_fast_path(revision_source: Path) -> None:
    result = RevisionMapper().map(revision_source, revision_source)
    assert result.identical_file_fast_path is True
    assert result.unchanged_ratio == 1
    assert [segment.kind for segment in result.segments] == [RevisionSegmentKind.UNCHANGED]
    assert result.previous_sample_count == result.revised_sample_count == 0


def test_normal_h264_reencode_is_overwhelmingly_unchanged(revision_source: Path, tmp_path: Path) -> None:
    revised = reencode_revision(revision_source, tmp_path / "reencoded.mp4")
    result = RevisionMapper().map(revision_source, revised)
    assert result.unchanged_ratio >= 0.98
    assert not _segments(result, RevisionSegmentKind.REMOVED)
    assert not _segments(result, RevisionSegmentKind.INSERTED)
    assert sum(_duration_on(item, "previous") for item in _segments(result, RevisionSegmentKind.CHANGED)) <= 0.5


def test_single_removal_is_located_and_downstream_realigns(revision_source: Path, tmp_path: Path) -> None:
    revised = tmp_path / "removed.mp4"
    operation = RepairOperation(operation_type="REMOVE_RANGE", start_seconds=20.25, end_seconds=29.25)
    FFmpegRepairEngine().render(revision_source, revised, [operation])
    result = RevisionMapper().map(revision_source, revised)
    removed = _segments(result, RevisionSegmentKind.REMOVED)
    assert len(removed) == 1
    assert removed[0].previous_start_seconds == pytest.approx(20.25, abs=0.5)
    assert removed[0].previous_end_seconds == pytest.approx(29.25, abs=0.5)
    assert result.segments[-1].kind is RevisionSegmentKind.UNCHANGED
    assert result.segments[-1].previous_end_seconds == pytest.approx(60, abs=0.2)
    assert result.segments[-1].revised_end_seconds == pytest.approx(51, abs=0.25)


def test_candidate_edit_boundaries_are_refined_locally(revision_source: Path, tmp_path: Path) -> None:
    revised = tmp_path / "removed.mp4"
    operation = RepairOperation(operation_type="REMOVE_RANGE", start_seconds=20.25, end_seconds=29.25)
    FFmpegRepairEngine().render(revision_source, revised, [operation])
    coarse = RevisionMapper(RevisionMapConfig(refinement_radius_seconds=0)).map(revision_source, revised)
    refined = RevisionMapper().map(revision_source, revised)
    coarse_removed = _segments(coarse, RevisionSegmentKind.REMOVED)[0]
    refined_removed = _segments(refined, RevisionSegmentKind.REMOVED)[0]
    coarse_error = abs(coarse_removed.previous_start_seconds - 20.25) + abs(coarse_removed.previous_end_seconds - 29.25)
    refined_error = abs(refined_removed.previous_start_seconds - 20.25) + abs(refined_removed.previous_end_seconds - 29.25)
    assert refined_error < coarse_error
    assert refined_error <= 0.25
    assert refined.sampling_policy.refinement_samples_per_second == 6


def test_single_insertion_is_located_and_downstream_realigns(revision_source: Path, tmp_path: Path) -> None:
    revised = insert_revision_section(
        revision_source, tmp_path / "inserted.mp4", at_seconds=20.25, insert_duration_seconds=6
    )
    result = RevisionMapper().map(revision_source, revised)
    inserted = _segments(result, RevisionSegmentKind.INSERTED)
    assert len(inserted) == 1
    assert inserted[0].revised_start_seconds == pytest.approx(20.25, abs=0.5)
    assert inserted[0].revised_end_seconds == pytest.approx(26.25, abs=0.5)
    assert result.segments[-1].kind is RevisionSegmentKind.UNCHANGED
    assert result.segments[-1].previous_end_seconds == pytest.approx(60, abs=0.2)
    assert result.segments[-1].revised_end_seconds == pytest.approx(66, abs=0.25)


def test_same_duration_visual_replacement_is_changed_visual_only(revision_source: Path, tmp_path: Path) -> None:
    revised = replace_revision_picture(
        revision_source, tmp_path / "visual-change.mp4", start_seconds=20, end_seconds=25
    )
    result = RevisionMapper().map(revision_source, revised)
    changed = _segments(result, RevisionSegmentKind.CHANGED)
    assert len(changed) == 1
    assert changed[0].previous_start_seconds == pytest.approx(20, abs=0.5)
    assert changed[0].previous_end_seconds == pytest.approx(25, abs=0.5)
    assert changed[0].visual_changed is True
    assert changed[0].audio_changed is False


def test_audio_only_replacement_is_changed_audio_only(revision_source: Path, tmp_path: Path) -> None:
    revised = replace_revision_audio(
        revision_source, tmp_path / "audio-change.mp4", start_seconds=20, end_seconds=25
    )
    result = RevisionMapper().map(revision_source, revised)
    changed = _segments(result, RevisionSegmentKind.CHANGED)
    assert len(changed) == 1
    assert changed[0].previous_start_seconds == pytest.approx(20, abs=0.6)
    assert changed[0].previous_end_seconds == pytest.approx(25, abs=0.6)
    assert changed[0].visual_changed is False
    assert changed[0].audio_changed is True


def test_early_removal_does_not_cascade_through_remaining_timeline(revision_source: Path, tmp_path: Path) -> None:
    revised = tmp_path / "early-cut.mp4"
    operation = RepairOperation(operation_type="REMOVE_RANGE", start_seconds=4, end_seconds=14)
    FFmpegRepairEngine().render(revision_source, revised, [operation])
    result = RevisionMapper().map(revision_source, revised)
    removed = _segments(result, RevisionSegmentKind.REMOVED)
    assert len(removed) == 1
    assert removed[0].previous_start_seconds == pytest.approx(4, abs=0.5)
    assert removed[0].previous_end_seconds == pytest.approx(14, abs=0.5)
    assert result.segments[-1].kind is RevisionSegmentKind.UNCHANGED
    assert _duration_on(result.segments[-1], "previous") >= 45.5


def test_multiple_edits_remain_separate_and_preserve_intervening_matches(revision_source: Path, tmp_path: Path) -> None:
    removed = tmp_path / "multi-removed.mp4"
    inserted = tmp_path / "multi-inserted.mp4"
    revised = tmp_path / "multi-final.mp4"
    FFmpegRepairEngine().render(
        revision_source,
        removed,
        [RepairOperation(operation_type="REMOVE_RANGE", start_seconds=10, end_seconds=15)],
    )
    insert_revision_section(removed, inserted, at_seconds=25, insert_duration_seconds=4)
    replace_revision_picture(inserted, revised, start_seconds=40, end_seconds=45)

    result = RevisionMapper().map(revision_source, revised)
    removals = _segments(result, RevisionSegmentKind.REMOVED)
    insertions = _segments(result, RevisionSegmentKind.INSERTED)
    changes = _segments(result, RevisionSegmentKind.CHANGED)
    assert len(removals) == len(insertions) == len(changes) == 1
    assert removals[0].previous_start_seconds == pytest.approx(10, abs=0.6)
    assert removals[0].previous_end_seconds == pytest.approx(15, abs=0.6)
    assert insertions[0].revised_start_seconds == pytest.approx(25, abs=0.6)
    assert insertions[0].revised_end_seconds == pytest.approx(29, abs=0.6)
    assert changes[0].revised_start_seconds == pytest.approx(40, abs=0.6)
    assert changes[0].revised_end_seconds == pytest.approx(45, abs=0.6)
    assert changes[0].visual_changed is True
    assert changes[0].audio_changed is False
    assert sum(segment.kind is RevisionSegmentKind.UNCHANGED for segment in result.segments) >= 3


def test_video_only_pair_is_supported(video_without_audio: Path, tmp_path: Path) -> None:
    revised = reencode_revision(video_without_audio, tmp_path / "video-only-reencoded.mp4")
    result = RevisionMapper().map(video_without_audio, revised)
    assert result.previous_streams.has_audio is False
    assert result.revised_streams.has_audio is False
    assert result.unchanged_ratio >= 0.9


def test_missing_video_stream_is_a_typed_safe_error(tmp_path: Path) -> None:
    audio_only = tmp_path / "audio-only.m4a"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=2", "-c:a", "aac", str(audio_only),
        ],
        check=True,
        timeout=30,
    )
    with pytest.raises(RevisionMapError) as raised:
        RevisionMapper().map(audio_only, audio_only)
    assert raised.value.code == "revision_previous_video_missing"
    assert "video stream" in raised.value.message


def test_missing_ffmpeg_is_normalized_to_revision_error(revision_source: Path, tmp_path: Path) -> None:
    revised = reencode_revision(revision_source, tmp_path / "copy.mp4")
    with pytest.raises(RevisionMapError) as raised:
        RevisionMapper(ffmpeg_binary="definitely-not-ffmpeg").map(revision_source, revised)
    assert raised.value.code == "revision_media_tool_unavailable"


def test_alignment_timeout_is_typed_and_safe(monkeypatch) -> None:
    clock = iter((0.0, 2.0))
    monkeypatch.setattr(revision, "monotonic", lambda: next(clock))
    with pytest.raises(RevisionMapError) as raised:
        align_sample_sequences(
            _samples([1, 2, 3]),
            _samples([1, 2, 3]),
            RevisionMapConfig(alignment_timeout_seconds=1),
        )
    assert raised.value.code == "revision_alignment_timeout"


def test_extraction_timeout_is_typed_and_safe(monkeypatch) -> None:
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ffmpeg", 1)

    monkeypatch.setattr(revision.subprocess, "run", timeout)
    with pytest.raises(RevisionMapError) as raised:
        revision._run_extraction(["ffmpeg"], 1, "revision_visual_extraction_failed")
    assert raised.value.code == "revision_extraction_timeout"


def test_unexpected_internal_failure_is_normalized(revision_source: Path, tmp_path: Path, monkeypatch) -> None:
    revised = reencode_revision(revision_source, tmp_path / "copy.mp4")
    monkeypatch.setattr(RevisionMapper, "_inspect", lambda *_args: (_ for _ in ()).throw(ValueError("private detail")))
    with pytest.raises(RevisionMapError) as raised:
        RevisionMapper().map(revision_source, revised)
    assert raised.value.code == "revision_mapping_failed"
    assert "private detail" not in raised.value.message


def test_low_information_media_is_marked_ambiguous_without_false_edit(tmp_path: Path) -> None:
    source = tmp_path / "static.mp4"
    revised = tmp_path / "static-reencoded.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x303030:size=320x180:rate=12:duration=12",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=12",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
        ],
        check=True,
        timeout=30,
    )
    reencode_revision(source, revised)
    result = RevisionMapper().map(source, revised)
    assert result.unchanged_ratio == pytest.approx(1)
    assert result.ambiguity_notes == [
        "Low-information, repeated, or weakly matched material reduced confidence for one or more regions."
    ]


def test_three_minute_pair_respects_sample_cap_and_completes(tmp_path: Path) -> None:
    source = generate_revision_source(tmp_path / "long-source.mp4", duration_seconds=180)
    revised = reencode_revision(source, tmp_path / "long-reencoded.mp4")
    result = RevisionMapper().map(source, revised)
    assert result.previous_sample_count <= 360
    assert result.revised_sample_count <= 361
    assert result.sampling_policy.visual_samples_per_second == pytest.approx(2)
    assert result.unchanged_ratio >= 0.98
    assert result.analysis_runtime_seconds < 90


def test_long_duration_sampling_policy_respects_hard_cap_without_decoding() -> None:
    config = RevisionMapConfig(visual_samples_per_second=2, maximum_visual_samples=1200)
    fps = effective_visual_sampling_rate(7200, 7190, config)
    assert fps == pytest.approx(1 / 6)
    assert fps * 7200 == pytest.approx(1200)


def test_same_pair_and_policy_produces_deterministic_map(revision_source: Path, tmp_path: Path) -> None:
    revised = tmp_path / "removed.mp4"
    FFmpegRepairEngine().render(
        revision_source,
        revised,
        [RepairOperation(operation_type="REMOVE_RANGE", start_seconds=20, end_seconds=30)],
    )
    first = RevisionMapper().map(revision_source, revised).model_dump(exclude={"analysis_runtime_seconds"})
    second = RevisionMapper().map(revision_source, revised).model_dump(exclude={"analysis_runtime_seconds"})
    assert first == second


def test_existing_preflight_remove_range_output_maps_to_source(anomaly_video: Path, tmp_path: Path) -> None:
    repaired = tmp_path / "preflight-repaired.mp4"
    FFmpegRepairEngine().render(
        anomaly_video,
        repaired,
        [RepairOperation(operation_type="REMOVE_RANGE", start_seconds=2, end_seconds=5)],
    )
    result = RevisionMapper().map(anomaly_video, repaired)
    removed = _segments(result, RevisionSegmentKind.REMOVED)
    assert len(removed) == 1
    assert removed[0].previous_start_seconds == pytest.approx(2, abs=0.6)
    assert removed[0].previous_end_seconds == pytest.approx(5, abs=0.6)
    assert result.segments[-1].previous_start_seconds == pytest.approx(5, abs=0.6)
    assert result.segments[-1].revised_start_seconds == pytest.approx(2, abs=0.6)
    unrelated_changed = sum(
        _duration_on(segment, "previous") for segment in _segments(result, RevisionSegmentKind.CHANGED)
    )
    assert unrelated_changed <= 0.5
    assert result.unchanged_ratio >= 0.70
