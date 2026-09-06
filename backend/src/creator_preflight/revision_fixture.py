"""Portable deterministic media pairs for Revision Map engineering validation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from creator_preflight.media import MediaInspector, require_media_tool


def generate_revision_source(
    output_path: str | Path,
    *,
    duration_seconds: float = 60.0,
    size: str = "320x180",
    frame_rate: int = 12,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 120.0,
) -> Path:
    """Generate moving, temporally varying picture and audio without network/TTS."""

    output = Path(output_path)
    command = [
        require_media_tool(ffmpeg_binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i",
        (
            f"testsrc2=size={size}:rate={frame_rate}:duration={duration_seconds},"
            "eq=brightness='0.22*sin(0.173*t)+0.08*sin(0.071*t)':eval=frame"
        ),
        "-f", "lavfi", "-i",
        f"aevalsrc=0.18*sin(2*PI*(180+2*t)*t):s=16000:d={duration_seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-shortest", str(output),
    ]
    _run(command, timeout_seconds)
    return output


def reencode_revision(
    source_path: str | Path,
    output_path: str | Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 120.0,
) -> Path:
    output = Path(output_path)
    command = [
        require_media_tool(ffmpeg_binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(Path(source_path)), "-c:v", "libx264", "-preset", "medium", "-crf", "28",
        "-c:a", "aac", "-b:a", "64k", str(output),
    ]
    _run(command, timeout_seconds)
    return output


def insert_revision_section(
    source_path: str | Path,
    output_path: str | Path,
    *,
    at_seconds: float,
    insert_duration_seconds: float,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 120.0,
) -> Path:
    source = Path(source_path)
    output = Path(output_path)
    media = MediaInspector().inspect(source)
    if media.duration_seconds is None or media.width is None or media.height is None or not media.has_audio:
        raise RuntimeError("Revision insertion fixture requires readable audiovisual media.")
    filter_graph = ";".join(
        [
            f"[0:v]trim=start=0:end={at_seconds},setpts=PTS-STARTPTS[v0]",
            f"[0:a]atrim=start=0:end={at_seconds},asetpts=PTS-STARTPTS[a0]",
            f"[1:v]setpts=PTS-STARTPTS[vi]",
            f"[2:a]asetpts=PTS-STARTPTS[ai]",
            f"[0:v]trim=start={at_seconds}:end={media.duration_seconds},setpts=PTS-STARTPTS[v1]",
            f"[0:a]atrim=start={at_seconds}:end={media.duration_seconds},asetpts=PTS-STARTPTS[a1]",
            "[v0][a0][vi][ai][v1][a1]concat=n=3:v=1:a=1[outv][outa]",
        ]
    )
    command = [
        require_media_tool(ffmpeg_binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(source),
        "-f", "lavfi", "-t", str(insert_duration_seconds), "-i",
        f"mandelbrot=size={media.width}x{media.height}:rate=12:maxiter=100",
        "-f", "lavfi", "-i", f"sine=frequency=1370:sample_rate=16000:duration={insert_duration_seconds}",
        "-filter_complex", filter_graph, "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", str(output),
    ]
    _run(command, timeout_seconds)
    return output


def replace_revision_picture(
    source_path: str | Path,
    output_path: str | Path,
    *,
    start_seconds: float,
    end_seconds: float,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 120.0,
) -> Path:
    output = Path(output_path)
    command = [
        require_media_tool(ffmpeg_binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(Path(source_path)), "-vf",
        f"negate=enable='between(t,{start_seconds},{end_seconds})'",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy", str(output),
    ]
    _run(command, timeout_seconds)
    return output


def replace_revision_audio(
    source_path: str | Path,
    output_path: str | Path,
    *,
    start_seconds: float,
    end_seconds: float,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 120.0,
) -> Path:
    output = Path(output_path)
    command = [
        require_media_tool(ffmpeg_binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(Path(source_path)), "-af",
        f"volume=0:enable='between(t,{start_seconds},{end_seconds})'",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", str(output),
    ]
    _run(command, timeout_seconds)
    return output


def _run(command: list[str], timeout_seconds: float) -> None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Portable revision fixture generation could not complete.") from exc
    if completed.returncode != 0:
        raise RuntimeError("Portable revision fixture generation could not complete.")
