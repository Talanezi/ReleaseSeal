"""Safe FFprobe subprocess boundary and normalized media inspection."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

from releaseseal.models import MediaInspection, MediaToolAvailability


class MediaInspectionError(Exception):
    """A structured error safe for application adapters to translate."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def check_media_tools(
    *, ffprobe_binary: str = "ffprobe", ffmpeg_binary: str = "ffmpeg"
) -> MediaToolAvailability:
    """Report whether the local FFprobe and FFmpeg executables are available."""

    ffprobe_path = shutil.which(ffprobe_binary)
    ffmpeg_path = shutil.which(ffmpeg_binary)
    return MediaToolAvailability(
        ffprobe_available=ffprobe_path is not None,
        ffprobe_path=ffprobe_path,
        ffmpeg_available=ffmpeg_path is not None,
        ffmpeg_path=ffmpeg_path,
    )


def require_media_tool(binary: str) -> str:
    """Resolve a media executable or raise a clear dependency error."""

    executable = shutil.which(binary)
    if executable is None:
        raise MediaInspectionError(
            "media_tool_unavailable",
            f"Required media tool '{binary}' is not available on PATH.",
            details={"tool": binary},
        )
    return executable


class MediaInspector:
    def __init__(self, *, ffprobe_binary: str = "ffprobe", timeout_seconds: float = 15):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.ffprobe_binary = ffprobe_binary
        self.timeout_seconds = timeout_seconds

    def inspect(self, media_path: str | Path) -> MediaInspection:
        path = Path(media_path)
        self._validate_path(path)
        resolved_path = path.resolve()
        executable = require_media_tool(self.ffprobe_binary)

        command = [
            executable,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(resolved_path),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaInspectionError(
                "ffprobe_timeout",
                "Media inspection timed out.",
                details={"timeout_seconds": self.timeout_seconds},
            ) from exc
        except OSError as exc:
            raise MediaInspectionError(
                "ffprobe_execution_failed",
                "FFprobe could not be executed.",
                details={"tool": self.ffprobe_binary},
            ) from exc

        if completed.returncode != 0:
            raise MediaInspectionError(
                "invalid_media",
                "FFprobe could not parse the supplied media file.",
                details={"ffprobe_exit_code": completed.returncode},
            )

        try:
            payload = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise MediaInspectionError(
                "invalid_ffprobe_output",
                "FFprobe returned an invalid metadata response.",
            ) from exc
        if not isinstance(payload, dict):
            raise MediaInspectionError(
                "invalid_ffprobe_output",
                "FFprobe returned an invalid metadata response.",
            )

        return self._normalize(payload, resolved_path.stat().st_size)

    @staticmethod
    def _validate_path(path: Path) -> None:
        if not path.exists():
            raise MediaInspectionError(
                "file_not_found", "The supplied media file does not exist."
            )
        if not path.is_file():
            raise MediaInspectionError(
                "not_a_file", "The supplied media path is not a file."
            )
        if path.stat().st_size == 0:
            raise MediaInspectionError(
                "empty_file", "The supplied media file is empty."
            )

    @staticmethod
    def _normalize(payload: dict[str, Any], file_size: int) -> MediaInspection:
        raw_streams = payload.get("streams")
        streams = (
            [stream for stream in raw_streams if isinstance(stream, dict)]
            if isinstance(raw_streams, list)
            else []
        )
        video_streams = [
            stream for stream in streams if stream.get("codec_type") == "video"
        ]
        audio_streams = [
            stream for stream in streams if stream.get("codec_type") == "audio"
        ]
        video = _primary_stream(video_streams)
        audio = _primary_stream(audio_streams)
        raw_format = payload.get("format")
        format_data = raw_format if isinstance(raw_format, dict) else {}

        duration = _positive_float(format_data.get("duration"), allow_zero=True)
        if duration is None:
            durations = [
                value
                for value in (_positive_float(stream.get("duration")) for stream in streams)
                if value is not None
            ]
            duration = max(durations, default=None)

        return MediaInspection(
            duration_seconds=duration,
            format_name=_useful_string(format_data.get("format_name")),
            file_size_bytes=file_size,
            has_video=video is not None,
            video_stream_count=len(video_streams),
            video_codec=_useful_string(video.get("codec_name")) if video else None,
            width=_nonnegative_int(video.get("width")) if video else None,
            height=_nonnegative_int(video.get("height")) if video else None,
            display_aspect_ratio=(
                _useful_string(video.get("display_aspect_ratio")) if video else None
            ),
            frame_rate=_frame_rate(video) if video else None,
            pixel_format=_useful_string(video.get("pix_fmt")) if video else None,
            has_audio=audio is not None,
            audio_stream_count=len(audio_streams),
            audio_codec=_useful_string(audio.get("codec_name")) if audio else None,
            channel_count=_nonnegative_int(audio.get("channels")) if audio else None,
            sample_rate=_nonnegative_int(audio.get("sample_rate")) if audio else None,
        )


def _primary_stream(streams: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not streams:
        return None
    return next(
        (
            stream
            for stream in streams
            if isinstance(stream.get("disposition"), dict)
            and stream["disposition"].get("default") == 1
        ),
        streams[0],
    )


def _useful_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.upper() == "N/A":
        return None
    return cleaned


def _positive_float(value: Any, *, allow_zero: bool = False) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0 or (parsed == 0 and not allow_zero):
        return None
    return parsed


def _nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _frame_rate(stream: dict[str, Any]) -> float | None:
    for field in ("avg_frame_rate", "r_frame_rate"):
        value = stream.get(field)
        if isinstance(value, str) and "/" in value:
            numerator, denominator = value.split("/", maxsplit=1)
            numerator_value = _positive_float(numerator, allow_zero=True)
            denominator_value = _positive_float(denominator)
            if numerator_value is not None and denominator_value is not None:
                rate = numerator_value / denominator_value
                if rate > 0:
                    return rate
        else:
            rate = _positive_float(value)
            if rate is not None:
                return rate
    return None
