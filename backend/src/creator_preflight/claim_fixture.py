"""Copyright-free narrated fixture for grounded Claim Review validation."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from creator_preflight.promise_fixture import _canvas, _draw_text, _write_ppm

SpeechRenderer = Callable[[str, Path], None]


def generate_claim_review_fixture(
    output_path: str | Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 120,
    speech_renderer: SpeechRenderer | None = None,
) -> Path:
    """Generate three 12s narrated scenes: supported, conflicting, subjective."""

    render_speech = speech_renderer or _render_macos_speech
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    scenes = [
        ((25, 66, 91), ("EIFFEL TOWER", "OPENED 1889"), "The Eiffel Tower opened in eighteen eighty nine."),
        ((37, 50, 92), ("APOLLO 11", "MOON LANDING 1968"), "Apollo eleven landed on the Moon in nineteen sixty eight."),
        ((78, 53, 38), ("OLD SPACECRAFT", "LOOK BEAUTIFUL"), "I think old spacecraft look beautiful."),
    ]
    with tempfile.TemporaryDirectory(prefix="creator-preflight-claims-") as temp:
        temp_path = Path(temp)
        inputs: list[str] = []
        video_chains: list[str] = []
        audio_chains: list[str] = []
        for index, (color, lines, speech) in enumerate(scenes):
            pixels = _canvas(color)
            _draw_text(pixels, lines[0], 60, 90, scale=6, color=(245, 247, 250))
            _draw_text(pixels, lines[1], 70, 220, scale=5, color=(255, 214, 105))
            image = temp_path / f"scene-{index}.ppm"
            audio = temp_path / f"speech-{index}.aiff"
            _write_ppm(image, pixels)
            render_speech(speech, audio)
            inputs.extend(["-loop", "1", "-framerate", "12", "-t", "12", "-i", str(image)])
            inputs.extend(["-i", str(audio)])
            video_chains.append(
                f"[{index * 2}:v]eq=brightness='0.015*sin(2*PI*t)':eval=frame,"
                f"trim=duration=12,setpts=PTS-STARTPTS[v{index}]"
            )
            audio_chains.append(
                f"[{index * 2 + 1}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,"
                f"adelay=2000,apad,atrim=duration=12,asetpts=PTS-STARTPTS[a{index}]"
            )
        joined = "".join(f"[v{i}][a{i}]" for i in range(len(scenes)))
        graph = ";".join([
            *video_chains, *audio_chains,
            f"{joined}concat=n=3:v=1:a=1[vcat][speech]",
            "sine=frequency=180:sample_rate=48000:duration=36,volume=0.03[ambient]",
            "[speech][ambient]amix=inputs=2:duration=first:normalize=0[audio]",
            "[vcat]format=yuv420p[video]",
        ])
        command = [
            ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y", *inputs,
            "-filter_complex", graph, "-map", "[video]", "-map", "[audio]",
            "-c:v", "mpeg4", "-q:v", "6", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "64k", str(output),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout_seconds)
        if completed.returncode != 0:
            diagnostic = completed.stderr.strip() or "unknown FFmpeg error"
            raise RuntimeError(f"FFmpeg could not generate the Claim Review fixture: {diagnostic}")
    return output


def _render_macos_speech(text: str, output_path: Path) -> None:
    """Render real narrated speech for optional maintainer/provider fixture use."""

    executable = shutil.which("say")
    if executable is None:
        raise RuntimeError("macOS 'say' is required for the narrated Claim Review fixture.")
    try:
        spoken = subprocess.run(
            [executable, "-r", "140", "-o", str(output_path), text],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Local speech synthesis could not generate the Claim Review fixture.") from exc
    if spoken.returncode != 0:
        raise RuntimeError("Local speech synthesis could not generate the Claim Review fixture.")
