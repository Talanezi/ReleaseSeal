"""Deterministic copyright-free video fixture for Gemini integration smoke tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def generate_ai_smoke_video(
    output_path: str | Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 60,
) -> Path:
    """Generate three unmistakable four-second visual/audio states."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    video_filters = []
    audio_filters = []
    states = (
        ("0x1f5aa6", 80, 330),
        ("0x2d7a46", 270, 440),
        ("0xa33a32", 460, 550),
    )
    for index, (color, box_x, frequency) in enumerate(states):
        video_filters.append(
            f"color=c={color}:size=640x360:rate=24:duration=4,"
            f"drawbox=x={box_x}:y=130:w=100:h=100:color=white:t=fill[v{index}]"
        )
        audio_filters.append(
            f"sine=frequency={frequency}:sample_rate=48000:duration=4[a{index}]"
        )
    filter_graph = ";".join(
        [
            *video_filters,
            *audio_filters,
            "[v0][v1][v2]concat=n=3:v=1:a=0,format=yuv420p[video]",
            "[a0][a1][a2]concat=n=3:v=0:a=1[audio]",
        ]
    )
    command = [
        ffmpeg_binary,
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
        "-q:v",
        "5",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        str(output),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg is required to generate the AI smoke fixture.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("AI smoke fixture generation timed out.") from exc
    if completed.returncode != 0:
        raise RuntimeError("FFmpeg could not generate the AI smoke fixture.")
    return output
