"""Bounded deterministic alignment of two finished media timelines."""

from __future__ import annotations

import hashlib
import math
import subprocess
from array import array
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic, perf_counter

from releaseseal.config import RevisionMapConfig
from releaseseal.media import MediaInspection, MediaInspectionError, MediaInspector, require_media_tool
from releaseseal.revision_models import (
    RevisionMap,
    RevisionSamplingPolicy,
    RevisionSegment,
    RevisionSegmentKind,
    RevisionStreamSummary,
)


class RevisionMapError(Exception):
    """Safe revision-analysis failure for application adapters."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AudioFingerprint:
    rms_db: float
    peak_db: float
    zero_crossing_rate: float


@dataclass(frozen=True)
class RevisionSample:
    timestamp_seconds: float
    perceptual_hash: int
    descriptor: bytes
    mean_luminance: float
    luminance_variance: float
    edge_energy: float
    low_information: bool = False
    audio: AudioFingerprint | None = None


@dataclass(frozen=True)
class AlignmentStep:
    previous_index: int | None
    revised_index: int | None


@dataclass(frozen=True)
class SampleDistance:
    visual: float
    audio: float | None
    combined: float


class RevisionMapper:
    """Create a deterministic monotonic RevisionMap from two local videos."""

    def __init__(
        self,
        config: RevisionMapConfig | None = None,
        *,
        inspector: MediaInspector | None = None,
        ffmpeg_binary: str = "ffmpeg",
    ) -> None:
        self.config = config or RevisionMapConfig()
        self.inspector = inspector or MediaInspector()
        self.ffmpeg_binary = ffmpeg_binary

    def map(self, previous_path: str | Path, revised_path: str | Path) -> RevisionMap:
        try:
            return self._map(previous_path, revised_path)
        except RevisionMapError:
            raise
        except Exception as exc:
            raise RevisionMapError(
                "revision_mapping_failed",
                "The revision timeline could not be mapped safely.",
            ) from exc

    def _map(self, previous_path: str | Path, revised_path: str | Path) -> RevisionMap:
        started = perf_counter()
        previous = Path(previous_path)
        revised = Path(revised_path)
        previous_hash = _sha256(previous, "revision_previous_unreadable")
        revised_hash = _sha256(revised, "revision_revised_unreadable")
        previous_media = self._inspect(previous, "previous")
        if previous_hash == revised_hash:
            streams = _stream_summary(previous_media)
            duration = _duration(previous_media, "previous")
            return RevisionMap(
                previous_sha256=previous_hash,
                revised_sha256=revised_hash,
                previous_duration_seconds=duration,
                revised_duration_seconds=duration,
                previous_streams=streams,
                revised_streams=streams,
                sampling_policy=self._policy_snapshot(self.config.visual_samples_per_second),
                previous_sample_count=0,
                revised_sample_count=0,
                estimated_unchanged_duration_seconds=duration,
                unchanged_ratio=1.0,
                segments=[RevisionSegment(
                    segment_id="segment-0001",
                    kind=RevisionSegmentKind.UNCHANGED,
                    previous_start_seconds=0,
                    previous_end_seconds=duration,
                    revised_start_seconds=0,
                    revised_end_seconds=duration,
                    visual_distance=0,
                    audio_distance=0 if previous_media.has_audio else None,
                    visual_changed=False,
                    audio_changed=False,
                    match_confidence=1,
                    boundary_confidence="high",
                )],
                analysis_runtime_seconds=perf_counter() - started,
                identical_file_fast_path=True,
            )
        revised_media = self._inspect(revised, "revised")
        previous_duration = _duration(previous_media, "previous")
        revised_duration = _duration(revised_media, "revised")
        effective_fps = effective_visual_sampling_rate(
            previous_duration,
            revised_duration,
            self.config,
        )
        previous_samples = self._extract_samples(previous, previous_media, previous_duration, effective_fps)
        revised_samples = self._extract_samples(revised, revised_media, revised_duration, effective_fps)
        steps = align_sample_sequences(
            previous_samples,
            revised_samples,
            self.config,
        )
        segments = _steps_to_segments(
            steps,
            previous_samples,
            revised_samples,
            previous_duration,
            revised_duration,
            effective_fps,
            self.config,
            previous_media.has_audio,
            revised_media.has_audio,
        )
        segments = self._refine_segments(
            previous,
            revised,
            segments,
            previous_duration,
            revised_duration,
        )
        unchanged_duration = sum(
            (segment.previous_end_seconds or 0) - (segment.previous_start_seconds or 0)
            for segment in segments
            if segment.kind is RevisionSegmentKind.UNCHANGED
        )
        ambiguity: list[str] = []
        if any(segment.boundary_confidence == "ambiguous" for segment in segments):
            ambiguity.append("Low-information, repeated, or weakly matched material reduced confidence for one or more regions.")
        if previous_media.has_audio != revised_media.has_audio:
            ambiguity.append("Only one version contains audio, so audio correspondence is unavailable across the pair.")
        return RevisionMap(
            previous_sha256=previous_hash,
            revised_sha256=revised_hash,
            previous_duration_seconds=previous_duration,
            revised_duration_seconds=revised_duration,
            previous_streams=_stream_summary(previous_media),
            revised_streams=_stream_summary(revised_media),
            sampling_policy=self._policy_snapshot(effective_fps),
            previous_sample_count=len(previous_samples),
            revised_sample_count=len(revised_samples),
            estimated_unchanged_duration_seconds=min(previous_duration, unchanged_duration),
            unchanged_ratio=min(1.0, max(0.0, unchanged_duration / previous_duration)),
            segments=segments,
            ambiguity_notes=ambiguity,
            analysis_runtime_seconds=perf_counter() - started,
        )

    def _inspect(self, path: Path, label: str) -> MediaInspection:
        try:
            media = self.inspector.inspect(path)
        except MediaInspectionError as exc:
            raise RevisionMapError(f"revision_{label}_unreadable", f"The {label} video could not be read.") from exc
        if not media.has_video:
            raise RevisionMapError(f"revision_{label}_video_missing", f"The {label} file does not contain a video stream.")
        _duration(media, label)
        return media

    def _extract_samples(
        self,
        path: Path,
        media: MediaInspection,
        duration: float,
        fps: float,
    ) -> list[RevisionSample]:
        visual = _extract_visual_samples(path, duration, fps, self.config, self.ffmpeg_binary)
        audio = (
            _extract_audio_samples(path, fps, len(visual), self.config, self.ffmpeg_binary)
            if media.has_audio
            else []
        )
        return [
            replace(sample, audio=audio[index] if index < len(audio) else None)
            for index, sample in enumerate(visual)
        ]

    def _policy_snapshot(self, fps: float) -> RevisionSamplingPolicy:
        return RevisionSamplingPolicy(
            visual_samples_per_second=fps,
            maximum_visual_samples=self.config.maximum_visual_samples,
            descriptor_width=self.config.descriptor_width,
            descriptor_height=self.config.descriptor_height,
            audio_sample_rate=self.config.audio_sample_rate,
            refinement_samples_per_second=self.config.refinement_samples_per_second,
            maximum_refinement_samples=self.config.maximum_refinement_samples,
        )

    def _refine_segments(
        self,
        previous_path: Path,
        revised_path: Path,
        segments: list[RevisionSegment],
        previous_duration: float,
        revised_duration: float,
    ) -> list[RevisionSegment]:
        """Refine candidate edit boundaries in small, bounded visual windows."""

        if self.config.refinement_radius_seconds <= 0:
            return segments
        refined = list(segments)
        remaining_samples = self.config.maximum_refinement_samples
        for index, segment in enumerate(list(refined)):
            if segment.kind is RevisionSegmentKind.UNCHANGED:
                continue
            previous_anchor = _segment_anchor(segment, refined, index, "previous")
            revised_anchor = _segment_anchor(segment, refined, index, "revised")
            previous_window = _refinement_window(
                segment.previous_start_seconds,
                segment.previous_end_seconds,
                previous_anchor,
                previous_duration,
                self.config.refinement_radius_seconds,
            )
            revised_window = _refinement_window(
                segment.revised_start_seconds,
                segment.revised_end_seconds,
                revised_anchor,
                revised_duration,
                self.config.refinement_radius_seconds,
            )
            estimated = math.ceil(
                ((previous_window[1] - previous_window[0]) + (revised_window[1] - revised_window[0]))
                * self.config.refinement_samples_per_second
            )
            if estimated <= 0 or estimated > remaining_samples:
                continue
            previous_samples = _extract_visual_samples(
                previous_path,
                previous_duration,
                self.config.refinement_samples_per_second,
                self.config,
                self.ffmpeg_binary,
                start_seconds=previous_window[0],
                end_seconds=previous_window[1],
                maximum_samples=remaining_samples,
            )
            revised_samples = _extract_visual_samples(
                revised_path,
                revised_duration,
                self.config.refinement_samples_per_second,
                self.config,
                self.ffmpeg_binary,
                start_seconds=revised_window[0],
                end_seconds=revised_window[1],
                maximum_samples=max(1, remaining_samples - len(previous_samples)),
            )
            remaining_samples -= len(previous_samples) + len(revised_samples)
            local_steps = align_sample_sequences(previous_samples, revised_samples, self.config)
            local_segments = _steps_to_segments(
                local_steps,
                previous_samples,
                revised_samples,
                previous_duration,
                revised_duration,
                self.config.refinement_samples_per_second,
                self.config,
                False,
                False,
            )
            candidate = _best_refinement_candidate(segment, local_segments)
            if candidate is None:
                continue
            refined[index] = segment.model_copy(
                update={
                    "previous_start_seconds": candidate.previous_start_seconds,
                    "previous_end_seconds": candidate.previous_end_seconds,
                    "revised_start_seconds": candidate.revised_start_seconds,
                    "revised_end_seconds": candidate.revised_end_seconds,
                    "boundary_confidence": "ambiguous"
                    if candidate.boundary_confidence == "ambiguous"
                    else "approximate",
                }
            )
            _join_adjacent_boundaries(refined, index)
            if remaining_samples <= 1:
                break
        for index, segment in enumerate(refined):
            if segment.kind is not RevisionSegmentKind.UNCHANGED:
                _join_adjacent_boundaries(refined, index)
        return [segment.model_copy(update={"segment_id": f"segment-{index:04d}"}) for index, segment in enumerate(refined, 1)]


def sample_distance(left: RevisionSample, right: RevisionSample, config: RevisionMapConfig) -> SampleDistance:
    bits = max(1, (config.descriptor_width - 1) * config.descriptor_height)
    hash_distance = (left.perceptual_hash ^ right.perceptual_hash).bit_count() / bits
    descriptor_count = max(1, min(len(left.descriptor), len(right.descriptor)))
    descriptor_distance = sum(abs(a - b) for a, b in zip(left.descriptor, right.descriptor)) / (255 * descriptor_count)
    mean_distance = abs(left.mean_luminance - right.mean_luminance) / 255
    variance_distance = min(1.0, abs(left.luminance_variance - right.luminance_variance) / 4000)
    edge_distance = abs(left.edge_energy - right.edge_energy) / 255
    visual = min(1.0, 0.45 * hash_distance + 0.35 * descriptor_distance + 0.08 * mean_distance + 0.06 * variance_distance + 0.06 * edge_distance)
    audio = _audio_distance(left.audio, right.audio)
    combined = visual if audio is None else visual * (1 - config.audio_weight) + audio * config.audio_weight
    return SampleDistance(visual=visual, audio=audio, combined=combined)


def effective_visual_sampling_rate(
    previous_duration_seconds: float,
    revised_duration_seconds: float,
    config: RevisionMapConfig | None = None,
) -> float:
    policy = config or RevisionMapConfig()
    duration = max(previous_duration_seconds, revised_duration_seconds)
    if not math.isfinite(duration) or duration <= 0:
        raise RevisionMapError("revision_duration_invalid", "Revision sampling requires usable media durations.")
    return max(0.01, min(policy.visual_samples_per_second, policy.maximum_visual_samples / duration))


def align_sample_sequences(
    previous: list[RevisionSample],
    revised: list[RevisionSample],
    config: RevisionMapConfig | None = None,
) -> list[AlignmentStep]:
    """Needleman-Wunsch alignment with rolling scores and compact backpointers."""

    policy = config or RevisionMapConfig()
    rows, columns = len(previous), len(revised)
    width = columns + 1
    directions = bytearray((rows + 1) * width)
    prior = array("f", (column * policy.gap_penalty for column in range(width)))
    for column in range(1, width):
        directions[column] = 2
    deadline = monotonic() + policy.alignment_timeout_seconds
    for row in range(1, rows + 1):
        if monotonic() > deadline:
            raise RevisionMapError("revision_alignment_timeout", "Revision timeline alignment exceeded its configured time limit.")
        current = array("f", [row * policy.gap_penalty] + [0.0] * columns)
        directions[row * width] = 1
        for column in range(1, width):
            distance = sample_distance(previous[row - 1], revised[column - 1], policy).combined
            diagonal = prior[column - 1] + min(distance, policy.maximum_substitution_cost)
            removed = prior[column] + policy.gap_penalty
            inserted = current[column - 1] + policy.gap_penalty
            if diagonal <= removed and diagonal <= inserted:
                current[column] = diagonal
                directions[row * width + column] = 0
            elif removed <= inserted:
                current[column] = removed
                directions[row * width + column] = 1
            else:
                current[column] = inserted
                directions[row * width + column] = 2
        prior = current
    steps: list[AlignmentStep] = []
    row, column = rows, columns
    while row or column:
        direction = directions[row * width + column]
        if row and column and direction == 0:
            row -= 1
            column -= 1
            steps.append(AlignmentStep(row, column))
        elif row and (not column or direction == 1):
            row -= 1
            steps.append(AlignmentStep(row, None))
        else:
            column -= 1
            steps.append(AlignmentStep(None, column))
    steps.reverse()
    return steps


def _extract_visual_samples(
    path: Path,
    duration: float,
    fps: float,
    config: RevisionMapConfig,
    ffmpeg_binary: str,
    *,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
    maximum_samples: int | None = None,
) -> list[RevisionSample]:
    executable = _require_ffmpeg(ffmpeg_binary)
    width, height = config.descriptor_width, config.descriptor_height
    command = [executable, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start_seconds > 0:
        command.extend(["-ss", f"{start_seconds:.6f}"])
    command.extend(["-i", str(path.resolve())])
    if end_seconds is not None:
        command.extend(["-t", f"{max(0.0, end_seconds - start_seconds):.6f}"])
    command.extend([
        "-map", "0:v:0", "-an", "-vf", f"fps={fps:.9f},scale={width}:{height}:flags=area,format=gray",
        "-frames:v", str(maximum_samples or config.maximum_visual_samples), "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ])
    completed = _run_extraction(command, config.extraction_timeout_seconds, "revision_visual_extraction_failed")
    frame_size = width * height
    frames = [completed.stdout[index:index + frame_size] for index in range(0, len(completed.stdout) - frame_size + 1, frame_size)]
    if not frames:
        raise RevisionMapError("revision_visual_extraction_failed", "No visual samples could be extracted from the media pair.")
    interval = 1 / fps
    return [_visual_sample(frame, min(start_seconds + index * interval, duration), width, height, config) for index, frame in enumerate(frames)]


def _segment_anchor(
    segment: RevisionSegment,
    segments: list[RevisionSegment],
    index: int,
    timeline: str,
) -> float:
    start = getattr(segment, f"{timeline}_start_seconds")
    end = getattr(segment, f"{timeline}_end_seconds")
    if start is not None and end is not None:
        return (start + end) / 2
    if index > 0:
        prior_end = getattr(segments[index - 1], f"{timeline}_end_seconds")
        if prior_end is not None:
            return prior_end
    if index + 1 < len(segments):
        following_start = getattr(segments[index + 1], f"{timeline}_start_seconds")
        if following_start is not None:
            return following_start
    return 0.0


def _refinement_window(
    start: float | None,
    end: float | None,
    anchor: float,
    duration: float,
    radius: float,
) -> tuple[float, float]:
    content_start = anchor if start is None else start
    content_end = anchor if end is None else end
    window_start = max(0.0, content_start - radius)
    window_end = min(duration, content_end + radius)
    if window_end <= window_start:
        window_end = min(duration, window_start + max(radius, 0.1))
    return window_start, window_end


def _best_refinement_candidate(
    coarse: RevisionSegment,
    candidates: list[RevisionSegment],
) -> RevisionSegment | None:
    same_kind = [candidate for candidate in candidates if candidate.kind is coarse.kind]
    if not same_kind:
        return None
    timeline = "revised" if coarse.kind is RevisionSegmentKind.INSERTED else "previous"
    coarse_start = getattr(coarse, f"{timeline}_start_seconds")
    coarse_end = getattr(coarse, f"{timeline}_end_seconds")
    assert coarse_start is not None and coarse_end is not None

    def score(candidate: RevisionSegment) -> tuple[float, float]:
        start = getattr(candidate, f"{timeline}_start_seconds")
        end = getattr(candidate, f"{timeline}_end_seconds")
        assert start is not None and end is not None
        overlap = max(0.0, min(coarse_end, end) - max(coarse_start, start))
        boundary_error = abs(start - coarse_start) + abs(end - coarse_end)
        return (overlap, -boundary_error)

    selected = max(same_kind, key=score)
    selected_start = getattr(selected, f"{timeline}_start_seconds")
    selected_end = getattr(selected, f"{timeline}_end_seconds")
    assert selected_start is not None and selected_end is not None
    if max(0.0, min(coarse_end, selected_end) - max(coarse_start, selected_start)) <= 0:
        return None
    return selected


def _join_adjacent_boundaries(segments: list[RevisionSegment], index: int) -> None:
    current = segments[index]
    if index > 0:
        prior = segments[index - 1]
        updates: dict[str, float] = {}
        if current.previous_start_seconds is not None and prior.previous_end_seconds is not None:
            updates["previous_end_seconds"] = current.previous_start_seconds
        if current.revised_start_seconds is not None and prior.revised_end_seconds is not None:
            updates["revised_end_seconds"] = current.revised_start_seconds
        if updates:
            segments[index - 1] = prior.model_copy(update=updates)
    if index + 1 < len(segments):
        following = segments[index + 1]
        updates = {}
        if current.previous_end_seconds is not None and following.previous_start_seconds is not None:
            updates["previous_start_seconds"] = current.previous_end_seconds
        if current.revised_end_seconds is not None and following.revised_start_seconds is not None:
            updates["revised_start_seconds"] = current.revised_end_seconds
        if updates:
            segments[index + 1] = following.model_copy(update=updates)
    if index > 0 and index + 1 < len(segments):
        prior = segments[index - 1]
        following = segments[index + 1]
        if current.kind is RevisionSegmentKind.REMOVED:
            if prior.revised_end_seconds is not None and following.revised_start_seconds is not None:
                segments[index + 1] = following.model_copy(
                    update={"revised_start_seconds": prior.revised_end_seconds}
                )
        elif current.kind is RevisionSegmentKind.INSERTED:
            if prior.previous_end_seconds is not None and following.previous_start_seconds is not None:
                segments[index + 1] = following.model_copy(
                    update={"previous_start_seconds": prior.previous_end_seconds}
                )


def _visual_sample(frame: bytes, timestamp: float, width: int, height: int, config: RevisionMapConfig) -> RevisionSample:
    mean = sum(frame) / len(frame)
    variance = sum((value - mean) ** 2 for value in frame) / len(frame)
    edge_differences = [frame[row * width + column] - frame[row * width + column + 1] for row in range(height) for column in range(width - 1)]
    edge = sum(abs(difference) for difference in edge_differences) / max(1, len(edge_differences))
    perceptual_hash = 0
    for difference in edge_differences:
        perceptual_hash = (perceptual_hash << 1) | int(difference > 0)
    low_information = variance < config.low_information_variance_threshold and edge < config.low_information_edge_threshold
    return RevisionSample(timestamp, perceptual_hash, frame, mean, variance, edge, low_information)


def _extract_audio_samples(
    path: Path,
    fps: float,
    maximum_samples: int,
    config: RevisionMapConfig,
    ffmpeg_binary: str,
) -> list[AudioFingerprint]:
    executable = _require_ffmpeg(ffmpeg_binary)
    samples_per_window = max(1, round(config.audio_sample_rate / fps))
    graph = (
        f"aresample={config.audio_sample_rate},asetnsamples=n={samples_per_window}:p=1,"
        "astats=metadata=1:reset=1,ametadata=print:file=-"
    )
    command = [
        executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path.resolve()),
        "-map", "0:a:0", "-vn", "-af", graph, "-frames:a", str(maximum_samples), "-f", "null", "-",
    ]
    completed = _run_extraction(command, config.extraction_timeout_seconds, "revision_audio_extraction_failed")
    frames: list[dict[str, float]] = []
    current: dict[str, float] | None = None
    for line in completed.stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith("frame:"):
            if current is not None:
                frames.append(current)
            current = {}
            continue
        if current is None or not line.startswith("lavfi.astats.Overall.") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        name = key.rsplit(".", 1)[-1]
        if name not in {"RMS_level", "Peak_level", "Zero_crossings_rate"}:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        current[name] = value if math.isfinite(value) else -120.0
    if current is not None:
        frames.append(current)
    return [
        AudioFingerprint(
            rms_db=frame.get("RMS_level", -120.0),
            peak_db=frame.get("Peak_level", -120.0),
            zero_crossing_rate=max(0.0, frame.get("Zero_crossings_rate", 0.0)),
        )
        for frame in frames[:maximum_samples]
    ]


def _run_extraction(command: list[str], timeout: float, error_code: str) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(command, capture_output=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RevisionMapError("revision_extraction_timeout", "Revision media sampling exceeded its configured time limit.") from exc
    except OSError as exc:
        raise RevisionMapError(error_code, "Revision media sampling could not start.") from exc
    if completed.returncode != 0:
        raise RevisionMapError(error_code, "Revision media samples could not be extracted.")
    return completed


def _require_ffmpeg(binary: str) -> str:
    try:
        return require_media_tool(binary)
    except MediaInspectionError as exc:
        raise RevisionMapError(
            "revision_media_tool_unavailable",
            "The local media tools required for revision analysis are unavailable.",
        ) from exc


def _audio_distance(left: AudioFingerprint | None, right: AudioFingerprint | None) -> float | None:
    if left is None and right is None:
        return None
    if left is None or right is None:
        return 1.0
    rms = min(1.0, abs(left.rms_db - right.rms_db) / 30)
    peak = min(1.0, abs(left.peak_db - right.peak_db) / 30)
    crossing = min(1.0, abs(left.zero_crossing_rate - right.zero_crossing_rate) / 0.20)
    return 0.45 * rms + 0.25 * peak + 0.30 * crossing


def _steps_to_segments(
    steps: list[AlignmentStep],
    previous: list[RevisionSample],
    revised: list[RevisionSample],
    previous_duration: float,
    revised_duration: float,
    fps: float,
    config: RevisionMapConfig,
    previous_has_audio: bool,
    revised_has_audio: bool,
) -> list[RevisionSegment]:
    interval = 1 / fps
    raw: list[dict[str, object]] = []
    for step in steps:
        if step.previous_index is None:
            sample = revised[step.revised_index]  # type: ignore[index]
            raw.append(_raw_segment(RevisionSegmentKind.INSERTED, None, None, sample.timestamp_seconds, min(revised_duration, sample.timestamp_seconds + interval), None, None, True, revised_has_audio, 0.5, sample.low_information))
        elif step.revised_index is None:
            sample = previous[step.previous_index]
            raw.append(_raw_segment(RevisionSegmentKind.REMOVED, sample.timestamp_seconds, min(previous_duration, sample.timestamp_seconds + interval), None, None, None, None, True, previous_has_audio, 0.5, sample.low_information))
        else:
            left, right = previous[step.previous_index], revised[step.revised_index]
            distance = sample_distance(left, right, config)
            visual_changed = distance.visual > config.visual_changed_threshold
            audio_changed = distance.audio is not None and distance.audio > config.audio_changed_threshold
            kind = RevisionSegmentKind.CHANGED if visual_changed or audio_changed else RevisionSegmentKind.UNCHANGED
            confidence = max(0.0, 1 - distance.combined - (config.low_information_penalty if left.low_information and right.low_information else 0))
            raw.append(_raw_segment(
                kind,
                left.timestamp_seconds,
                min(previous_duration, left.timestamp_seconds + interval),
                right.timestamp_seconds,
                min(revised_duration, right.timestamp_seconds + interval),
                distance.visual,
                distance.audio,
                visual_changed,
                audio_changed,
                confidence,
                left.low_information and right.low_information,
            ))
    merged: list[dict[str, object]] = []
    for item in raw:
        if merged and _can_merge(merged[-1], item, config.merge_tolerance_seconds):
            _merge_raw(merged[-1], item)
        else:
            merged.append(item)
    merged = _coalesce_balanced_gap_pairs(merged, previous, revised, config)
    merged = _absorb_tiny_changed_runs(merged, config.minimum_segment_duration_seconds)
    return [_to_segment(item, index, config) for index, item in enumerate(merged, start=1)]


def _raw_segment(kind, previous_start, previous_end, revised_start, revised_end, visual, audio, visual_changed, audio_changed, confidence, low_information):
    return {
        "kind": kind, "previous_start": previous_start, "previous_end": previous_end,
        "revised_start": revised_start, "revised_end": revised_end,
        "visual_sum": visual or 0.0, "visual_count": int(visual is not None),
        "audio_sum": audio or 0.0, "audio_count": int(audio is not None),
        "visual_changed": visual_changed, "audio_changed": audio_changed,
        "confidence_sum": confidence, "count": 1, "low_information": low_information,
    }


def _can_merge(left: dict[str, object], right: dict[str, object], tolerance: float) -> bool:
    if left["kind"] != right["kind"]:
        return False
    for end_key, start_key in (("previous_end", "previous_start"), ("revised_end", "revised_start")):
        end, start = left[end_key], right[start_key]
        if end is None and start is None:
            continue
        if end is None or start is None or abs(float(start) - float(end)) > tolerance:
            return False
    return True


def _merge_raw(target: dict[str, object], item: dict[str, object]) -> None:
    if item["previous_end"] is not None:
        target["previous_end"] = item["previous_end"]
    if item["revised_end"] is not None:
        target["revised_end"] = item["revised_end"]
    for key in ("visual_sum", "audio_sum", "confidence_sum"):
        target[key] = float(target[key]) + float(item[key])
    for key in ("visual_count", "audio_count", "count"):
        target[key] = int(target[key]) + int(item[key])
    target["visual_changed"] = bool(target["visual_changed"] or item["visual_changed"])
    target["audio_changed"] = bool(target["audio_changed"] or item["audio_changed"])
    target["low_information"] = bool(target["low_information"] or item["low_information"])


def _coalesce_balanced_gap_pairs(
    segments: list[dict[str, object]],
    previous_samples: list[RevisionSample],
    revised_samples: list[RevisionSample],
    config: RevisionMapConfig,
) -> list[dict[str, object]]:
    """Represent a same-length replacement as CHANGED, not delete plus insert."""

    output: list[dict[str, object]] = []
    index = 0
    while index < len(segments):
        if index + 1 >= len(segments):
            output.append(segments[index])
            break
        first, second = segments[index], segments[index + 1]
        kinds = {first["kind"], second["kind"]}
        if kinds != {RevisionSegmentKind.REMOVED, RevisionSegmentKind.INSERTED}:
            output.append(first)
            index += 1
            continue
        removed = first if first["kind"] is RevisionSegmentKind.REMOVED else second
        inserted = first if first["kind"] is RevisionSegmentKind.INSERTED else second
        removed_count = int(removed["count"])
        inserted_count = int(inserted["count"])
        removed_duration = float(removed["previous_end"]) - float(removed["previous_start"])
        inserted_duration = float(inserted["revised_end"]) - float(inserted["revised_start"])
        if abs(removed_count - inserted_count) > 1:
            if removed_count > inserted_count:
                output.append(
                    _raw_segment(
                        RevisionSegmentKind.REMOVED,
                        removed["previous_start"],
                        float(removed["previous_start"]) + max(0.001, removed_duration - inserted_duration),
                        None,
                        None,
                        None,
                        None,
                        True,
                        bool(removed["audio_changed"]),
                        0.5,
                        bool(removed["low_information"] or inserted["low_information"]),
                    )
                )
            else:
                output.append(
                    _raw_segment(
                        RevisionSegmentKind.INSERTED,
                        None,
                        None,
                        inserted["revised_start"],
                        float(inserted["revised_start"]) + max(0.001, inserted_duration - removed_duration),
                        None,
                        None,
                        True,
                        bool(inserted["audio_changed"]),
                        0.5,
                        bool(removed["low_information"] or inserted["low_information"]),
                    )
                )
            index += 2
            continue
        previous_window = _samples_in_bounds(
            previous_samples,
            float(removed["previous_start"]),
            float(removed["previous_end"]),
        )
        revised_window = _samples_in_bounds(
            revised_samples,
            float(inserted["revised_start"]),
            float(inserted["revised_end"]),
        )
        distances = [sample_distance(left, right, config) for left, right in zip(previous_window, revised_window)]
        if not distances:
            output.append(first)
            index += 1
            continue
        visual = sum(distance.visual for distance in distances) / len(distances)
        audio_values = [distance.audio for distance in distances if distance.audio is not None]
        audio = sum(audio_values) / len(audio_values) if audio_values else None
        combined = sum(distance.combined for distance in distances) / len(distances)
        visual_changed = visual > config.strong_match_threshold
        audio_changed = audio is not None and audio > config.audio_changed_threshold
        if not visual_changed and not audio_changed:
            visual_changed = True
        output.append(
            _raw_segment(
                RevisionSegmentKind.CHANGED,
                removed["previous_start"],
                removed["previous_end"],
                inserted["revised_start"],
                inserted["revised_end"],
                visual,
                audio,
                visual_changed,
                audio_changed,
                max(0.0, 1 - combined),
                bool(removed["low_information"] or inserted["low_information"]),
            )
        )
        index += 2
    return output


def _samples_in_bounds(samples: list[RevisionSample], start: float, end: float) -> list[RevisionSample]:
    return [sample for sample in samples if start <= sample.timestamp_seconds < end]


def _absorb_tiny_changed_runs(
    segments: list[dict[str, object]],
    minimum_duration_seconds: float,
) -> list[dict[str, object]]:
    if minimum_duration_seconds <= 0 or len(segments) < 3:
        return segments
    output = list(segments)
    index = 1
    while index + 1 < len(output):
        item = output[index]
        if (
            item["kind"] is RevisionSegmentKind.CHANGED
            and output[index - 1]["kind"] is RevisionSegmentKind.UNCHANGED
            and output[index + 1]["kind"] is RevisionSegmentKind.UNCHANGED
        ):
            duration = max(
                0.0,
                float(item["previous_end"]) - float(item["previous_start"]),
                float(item["revised_end"]) - float(item["revised_start"]),
            )
            if duration < minimum_duration_seconds:
                combined = output[index - 1]
                _merge_raw(combined, item)
                _merge_raw(combined, output[index + 1])
                combined["kind"] = RevisionSegmentKind.UNCHANGED
                combined["visual_changed"] = False
                combined["audio_changed"] = False
                output[index - 1:index + 2] = [combined]
                index = max(1, index - 1)
                continue
        index += 1
    return output


def _to_segment(item: dict[str, object], index: int, config: RevisionMapConfig) -> RevisionSegment:
    visual_count, audio_count, count = int(item["visual_count"]), int(item["audio_count"]), int(item["count"])
    confidence = float(item["confidence_sum"]) / count
    visual_distance = float(item["visual_sum"]) / visual_count if visual_count else None
    low_information = bool(item["low_information"])
    if low_information:
        boundary_confidence = "ambiguous"
    elif visual_distance is not None and visual_distance <= config.strong_match_threshold:
        boundary_confidence = "high"
    elif visual_distance is not None and visual_distance > config.plausible_match_threshold:
        boundary_confidence = "ambiguous"
    else:
        boundary_confidence = "approximate"
    return RevisionSegment(
        segment_id=f"segment-{index:04d}",
        kind=item["kind"],
        previous_start_seconds=item["previous_start"],
        previous_end_seconds=item["previous_end"],
        revised_start_seconds=item["revised_start"],
        revised_end_seconds=item["revised_end"],
        visual_distance=visual_distance,
        audio_distance=float(item["audio_sum"]) / audio_count if audio_count else None,
        visual_changed=bool(item["visual_changed"]),
        audio_changed=bool(item["audio_changed"]),
        match_confidence=max(0.0, min(1.0, confidence)),
        boundary_confidence=boundary_confidence,
    )


def _duration(media: MediaInspection, label: str) -> float:
    duration = media.duration_seconds
    if duration is None or not math.isfinite(duration) or duration <= 0:
        raise RevisionMapError(f"revision_{label}_duration_invalid", f"The {label} video does not have a usable duration.")
    return duration


def _stream_summary(media: MediaInspection) -> RevisionStreamSummary:
    if media.width is None or media.height is None:
        raise RevisionMapError("revision_video_dimensions_invalid", "Revision analysis requires usable video dimensions.")
    return RevisionStreamSummary(
        width=media.width,
        height=media.height,
        video_codec=media.video_codec,
        has_audio=media.has_audio,
        audio_codec=media.audio_codec,
    )


def _sha256(path: Path, error_code: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RevisionMapError(error_code, "A revision input file could not be read.") from exc
    return digest.hexdigest()
