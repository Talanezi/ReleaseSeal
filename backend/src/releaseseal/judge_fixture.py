"""Copyright-free creator-style fixtures for the final judge demonstration."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from releaseseal.promise_fixture import _canvas, _draw_text, _fill_rect, _write_png, _write_ppm


_DEFECTIVE_SCENES = [
    ((38, 48, 61), ("FIELD NOTES", "CREATOR UPDATE"), "Welcome back to Field Notes. Before today's story, here is a quick channel update."),
    ((67, 53, 45), ("THANK YOU", "STARTING SOON"), "Thank you for watching and supporting this series. Let us get started."),
    ((18, 56, 82), ("EIFFEL TOWER", "OPENED 1889"), "The Eiffel Tower opened in eighteen eighty nine for the Paris World's Fair."),
    ((27, 42, 76), ("APOLLO 11 MOON LANDING", "YEAR 1968"), "Apollo eleven landed on the Moon in the year one nine six eight."),
    ((70, 47, 39), ("TODO", "REPLACE THIS MAP"), "I think these old engineering landmarks are beautiful."),
]

_CORRECTED_SCENES = [
    ((18, 56, 82), ("EIFFEL TOWER", "OPENED 1889"), "The Eiffel Tower opened in eighteen eighty nine for the Paris World's Fair."),
    ((27, 42, 76), ("APOLLO 11 MOON LANDING", "YEAR 1969"), "Apollo eleven landed on the Moon in the year one nine six nine."),
    ((30, 72, 70), ("TWO MOMENTS", "ONE STORY"), "These are the two historical moments in today's story."),
    ((58, 52, 78), ("ENGINEERING", "AND EXPLORATION"), "I think both achievements remain inspiring examples of engineering and exploration."),
    ((38, 48, 61), ("THANK YOU", "FOR WATCHING"), "Thank you for watching this short Field Notes video."),
]


def generate_judge_demo(
    output_directory: str | Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 180,
) -> tuple[Path, Path, Path]:
    """Generate defective/corrected 60s video essays and one aligned thumbnail."""

    if shutil.which("say") is None:
        raise RuntimeError("macOS 'say' is required for the narrated judge demo.")
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    defective = _generate_video(
        output / "releaseseal-judge-defective.mp4",
        _DEFECTIVE_SCENES,
        black_interval=(12, 15),
        ffmpeg_binary=ffmpeg_binary,
        timeout_seconds=timeout_seconds,
    )
    corrected = _generate_video(
        output / "releaseseal-judge-corrected.mp4",
        _CORRECTED_SCENES,
        black_interval=None,
        ffmpeg_binary=ffmpeg_binary,
        timeout_seconds=timeout_seconds,
    )
    thumbnail = output / "releaseseal-judge-thumbnail.png"
    pixels = _scene_canvas((18, 56, 82), ("EIFFEL AND APOLLO", "TWO MOMENTS"))
    _write_png(thumbnail, pixels)
    return defective, corrected, thumbnail


def _generate_video(
    output: Path,
    scenes: list[tuple[tuple[int, int, int], tuple[str, str], str]],
    *,
    black_interval: tuple[int, int] | None,
    ffmpeg_binary: str,
    timeout_seconds: float,
) -> Path:
    with tempfile.TemporaryDirectory(prefix="releaseseal-judge-") as temp:
        temp_path = Path(temp)
        inputs: list[str] = []
        video_chains: list[str] = []
        audio_chains: list[str] = []
        for index, (color, lines, speech) in enumerate(scenes):
            image = temp_path / f"scene-{index}.ppm"
            audio = temp_path / f"speech-{index}.aiff"
            _write_ppm(image, _scene_canvas(color, lines))
            spoken = subprocess.run(
                ["say", "-r", "145", "-o", str(audio), speech],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if spoken.returncode != 0:
                raise RuntimeError("Local speech synthesis could not generate the judge demo.")
            inputs.extend(["-loop", "1", "-framerate", "15", "-t", "12", "-i", str(image)])
            inputs.extend(["-i", str(audio)])
            video_chains.append(
                f"[{index * 2}:v]eq=brightness='0.012*sin(2*PI*t)':eval=frame,"
                f"trim=duration=12,setpts=PTS-STARTPTS[v{index}]"
            )
            audio_chains.append(
                f"[{index * 2 + 1}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,"
                f"adelay=900,apad,atrim=duration=12,asetpts=PTS-STARTPTS[a{index}]"
            )
        joined = "".join(f"[v{i}][a{i}]" for i in range(len(scenes)))
        video_finish = (
            f"[vcat]drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:"
            f"enable='between(t,{black_interval[0]},{black_interval[1]})',format=yuv420p[video]"
            if black_interval
            else "[vcat]format=yuv420p[video]"
        )
        graph = ";".join([
            *video_chains,
            *audio_chains,
            f"{joined}concat=n={len(scenes)}:v=1:a=1[vcat][speech]",
            "sine=frequency=165:sample_rate=48000:duration=60,volume=0.025[roomtone]",
            "[speech][roomtone]amix=inputs=2:duration=first:normalize=0[audio]",
            video_finish,
        ])
        command = [
            ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *inputs,
            "-filter_complex",
            graph,
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
            "80k",
            str(output),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            diagnostic = completed.stderr.strip() or "unknown FFmpeg error"
            raise RuntimeError(f"FFmpeg could not generate the judge demo: {diagnostic}")
    return output


def _scene_canvas(color: tuple[int, int, int], lines: tuple[str, str]) -> list[bytearray]:
    pixels = _canvas(color, width=1280, height=720)
    _fill_rect(pixels, 72, 62, 8, 596, (238, 190, 80))
    _fill_rect(pixels, 104, 80, 420, 4, (210, 218, 225))
    _draw_text(pixels, "FIELD NOTES", 104, 110, scale=4, color=(210, 218, 225))
    _draw_text(pixels, lines[0], 104, 254, scale=11, color=(248, 249, 250))
    _draw_text(pixels, lines[1], 108, 430, scale=7, color=(255, 211, 104))
    _fill_rect(pixels, 104, 590, 860, 3, (160, 173, 184))
    _draw_text(pixels, "RELEASESEAL DEMO", 104, 620, scale=3, color=(194, 204, 213))
    return pixels
