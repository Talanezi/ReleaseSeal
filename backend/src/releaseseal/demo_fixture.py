"""Deterministic, copyright-free media generation for tests and demos."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def generate_demo_video(
    output_path: str | Path,
    *,
    size: str = "1280x720",
    ffmpeg_binary: str | None = None,
    timeout_seconds: float = 60.0,
) -> Path:
    """Generate the 12-second anomaly fixture used by tests and the demo."""

    executable = ffmpeg_binary or shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("FFmpeg is required to generate the demo fixture.")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    filter_graph = ";".join(
        [
            f"testsrc2=size={size}:rate=24:duration=2[v0]",
            f"color=c=black:size={size}:rate=24:duration=3[v1]",
            f"testsrc2=size={size}:rate=24:duration=2[v2]",
            f"color=c=blue:size={size}:rate=24:duration=3[v3]",
            f"testsrc2=size={size}:rate=24:duration=2[v4]",
            "[v0][v1][v2][v3][v4]concat=n=5:v=1:a=0,format=yuv420p[video]",
            "sine=frequency=440:sample_rate=48000:duration=3[a0]",
            "anullsrc=r=48000:cl=mono,atrim=duration=3[a1]",
            "sine=frequency=660:sample_rate=48000:duration=4[a2]",
            "aevalsrc=clip(4*sin(2*PI*880*t)\\,-1\\,1):s=48000:d=1[a3]",
            "sine=frequency=550:sample_rate=48000:duration=1[a4]",
            "[a0][a1][a2][a3][a4]concat=n=5:v=0:a=1[audio]",
        ]
    )
    command = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-filter_complex",
        filter_graph,
        "-map",
        "[video]",
        "-map",
        "[audio]",
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"FFmpeg timed out after {timeout_seconds:g} seconds while generating the demo fixture."
        ) from exc
    if completed.returncode != 0:
        diagnostic = completed.stderr.strip() or "No FFmpeg diagnostic was returned."
        raise RuntimeError(
            "FFmpeg could not generate the demo fixture: "
            f"exit code {completed.returncode}; {diagnostic}"
        )
    return path
