"""Bounded audiovisual proxy generation for fast publishing-metadata assistance."""

from __future__ import annotations

import subprocess
from pathlib import Path

from creator_preflight.config import MetadataAssistConfig
from creator_preflight.media import MediaInspection, MediaInspectionError, require_media_tool


def build_content_sketch(
    source_path: str | Path,
    output_path: str | Path,
    media: MediaInspection,
    config: MetadataAssistConfig,
    *,
    ffmpeg_binary: str = "ffmpeg",
) -> Path:
    """Create a short, low-resolution montage spread across the source timeline."""

    if not media.has_video or media.duration_seconds is None or media.duration_seconds <= 0:
        raise MediaInspectionError("metadata_sketch_unavailable", "A readable video stream is required for suggestions.")
    source = Path(source_path).resolve()
    output = Path(output_path).resolve()
    windows = sketch_windows(
        media.duration_seconds,
        sample_count=config.visual_sample_count,
        segment_seconds=config.visual_sample_seconds,
    )
    command = [require_media_tool(ffmpeg_binary), "-hide_banner", "-loglevel", "error", "-y"]
    for start, duration in windows:
        command.extend(["-ss", f"{start:.6f}", "-t", f"{duration:.6f}", "-i", str(source)])

    filters: list[str] = []
    concat_inputs: list[str] = []
    for index in range(len(windows)):
        filters.append(
            f"[{index}:v:0]scale={config.proxy_width}:{config.proxy_height}:"
            "force_original_aspect_ratio=decrease,pad="
            f"{config.proxy_width}:{config.proxy_height}:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1,setpts=PTS-STARTPTS"
            f"[v{index}]"
        )
        concat_inputs.append(f"[v{index}]")
        if media.has_audio:
            filters.append(
                f"[{index}:a:0]aresample=16000,aformat=sample_fmts=fltp:"
                "channel_layouts=mono,asetpts=PTS-STARTPTS"
                f"[a{index}]"
            )
            concat_inputs.append(f"[a{index}]")
    filters.append(
        "".join(concat_inputs)
        + f"concat=n={len(windows)}:v=1:a={1 if media.has_audio else 0}"
        + ("[video][audio]" if media.has_audio else "[video]")
    )
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[video]",
    ])
    if media.has_audio:
        command.extend(["-map", "[audio]", "-c:a", "aac", "-b:a", "48k"])
    command.extend([
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ])
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=config.proxy_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaInspectionError("metadata_sketch_timeout", "The fast content sketch took too long to create.") from exc
    except OSError as exc:
        raise MediaInspectionError("metadata_sketch_failed", "The fast content sketch could not be created.") from exc
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        raise MediaInspectionError("metadata_sketch_failed", "The fast content sketch could not be created.")
    return output


def sketch_windows(duration_seconds: float, *, sample_count: int, segment_seconds: float) -> list[tuple[float, float]]:
    """Return deterministic, timeline-spanning windows bounded by source duration."""

    if duration_seconds <= segment_seconds * sample_count:
        return [(0.0, duration_seconds)]
    maximum_start = duration_seconds - segment_seconds
    return [
        (maximum_start * index / (sample_count - 1), segment_seconds)
        for index in range(sample_count)
    ]
