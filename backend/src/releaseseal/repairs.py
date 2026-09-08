"""Deterministic repair planning and bounded FFmpeg rendering."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from releaseseal.media import MediaInspector, require_media_tool
from releaseseal.models import Finding, MediaInspection
from releaseseal.repair_models import (
    RepairOperation,
    RepairOperationType,
    RepairPlan,
    RepairProposal,
    Repairability,
)
from releaseseal.presentation import format_timecode_interval

MAXIMUM_REPAIRS_PER_RENDER = 10
MINIMUM_REMOVE_DURATION_SECONDS = 0.1
MINIMUM_OUTPUT_DURATION_SECONDS = 0.5
DURATION_TOLERANCE_SECONDS = 0.1
PREVIEW_CONTEXT_SECONDS = 4.0


class RepairError(Exception):
    """Safe repair failure for adapters to translate without raw FFmpeg output."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class RepairRenderResult:
    output_path: Path
    original_duration_seconds: float
    output_duration_seconds: float
    removed_duration_seconds: float


def build_repair_plan(findings: list[Finding]) -> RepairPlan:
    """Map trusted findings to the only repair operation supported in M17."""

    proposals = [_proposal_for_finding(finding, index) for index, finding in enumerate(findings)]
    return RepairPlan(
        proposals=proposals,
        safe_count=sum(item.repairability is Repairability.SAFE for item in proposals),
        preview_required_count=sum(
            item.repairability is Repairability.PREVIEW_REQUIRED for item in proposals
        ),
        human_only_count=sum(
            item.repairability is Repairability.HUMAN_ONLY for item in proposals
        ),
    )


def validate_repair_operations(
    operations: list[RepairOperation],
    media_duration_seconds: float | None,
) -> list[RepairOperation]:
    if not operations:
        raise RepairError("repair_operations_empty", "Select at least one approved repair.")
    if len(operations) > MAXIMUM_REPAIRS_PER_RENDER:
        raise RepairError(
            "repair_operations_too_many",
            f"A single render supports at most {MAXIMUM_REPAIRS_PER_RENDER} repairs.",
        )
    if media_duration_seconds is None or not math.isfinite(media_duration_seconds) or media_duration_seconds <= 0:
        raise RepairError(
            "repair_media_duration_invalid",
            "The source video does not have a usable duration for repair.",
        )
    ordered = sorted(operations, key=lambda item: (item.start_seconds, item.end_seconds))
    normalized: list[RepairOperation] = []
    for operation in ordered:
        if operation.operation_type is not RepairOperationType.REMOVE_RANGE:
            raise RepairError("repair_operation_unsupported", "This repair operation is not supported.")
        if operation.end_seconds > media_duration_seconds + DURATION_TOLERANCE_SECONDS:
            raise RepairError(
                "repair_range_out_of_bounds",
                "A repair range extends beyond the source video duration.",
            )
        end_seconds = min(operation.end_seconds, media_duration_seconds)
        if end_seconds - operation.start_seconds < MINIMUM_REMOVE_DURATION_SECONDS:
            raise RepairError(
                "repair_range_too_short",
                f"A removed range must be at least {MINIMUM_REMOVE_DURATION_SECONDS:.1f} seconds.",
            )
        normalized.append(
            RepairOperation(
                operation_type=RepairOperationType.REMOVE_RANGE,
                start_seconds=operation.start_seconds,
                end_seconds=end_seconds,
            )
        )
    for previous, current in zip(normalized, normalized[1:]):
        if current.start_seconds < previous.end_seconds:
            raise RepairError(
                "repair_ranges_overlap",
                "Approved repair ranges must not overlap.",
            )
    removed_duration = sum(item.end_seconds - item.start_seconds for item in normalized)
    if media_duration_seconds - removed_duration < MINIMUM_OUTPUT_DURATION_SECONDS:
        raise RepairError(
            "repair_would_remove_entire_video",
            "The approved repairs would not leave a usable video.",
        )
    return normalized


