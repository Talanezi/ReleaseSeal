"""Generate a bounded synthetic calibration corpus for thumbnail assurance."""

from __future__ import annotations

import subprocess
from pathlib import Path

from releaseseal.promise_fixture import _canvas, _draw_text, _fill_rect, _write_png


def generate_thumbnail_assurance_fixtures(
    output_directory: str | Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
) -> dict[str, Path]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    fixtures: dict[str, list[bytearray]] = {}

    fixtures["large_text"] = _artwork("MAIN STORY", x=100, y=220, scale=14)
    fixtures["tiny_text"] = _artwork("SMALL SUPPORTING TEXT", x=100, y=300, scale=3)
    fixtures["low_contrast"] = _artwork("LOW CONTRAST", x=100, y=220, scale=14, background=(80, 80, 80), foreground=(112, 112, 112))
    fixtures["badge_collision"] = _artwork("BADGE TEXT", x=930, y=550, scale=8)
    fixtures["unsafe_edge"] = _artwork("EDGE TEXT", x=2, y=4, scale=9)
    fixtures["safe_region"] = _artwork("SAFE TEXT", x=250, y=250, scale=12)

    multiple = _artwork("MAIN STORY", x=100, y=150, scale=14)
    _draw_text(multiple, "SMALL TEXT", 140, 410, scale=3, color=(245, 245, 245))
    fixtures["multiple_sizes"] = multiple

    outlined = _canvas((38, 66, 82), width=1280, height=720)
    for dx, dy in ((-4, 0), (4, 0), (0, -4), (0, 4), (5, 5)):
        _draw_text(outlined, "OUTLINED", 220 + dx, 240 + dy, scale=14, color=(3, 8, 12))
    _draw_text(outlined, "OUTLINED", 220, 240, scale=14, color=(246, 246, 246))
    fixtures["outlined_text"] = outlined

    natural = _canvas((115, 164, 186), width=1280, height=720)
    for row in range(360, 720):
        shade = 50 + (row - 360) // 12
        _fill_rect(natural, 0, row, 1280, 1, (45, min(120, shade + 35), 58))
    for offset in range(280):
        _fill_rect(natural, 300 + offset, 360 - offset // 2, 1, 180 + offset // 2, (77, 91, 86))
    fixtures["textless_natural"] = natural

    busy = _canvas((24, 30, 38), width=1280, height=720)
    for y in range(0, 720, 24):
        for x in range(0, 1280, 24):
            shade = 45 if (x // 24 + y // 24) % 2 else 125
            _fill_rect(busy, x, y, 24, 24, (shade, 90, 145 - shade // 2))
    _draw_text(busy, "BUSY STORY", 170, 260, scale=12, color=(250, 246, 238))
    fixtures["busy_background"] = busy
    detail = _canvas((20, 20, 20), width=1280, height=720)
    for y in range(0, 720, 4):
        for x in range(0, 1280, 4):
            shade = 230 if (x // 4 + y // 4) % 2 else 20
            _fill_rect(detail, x, y, 4, 4, (shade, shade, shade))
    fixtures["detail_heavy"] = detail
    fixtures["simple_composition"] = _artwork("SIMPLE", x=310, y=250, scale=14)

    paths: dict[str, Path] = {}
    for name, pixels in fixtures.items():
        path = output / f"{name}.png"
        _write_png(path, pixels)
        paths[name] = path

    jpeg = output / "large_text.jpg"
    result = subprocess.run(
        [ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(paths["large_text"]), "-q:v", "2", str(jpeg)],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("FFmpeg could not create the JPEG calibration fixture.")
    paths["large_text_jpeg"] = jpeg
    return paths


def _artwork(
    text: str,
    *,
    x: int,
    y: int,
    scale: int,
    background: tuple[int, int, int] = (20, 30, 40),
    foreground: tuple[int, int, int] = (250, 250, 250),
) -> list[bytearray]:
    pixels = _canvas(background, width=1280, height=720)
    _draw_text(pixels, text, x, y, scale=scale, color=foreground)
    return pixels
