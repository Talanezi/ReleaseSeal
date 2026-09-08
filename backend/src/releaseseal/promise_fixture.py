"""Deterministic, copyright-free semantic fixture for Promise Check validation."""

from __future__ import annotations

import struct
import subprocess
import tempfile
import zlib
from pathlib import Path


_GLYPHS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "11100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
}


def generate_promise_fixture(
    output_path: str | Path,
    thumbnail_path: str | Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 90,
) -> tuple[Path, Path]:
    """Generate a 36-second intro-then-blue-light explainer and aligned PNG."""

    output = Path(output_path)
    thumbnail = Path(thumbnail_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    intro = _canvas((71, 48, 112))
    _draw_text(intro, "WELCOME", 124, 128, scale=10, color=(246, 240, 255))
    _draw_text(intro, "CREATOR INTRO", 145, 230, scale=4, color=(211, 200, 232))
    subject = _canvas((14, 39, 73))
    _draw_text(subject, "BLUE LIGHT", 76, 90, scale=8, color=(104, 190, 255))
    _draw_text(subject, "CAN DISRUPT SLEEP", 78, 205, scale=4, color=(244, 246, 249))
    _draw_moon(subject, 540, 270, 42)

    with tempfile.TemporaryDirectory(prefix="releaseseal-promise-") as temp:
        intro_path = Path(temp) / "intro.ppm"
        subject_path = Path(temp) / "subject.ppm"
        _write_ppm(intro_path, intro)
        _write_ppm(subject_path, subject)
        command = [
            ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-framerate", "12", "-t", "12", "-i", str(intro_path),
            "-loop", "1", "-framerate", "12", "-t", "24", "-i", str(subject_path),
            "-f", "lavfi", "-t", "36", "-i", "sine=frequency=330:sample_rate=48000",
            "-filter_complex",
            (
                "[0:v]eq=brightness='0.02*sin(2*PI*t)':eval=frame[v0];"
                "[1:v]eq=brightness='0.02*sin(2*PI*t)':eval=frame[v1];"
                "[v0][v1]concat=n=2:v=1:a=0,format=yuv420p[video]"
            ),
            "-map", "[video]", "-map", "2:a", "-c:v", "mpeg4", "-q:v", "6",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-shortest", str(output),
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=timeout_seconds
        )
        if completed.returncode != 0:
            raise RuntimeError("FFmpeg could not generate the Promise Check fixture.")

    thumbnail_pixels = _canvas((14, 39, 73), width=640, height=360)
    _draw_text(thumbnail_pixels, "BLUE LIGHT", 76, 90, scale=8, color=(104, 190, 255))
    _draw_text(thumbnail_pixels, "SLEEP", 180, 210, scale=8, color=(244, 246, 249))
    _draw_moon(thumbnail_pixels, 535, 265, 48)
    _write_png(thumbnail, thumbnail_pixels)
    return output, thumbnail


def _canvas(color: tuple[int, int, int], *, width: int = 640, height: int = 360) -> list[bytearray]:
    row = bytearray(color * width)
    return [bytearray(row) for _ in range(height)]


def _draw_text(pixels, text: str, x: int, y: int, *, scale: int, color) -> None:
    cursor = x
    for character in text:
        if character == " ":
            cursor += 4 * scale
            continue
        glyph = _GLYPHS.get(character)
        if glyph is None:
            cursor += 6 * scale
            continue
        for row_index, row in enumerate(glyph):
            for column_index, bit in enumerate(row):
                if bit == "1":
                    _fill_rect(pixels, cursor + column_index * scale, y + row_index * scale, scale, scale, color)
        cursor += 6 * scale


def _draw_moon(pixels, center_x: int, center_y: int, radius: int) -> None:
    for y in range(center_y - radius, center_y + radius + 1):
        for x in range(center_x - radius, center_x + radius + 1):
            if (x - center_x) ** 2 + (y - center_y) ** 2 <= radius**2:
                if 0 <= y < len(pixels) and 0 <= x < len(pixels[0]) // 3:
                    offset = x * 3
                    pixels[y][offset : offset + 3] = bytes((245, 221, 132))


def _fill_rect(pixels, x: int, y: int, width: int, height: int, color) -> None:
    rgb = bytes(color)
    for row in range(max(0, y), min(len(pixels), y + height)):
        for column in range(max(0, x), min(len(pixels[row]) // 3, x + width)):
            offset = column * 3
            pixels[row][offset : offset + 3] = rgb


def _write_ppm(path: Path, pixels: list[bytearray]) -> None:
    path.write_bytes(
        f"P6\n{len(pixels[0]) // 3} {len(pixels)}\n255\n".encode() + b"".join(pixels)
    )


def _write_png(path: Path, pixels: list[bytearray]) -> None:
    width, height = len(pixels[0]) // 3, len(pixels)
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
