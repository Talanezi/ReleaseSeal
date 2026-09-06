"""Generate the portable, creator-style official judge demo asset."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from creator_preflight.promise_fixture import _canvas, _draw_text, _fill_rect, _write_png, _write_ppm


TITLE = "Why Night Trains Are Returning to Europe"
DESCRIPTION = (
    "A short visual essay about why overnight rail is returning to European travel.\n\n"
    "00:00 The promise of a city-to-city night journey\n"
    "00:36 Why routes disappeared\n"
    "01:00 What changed\n"
    "01:36 The passenger experience\n"
    "02:12 What comes next"
)

SCENES = [
    ("NIGHT TRAINS", "ARE RETURNING", "Imagine leaving one city after dinner and waking up in another. Night trains are returning to make that journey possible."),
    ("CITY CENTER", "TO CITY CENTER", "The appeal is simple. Travelers can trade an airport transfer and a hotel night for one continuous trip."),
    ("A RELEVANT HOOK", "THE JOURNEY BEGINS", "That promise starts with the experience, not a long introduction. Step aboard, settle in, and let distance pass overnight."),
    ("WHY THEY FADED", "CHEAP FLIGHTS GREW", "Many overnight routes disappeared as low cost airlines expanded and railway operators focused on daytime services."),
    ("A HARD BUSINESS", "BEDS TAKE SPACE", "Sleeping cars carry fewer passengers than ordinary coaches, so each berth has to support more of the operating cost."),
    ("WHAT CHANGED", "DEMAND RETURNED", "Travel habits changed again. More passengers began comparing the whole journey, including airport time and an extra hotel night."),
    ("NEW ROUTES", "CITIES RECONNECT", "Operators started reconnecting major cities with modern rolling stock and simpler overnight timetables."),
    ("THE EXPORT", "SHOULD STAY VISIBLE", "A finished upload should carry the story without an unexplained interruption in picture or sound."),
    ("CABINS", "PRIVACY MATTERS", "Newer services offer a mix of seats, shared couchettes, and private cabins for different budgets."),
    ("ARRIVAL", "IN THE CITY", "Rail stations often place passengers near the center, making the morning arrival part of the value."),
    ("A QUIET MOMENT", "INTENTIONAL OR STUCK?", "A held image can be a deliberate pause, but it deserves review when it lasts longer than expected."),
    ("THE NETWORK", "STILL HAS GAPS", "Cross border schedules, track access, and rolling stock remain practical constraints on expansion."),
    ("THE TRADEOFF", "TIME FOR COMFORT", "Night trains will not replace every flight. They work best where the route and overnight timing fit together."),
    ("WHAT TO WATCH", "RELIABLE SERVICE", "The next test is whether operators can deliver reliable schedules, clear booking, and consistent onboard comfort."),
    ("THE BIG IDEA", "TRAVEL WHILE SLEEPING", "The renewed promise is not nostalgia. It is a practical way to turn travel time into rest and arrive where the day begins."),
]


def generate_official_demo(
    output_directory: str | Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 360,
) -> tuple[Path, Path, Path, Path, Path]:
    """Generate a three-minute 720p H.264/AAC demo with three controlled issues."""

    if shutil.which("say") is None:
        raise RuntimeError("macOS 'say' is required only to regenerate the tracked narrated asset.")
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    video = output / "creator-preflight-official-demo.mp4"
    thumbnail = output / "creator-preflight-official-thumbnail.png"
    captions = output / "creator-preflight-official-captions.srt"
    title = output / "creator-preflight-official-title.txt"
    description = output / "creator-preflight-official-description.txt"

    with tempfile.TemporaryDirectory(prefix="creator-preflight-official-") as temporary:
        temporary_path = Path(temporary)
        inputs: list[str] = []
        video_chains: list[str] = []
        audio_chains: list[str] = []
        for index, (heading, subheading, narration) in enumerate(SCENES):
            image = temporary_path / f"scene-{index}.ppm"
            audio = temporary_path / f"speech-{index}.aiff"
            _write_ppm(image, _scene_canvas(index, heading, subheading))
            spoken = subprocess.run(
                ["say", "-r", "150", "-o", str(audio), narration],
                capture_output=True, text=True, check=False, timeout=30,
            )
            if spoken.returncode != 0:
                raise RuntimeError("Local speech synthesis could not generate the official demo.")
            inputs.extend(["-loop", "1", "-framerate", "24", "-t", "12", "-i", str(image), "-i", str(audio)])
            visual_filter = "eq=brightness='0.010*sin(2*PI*t/3)':eval=frame,trim=duration=12,setpts=PTS-STARTPTS"
            video_chains.append(f"[{index * 2}:v]{visual_filter}[v{index}]")
            audio_chains.append(
                f"[{index * 2 + 1}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,volume=7,"
                f"adelay=700,apad,atrim=duration=12,asetpts=PTS-STARTPTS[a{index}]"
            )
        joined = "".join(f"[v{i}][a{i}]" for i in range(len(SCENES)))
        graph = ";".join([
            *video_chains, *audio_chains,
            f"{joined}concat=n={len(SCENES)}:v=1:a=1[vcat][speech]",
            "sine=frequency=110:sample_rate=48000:duration=180,volume=0.12[roomtone]",
            "[speech][roomtone]amix=inputs=2:duration=first:normalize=0[mixed]",
            "[mixed]volume=0:enable='between(t,126,132)'[audio]",
            "[vcat]drawbox=x='mod(t*42,iw)':y=92:w=160:h=3:color=0xEFC45C:t=fill,"
            "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,46,46.18)+between(t,78,82)',format=yuv420p[video]",
        ])
        command = [
            ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y", *inputs,
            "-filter_complex", graph, "-map", "[video]", "-map", "[audio]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(video),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout_seconds)
        if completed.returncode != 0:
            raise RuntimeError(f"FFmpeg could not generate the official demo: {completed.stderr.strip() or 'unknown error'}")

    _write_png(thumbnail, _scene_canvas(0, "NIGHT TRAINS", "ARE RETURNING"))
    captions.write_text(_captions(), encoding="utf-8")
    title.write_text(TITLE + "\n", encoding="utf-8")
    description.write_text(DESCRIPTION + "\n", encoding="utf-8")
    return video, thumbnail, captions, title, description


def _scene_canvas(index: int, heading: str, subheading: str) -> list[bytearray]:
    palettes = [(19, 38, 62), (42, 54, 70), (25, 58, 66), (58, 44, 62), (35, 56, 48)]
    pixels = _canvas(palettes[index % len(palettes)], width=1280, height=720)
    _fill_rect(pixels, 0, 0, 1280, 76, (14, 20, 29))
    _draw_text(pixels, "THE NIGHT ROUTE", 68, 24, scale=4, color=(210, 220, 228))
    _fill_rect(pixels, 68, 132, 8, 430, (239, 196, 92))
    _draw_text(pixels, heading, 112, 220, scale=11, color=(247, 249, 250))
    _draw_text(pixels, subheading, 116, 392, scale=7, color=(239, 196, 92))
    _fill_rect(pixels, 112, 590, 940, 2, (145, 160, 172))
    _draw_text(pixels, f"CHAPTER {index + 1:02d}", 112, 620, scale=3, color=(184, 197, 207))
    return pixels


def _captions() -> str:
    blocks = []
    for index, (_, _, narration) in enumerate(SCENES, start=1):
        start = (index - 1) * 12 + 0.7
        end = (index - 1) * 12 + 10.8
        blocks.append(f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n{narration}\n")
    return "\n".join(blocks)


def _srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"
