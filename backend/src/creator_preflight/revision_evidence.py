"""Bounded evidence planning and FFmpeg rendering for semantic revision review."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from creator_preflight.config import RevisionSemanticReviewConfig
from creator_preflight.revision_check import insertion_previous_anchor
from creator_preflight.revision_check_models import RevisionCheckReport, RevisionRequest
from creator_preflight.revision_models import RevisionSegment, RevisionSegmentKind
from creator_preflight.revision_semantic_models import RevisionEvidenceRange


class RevisionEvidenceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PlannedRevisionEvidence:
    previous_range: RevisionEvidenceRange
    revised_range: RevisionEvidenceRange
    change_kinds: tuple[str, ...]
    partial: bool


@dataclass(frozen=True)
class RenderedRevisionEvidence:
    previous_path: Path
    revised_path: Path
    plan: PlannedRevisionEvidence
    render_seconds: float


def plan_revision_evidence(
    request: RevisionRequest,
    report: RevisionCheckReport,
    config: RevisionSemanticReviewConfig,
) -> PlannedRevisionEvidence:
    segments = {item.segment_id: item for item in report.revision_map.segments}
    matched = [segments[item] for item in request.matched_segment_ids if item in segments]
    if not matched:
        raise RevisionEvidenceError("revision_semantic_evidence_unavailable", "No mapped changed region is available for this request.")
    previous_cores: list[tuple[float, float]] = []
    revised_cores: list[tuple[float, float]] = []
    for segment in matched:
        if segment.previous_start_seconds is not None and segment.previous_end_seconds is not None:
            previous_cores.append((segment.previous_start_seconds, segment.previous_end_seconds))
        elif segment.kind is RevisionSegmentKind.INSERTED:
            anchor = insertion_previous_anchor(segment.segment_id, report.revision_map)
            if anchor is not None:
                previous_cores.append((anchor, anchor))
        if segment.revised_start_seconds is not None and segment.revised_end_seconds is not None:
            revised_cores.append((segment.revised_start_seconds, segment.revised_end_seconds))
        elif segment.kind is RevisionSegmentKind.REMOVED:
            anchor = _removed_revised_anchor(segment, report)
            if anchor is not None:
                revised_cores.append((anchor, anchor))
    if not previous_cores or not revised_cores:
        raise RevisionEvidenceError("revision_semantic_evidence_unavailable", "Corresponding Previous and Revised evidence could not be mapped safely.")
    previous, previous_partial = _bounded_range(previous_cores, report.revision_map.previous_duration_seconds, config)
    revised, revised_partial = _bounded_range(revised_cores, report.revision_map.revised_duration_seconds, config)
    return PlannedRevisionEvidence(
        previous_range=previous,
        revised_range=revised,
        change_kinds=tuple(dict.fromkeys(segment.kind.value for segment in matched)),
        partial=previous_partial or revised_partial,
    )


def render_revision_evidence(
    previous_path: str | Path,
    revised_path: str | Path,
    output_directory: str | Path,
    plan: PlannedRevisionEvidence,
    report: RevisionCheckReport,
    config: RevisionSemanticReviewConfig,
    *,
    ffmpeg_binary: str = "ffmpeg",
) -> RenderedRevisionEvidence:
    started = perf_counter()
    directory = Path(output_directory)
    previous_output = directory / "previous-evidence.mp4"
    revised_output = directory / "revised-evidence.mp4"
    _render_clip(previous_path, previous_output, plan.previous_range, report.revision_map.previous_streams.has_audio, config, ffmpeg_binary)
    _render_clip(revised_path, revised_output, plan.revised_range, report.revision_map.revised_streams.has_audio, config, ffmpeg_binary)
    return RenderedRevisionEvidence(previous_output, revised_output, plan, perf_counter() - started)


def _bounded_range(cores: list[tuple[float, float]], duration: float, config: RevisionSemanticReviewConfig) -> tuple[RevisionEvidenceRange, bool]:
    core_start = min(item[0] for item in cores)
    core_end = max(item[1] for item in cores)
    maximum = config.maximum_clip_duration_seconds
    partial = core_end - core_start > maximum
    if partial:
        center = (core_start + core_end) / 2
        start, end = center - maximum / 2, center + maximum / 2
    else:
        start = core_start - config.context_before_seconds
        end = core_end + config.context_after_seconds
        if end - start > maximum:
            excess = end - start - maximum
            start += excess / 2
            end -= excess / 2
    start = max(0.0, start)
    end = min(duration, end)
    if end - start > maximum:
        end = start + maximum
    if end - start < min(0.05, duration):
        start = max(0.0, min(core_start - 0.25, duration - 0.5))
        end = min(duration, start + 0.5)
    return RevisionEvidenceRange(start_seconds=start, end_seconds=end), partial


def _removed_revised_anchor(segment: RevisionSegment, report: RevisionCheckReport) -> float | None:
    items = report.revision_map.segments
    index = next((i for i, item in enumerate(items) if item.segment_id == segment.segment_id), None)
    if index is None:
        return None
    before = next((item.revised_end_seconds for item in reversed(items[:index]) if item.revised_end_seconds is not None), None)
    after = next((item.revised_start_seconds for item in items[index + 1:] if item.revised_start_seconds is not None), None)
    if before is not None and after is not None:
        return (before + after) / 2
    return before if before is not None else after


def _render_clip(source: str | Path, output: Path, interval: RevisionEvidenceRange, has_audio: bool, config: RevisionSemanticReviewConfig, ffmpeg_binary: str) -> None:
    duration = interval.end_seconds - interval.start_seconds
    args = [ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{interval.start_seconds:.6f}", "-i", str(source), "-t", f"{duration:.6f}", "-map", "0:v:0"]
    if has_audio:
        args += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "64k"]
    else:
        args += ["-an"]
    args += ["-vf", f"scale={config.clip_width}:{config.clip_height}:force_original_aspect_ratio=decrease,pad={config.clip_width}:{config.clip_height}:(ow-iw)/2:(oh-ih)/2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=config.clip_timeout_seconds, check=False)
    except FileNotFoundError as exc:
        raise RevisionEvidenceError("revision_semantic_media_tool_unavailable", "FFmpeg is unavailable for evidence rendering.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RevisionEvidenceError("revision_semantic_evidence_timeout", "Revision evidence rendering timed out.") from exc
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        raise RevisionEvidenceError("revision_semantic_evidence_render_failed", "A bounded revision evidence clip could not be rendered.")
