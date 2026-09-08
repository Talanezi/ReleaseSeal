"""Canonical creator-facing presentation helpers."""

from __future__ import annotations

import math


def format_timecode(seconds: float) -> str:
    """Format seconds as MM:SS.xx, or H:MM:SS.xx for hour-plus media."""

    if not math.isfinite(seconds):
        raise ValueError("timecode seconds must be finite")
    total_hundredths = max(0, round(seconds * 100))
    hours, remainder = divmod(total_hundredths, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, hundredths = divmod(remainder, 100)
    base = f"{minutes:02d}:{whole_seconds:02d}.{hundredths:02d}"
    return f"{hours}:{base}" if hours else base


def format_timecode_interval(start_seconds: float, end_seconds: float | None = None) -> str:
    start = format_timecode(start_seconds)
    return start if end_seconds is None else f"{start}–{format_timecode(end_seconds)}"