class FFmpegRepairEngine:
    """Render allowlisted timeline removals to a new H.264/AAC MP4."""

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        timeout_seconds: float = 600,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self.timeout_seconds = timeout_seconds

    def render(
        self,
        source_path: str | Path,
        output_path: str | Path,
        operations: list[RepairOperation],
        *,
        media: MediaInspection | None = None,
    ) -> RepairRenderResult:
        source = Path(source_path).resolve()
        output = Path(output_path).resolve()
        if source == output:
            raise RepairError(
                "repair_source_overwrite_forbidden",
                "ReleaseSeal will not overwrite the original video.",
            )
        inspection = media or MediaInspector(
            ffprobe_binary=self.ffprobe_binary
        ).inspect(source)
        if not inspection.has_video:
            raise RepairError("repair_video_stream_missing", "The source has no video stream to repair.")
        validated = validate_repair_operations(operations, inspection.duration_seconds)
        duration = inspection.duration_seconds
        assert duration is not None
        kept = _kept_intervals(0.0, duration, validated)
        self._render_intervals(source, output, kept, inspection)
        output_media = MediaInspector(ffprobe_binary=self.ffprobe_binary).inspect(output)
        if not output_media.has_video or output_media.duration_seconds is None:
            raise RepairError("repair_output_invalid", "The repaired output could not be validated.")
        return RepairRenderResult(
            output_path=output,
            original_duration_seconds=duration,
            output_duration_seconds=output_media.duration_seconds,
            removed_duration_seconds=sum(item.end_seconds - item.start_seconds for item in validated),
        )

    def render_preview(
        self,
        source_path: str | Path,
        output_path: str | Path,
        operation: RepairOperation,
        *,
        media: MediaInspection | None = None,
        context_seconds: float = PREVIEW_CONTEXT_SECONDS,
    ) -> RepairRenderResult:
        inspection = media or MediaInspector(
            ffprobe_binary=self.ffprobe_binary
        ).inspect(source_path)
        validated = validate_repair_operations([operation], inspection.duration_seconds)
        duration = inspection.duration_seconds
        assert duration is not None
        selected = validated[0]
        context_start = max(0.0, selected.start_seconds - context_seconds)
        context_end = min(duration, selected.end_seconds + context_seconds)
        kept = _kept_intervals(context_start, context_end, validated)
        source = Path(source_path).resolve()
        output = Path(output_path).resolve()
        if source == output:
            raise RepairError(
                "repair_source_overwrite_forbidden",
                "ReleaseSeal will not overwrite the original video.",
            )
        self._render_intervals(source, output, kept, inspection)
        output_media = MediaInspector(ffprobe_binary=self.ffprobe_binary).inspect(output)
        if not output_media.has_video or output_media.duration_seconds is None:
            raise RepairError("repair_output_invalid", "The repair preview could not be validated.")
        return RepairRenderResult(
            output_path=output,
            original_duration_seconds=context_end - context_start,
            output_duration_seconds=output_media.duration_seconds,
            removed_duration_seconds=selected.end_seconds - selected.start_seconds,
        )

    def render_segments(
        self,
        source_path: str | Path,
        output_path: str | Path,
        intervals: list[tuple[float, float]],
        *,
        media: MediaInspection | None = None,
    ) -> RepairRenderResult:
        """Concatenate backend-generated source intervals into a bounded review reel."""

        inspection = media or MediaInspector(ffprobe_binary=self.ffprobe_binary).inspect(source_path)
        duration = inspection.duration_seconds
        if not inspection.has_video or duration is None:
            raise RepairError("repair_video_stream_missing", "The source has no usable video stream.")
        if not intervals or len(intervals) > 12:
            raise RepairError("review_reel_intervals_invalid", "The review reel intervals are invalid.")
        normalized: list[tuple[float, float]] = []
        for start, end in intervals:
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or end > duration + DURATION_TOLERANCE_SECONDS:
                raise RepairError("review_reel_intervals_invalid", "A review reel interval is outside the repaired video.")
            normalized.append((start, min(end, duration)))
        source = Path(source_path).resolve()
        output = Path(output_path).resolve()
        if source == output:
            raise RepairError("repair_source_overwrite_forbidden", "ReleaseSeal will not overwrite the repaired video.")
        self._render_intervals(source, output, normalized, inspection)
        output_media = MediaInspector(ffprobe_binary=self.ffprobe_binary).inspect(output)
        if not output_media.has_video or output_media.duration_seconds is None:
            raise RepairError("repair_output_invalid", "The review reel could not be validated.")
        return RepairRenderResult(
            output_path=output,
            original_duration_seconds=duration,
            output_duration_seconds=output_media.duration_seconds,
            removed_duration_seconds=max(0.0, duration - sum(end - start for start, end in normalized)),
        )

    def _render_intervals(
        self,
        source: Path,
        output: Path,
        kept_intervals: list[tuple[float, float]],
        media: MediaInspection,
    ) -> None:
        executable = require_media_tool(self.ffmpeg_binary)
        output.parent.mkdir(parents=True, exist_ok=True)
        filter_parts: list[str] = []
        concat_inputs: list[str] = []
        for index, (start, end) in enumerate(kept_intervals):
            filter_parts.append(
                f"[0:v:0]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{index}]"
            )
            concat_inputs.append(f"[v{index}]")
            if media.has_audio:
                filter_parts.append(
                    f"[0:a:0]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{index}]"
                )
                concat_inputs.append(f"[a{index}]")
        filter_parts.append(
            "".join(concat_inputs)
            + f"concat=n={len(kept_intervals)}:v=1:a={1 if media.has_audio else 0}[outv]"
            + ("[outa]" if media.has_audio else "")
        )
        command = [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(source),
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[outv]",
        ]
        if media.has_audio:
            command.extend(["-map", "[outa]"])
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
            ]
        )
        if media.has_audio:
            command.extend(["-c:a", "aac", "-b:a", "192k"])
        command.extend(["-movflags", "+faststart", "-map_metadata", "-1", str(output)])
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RepairError("repair_render_timeout", "The repair render timed out.") from exc
        except OSError as exc:
            raise RepairError("repair_render_unavailable", "FFmpeg could not start the repair render.") from exc
        if completed.returncode != 0:
            code = (
                "repair_encoder_unavailable"
                if "unknown encoder" in completed.stderr.lower()
                else "repair_render_failed"
            )
            message = (
                "The required H.264 encoder is unavailable in this FFmpeg installation."
                if code == "repair_encoder_unavailable"
                else "FFmpeg could not render the proposed repair."
            )
            raise RepairError(code, message, details={"ffmpeg_exit_code": completed.returncode})


