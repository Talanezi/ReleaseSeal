"""Bounded, content-based validation for optional Promise Check thumbnails."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ThumbnailInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mime_type: str
    file_size_bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ThumbnailValidationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def inspect_thumbnail(
    path: str | Path,
    *,
    maximum_bytes: int,
    maximum_width: int = 8192,
    maximum_height: int = 8192,
    maximum_pixels: int = 16_777_216,
    maximum_decompressed_bytes: int = 64_000_000,
) -> ThumbnailInfo:
    thumbnail_path = Path(path)
    if not thumbnail_path.is_file():
        raise ThumbnailValidationError(
            "thumbnail_not_found", "Thumbnail path is not a readable file."
        )
    size = thumbnail_path.stat().st_size
    if size == 0:
        raise ThumbnailValidationError(
            "thumbnail_empty", "The supplied thumbnail file is empty."
        )
    if size > maximum_bytes:
        raise ThumbnailValidationError(
            "thumbnail_too_large",
            f"Thumbnail exceeds the configured {maximum_bytes}-byte size limit.",
        )
    data = thumbnail_path.read_bytes()
    dimensions = _png_dimensions(
        data,
        maximum_pixels=maximum_pixels,
        maximum_decompressed_bytes=maximum_decompressed_bytes,
    )
    mime_type = "image/png"
    if dimensions is None:
        dimensions = _jpeg_dimensions(data)
        mime_type = "image/jpeg"
    if dimensions is None:
        raise ThumbnailValidationError(
            "thumbnail_invalid",
            "Thumbnail must be a readable PNG or JPEG image.",
        )
    width, height = dimensions
    if (
        width > maximum_width
        or height > maximum_height
        or width * height > maximum_pixels
    ):
        raise ThumbnailValidationError(
            "thumbnail_dimensions_too_large",
            "Thumbnail dimensions exceed the configured safe limit.",
        )
    return ThumbnailInfo(
        mime_type=mime_type, file_size_bytes=size, width=width, height=height
    )


def _png_dimensions(
    data: bytes, *, maximum_pixels: int, maximum_decompressed_bytes: int
) -> tuple[int, int] | None:
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    offset = 8
    dimensions = None
    compressed = bytearray()
    saw_end = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            return None
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
            return None
        if kind == b"IHDR":
            if dimensions is not None or length != 13:
                return None
            width, height = struct.unpack(">II", payload[:8])
            if width <= 0 or height <= 0:
                return None
            if width * height > maximum_pixels:
                raise ThumbnailValidationError(
                    "thumbnail_dimensions_too_large",
                    "Thumbnail dimensions exceed the configured safe limit.",
                )
            dimensions = (width, height)
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            saw_end = length == 0 and end == len(data)
            break
        offset = end
    if dimensions is None or not compressed or not saw_end:
        return None
    width, height = dimensions
    # PNG scanlines require at most eight bytes per pixel plus filter bytes.
    # Bound decompression independently of the compressed upload size so a
    # tiny IDAT stream cannot expand without a ceiling.
    maximum_output = min(
        width * height * 8 + height * 7 + 1024,
        maximum_decompressed_bytes,
    )
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(bytes(compressed), maximum_output + 1)
        if (
            not decoded
            or len(decoded) > maximum_output
            or decompressor.unconsumed_tail
            or not decompressor.eof
        ):
            return None
    except zlib.error:
        return None
    return dimensions


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
        return None
    offset = 2
    dimensions = None
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            return None
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            return None
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            return None
        segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(data):
            return None
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if segment_length < 7:
                return None
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            dimensions = (width, height) if width > 0 and height > 0 else None
            if dimensions is None:
                return None
        if marker == 0xDA:
            scan_start = offset + segment_length
            return dimensions if dimensions and scan_start < len(data) - 2 else None
        offset += segment_length
    return None
