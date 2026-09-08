"""Copyright-free creator-style fixtures for live Final Viewer Pass validation."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from releaseseal.promise_fixture import _canvas, _draw_text, _write_ppm


def generate_viewer_pass_fixture(
    output_path: str | Path,
    *,
    problematic: bool,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 120,
) -> Path:
    """Generate a 45s clean or 48s deliberately inconsistent narrated fixture."""

    if shutil.which("say") is None:
        raise RuntimeError("macOS 'say' is required for the narrated Viewer Pass fixture.")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if problematic:
        segments = [
            (12, (20, 55, 91), ("AURORA PROJECT", "LAUNCH YEAR 2020"),
             "The fictional Aurora project launched in twenty twenty one."),
            (12, (92, 47, 28), ("TODO", "REPLACE THIS CHART"),
             "Here is the project timeline."),
            (12, (24, 86, 61), ("AURORA PROJECT", "UPDATE COMPLETE"),
             "The Aurora project update is complete."),
            (12, (24, 86, 61), ("AURORA PROJECT", "UPDATE COMPLETE"),
             "The Aurora project update is complete."),
        ]
    else:
        segments = [
            (15, (20, 55, 91), ("AURORA PROJECT", "LAUNCH YEAR 2021"),
             "The fictional Aurora project launched in twenty twenty one."),
            (15, (35, 75, 106), ("LAUNCH YEAR 2021", "TIMELINE CONFIRMED"),
             "Launch year twenty twenty one is shown on screen and matches the narration."),
            (15, (24, 86, 61), ("AURORA PROJECT", "STATUS ACTIVE"),
             "The Aurora project remains active."),
        ]

    with tempfile.TemporaryDirectory(prefix="releaseseal-viewer-") as temp:
        temp_path = Path(temp)
        inputs: list[str] = []
        video_chains: list[str] = []
        audio_chains: list[str] = []
        for index, (duration, color, lines, speech) in enumerate(segments):
            pixels = _canvas(color)
            _draw_text(pixels, lines[0], 62, 92, scale=7, color=(246, 248, 250))
            _draw_text(pixels, lines[1], 50, 220, scale=5, color=(255, 210, 92))
            image_path = temp_path / f"scene-{index}.ppm"
            audio_path = temp_path / f"speech-{index}.aiff"
            _write_ppm(image_path, pixels)
            spoken = subprocess.run(
                ["say", "-r", "145", "-o", str(audio_path), speech],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if spoken.returncode != 0:
                raise RuntimeError("Local speech synthesis could not generate the fixture.")
            inputs.extend(["-loop", "1", "-framerate", "12", "-t", str(duration), "-i", str(image_path)])
            inputs.extend(["-i", str(audio_path)])
            video_chains.append(
                f"[{index * 2}:v]eq=brightness='0.015*sin(2*PI*t)':eval=frame,"
                f"trim=duration={duration},setpts=PTS-STARTPTS[v{index}]"
            )
            audio_chains.append(
                f"[{index * 2 + 1}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,"
                f"apad,atrim=duration={duration},asetpts=PTS-STARTPTS[a{index}]"
            )
        joined = "".join(f"[v{i}][a{i}]" for i in range(len(segments)))
        total_duration = sum(segment[0] for segment in segments)
        graph = ";".join([
            *video_chains,
            *audio_chains,
            f"{joined}concat=n={len(segments)}:v=1:a=1[vcat][speech]",
            f"sine=frequency=180:sample_rate=48000:duration={total_duration},volume=0.05[ambient]",
            "[speech][ambient]amix=inputs=2:duration=first:normalize=0[audio]",
            "[vcat]format=yuv420p[video]",
        ])
        command = [
            ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y",
            *inputs,
            "-filter_complex", graph,
            "-map", "[video]", "-map", "[audio]",
            "-c:v", "mpeg4", "-q:v", "6", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "64k", str(output),
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=timeout_seconds
        )
        if completed.returncode != 0:
            diagnostic = completed.stderr.strip() or "unknown FFmpeg error"
            raise RuntimeError(f"FFmpeg could not generate the Viewer Pass fixture: {diagnostic}")
    return output