def _proposal_for_finding(finding: Finding, index: int) -> RepairProposal:
    title = _finding_title(finding)
    evidence = finding.details
    start = finding.timestamp_start_seconds
    end = finding.timestamp_end_seconds
    original_start = _number(evidence, "original_start_seconds")
    original_end = _number(evidence, "original_end_seconds")
    proposal_id = _proposal_id(finding, index)
    if (
        finding.code == "AI_ACCIDENTAL_REPETITION"
        and start is not None
        and end is not None
        and end > start
        and original_start is not None
        and original_end is not None
        and original_end > original_start
        and (original_end <= start or original_start >= end)
    ):
        return RepairProposal(
            proposal_id=proposal_id,
            finding_code=finding.code,
            finding_title=title,
            explanation=(
                f"Remove the repeated occurrence at {format_timecode_interval(start, end)}; "
                "the original reference interval remains in the video."
            ),
            source=finding.source,
            repairability=Repairability.SAFE,
            operation=RepairOperation(
                operation_type=RepairOperationType.REMOVE_RANGE,
                start_seconds=start,
                end_seconds=end,
            ),
            start_seconds=start,
            end_seconds=end,
            expected_duration_change_seconds=-(end - start),
            original_start_seconds=original_start,
            original_end_seconds=original_end,
            evidence=evidence,
        )
    if finding.code == "VIDEO_BLACK_SEGMENT" and start is not None and end is not None and end > start:
        return RepairProposal(
            proposal_id=proposal_id,
            finding_code=finding.code,
            finding_title=title,
            explanation=(
                f"Remove the black interval at {format_timecode_interval(start, end)} and ripple "
                "the remaining video and audio together. Preview this pacing change first."
            ),
            source=finding.source,
            repairability=Repairability.PREVIEW_REQUIRED,
            operation=RepairOperation(
                operation_type=RepairOperationType.REMOVE_RANGE,
                start_seconds=start,
                end_seconds=end,
            ),
            start_seconds=start,
            end_seconds=end,
            expected_duration_change_seconds=-(end - start),
            evidence=evidence,
        )
    return RepairProposal(
        proposal_id=proposal_id,
        finding_code=finding.code,
        finding_title=title,
        explanation=(
            "ReleaseSeal can show this evidence, but cannot make a trustworthy edit "
            "without your judgment."
        ),
        source=finding.source,
        repairability=Repairability.HUMAN_ONLY,
        start_seconds=start,
        end_seconds=end,
        evidence=evidence,
    )


def _kept_intervals(
    window_start: float,
    window_end: float,
    operations: list[RepairOperation],
) -> list[tuple[float, float]]:
    kept: list[tuple[float, float]] = []
    cursor = window_start
    for operation in operations:
        if operation.end_seconds <= window_start or operation.start_seconds >= window_end:
            continue
        remove_start = max(window_start, operation.start_seconds)
        remove_end = min(window_end, operation.end_seconds)
        if remove_start > cursor:
            kept.append((cursor, remove_start))
        cursor = max(cursor, remove_end)
    if cursor < window_end:
        kept.append((cursor, window_end))
    if not kept:
        raise RepairError("repair_would_remove_entire_video", "The repair would leave no previewable video.")
    return kept


def _proposal_id(finding: Finding, index: int) -> str:
    payload = json.dumps(
        {
            "index": index,
            "code": finding.code,
            "start": finding.timestamp_start_seconds,
            "end": finding.timestamp_end_seconds,
            "message": finding.message,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"repair-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _finding_title(finding: Finding) -> str:
    if finding.details and isinstance(finding.details.get("title"), str):
        return str(finding.details["title"])
    return finding.code.replace("_", " ").title()


def _number(details: dict[str, Any] | None, key: str) -> float | None:
    if not details:
        return None
    value = details.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None
