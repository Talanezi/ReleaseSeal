"""Independent deterministic FFmpeg media anomaly detectors."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from releaseseal.config import (
    AudioPeakDetectorConfig,
    BlackDetectorConfig,
    FreezeDetectorConfig,
    SilenceDetectorConfig,
    ShortBlackDetectorConfig,
    StreamExpectationConfig,
)
from releaseseal.media import MediaInspectionError, require_media_tool
from releaseseal.models import (
    Finding,
    FindingSeverity,
    FindingStatus,
    MediaInspection,
)

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_BLACK_EVENT = re.compile(
    rf"black_start:(?P<start>{_NUMBER})\s+"
    rf"black_end:(?P<end>{_NUMBER})\s+"
    rf"black_duration:(?P<duration>{_NUMBER})"
)
_SILENCE_START = re.compile(rf"silence_start:\s*(?P<value>{_NUMBER})")
_SILENCE_END = re.compile(rf"silence_end:\s*(?P<value>{_NUMBER})")
_SILENCE_DURATION = re.compile(rf"silence_duration:\s*(?P<value>{_NUMBER})")
_FREEZE_START = re.compile(rf"freeze_start:\s*(?P<value>{_NUMBER})")
_FREEZE_END = re.compile(rf"freeze_end:\s*(?P<value>{_NUMBER})")
_FREEZE_DURATION = re.compile(rf"freeze_duration:\s*(?P<value>{_NUMBER})")
_MAX_VOLUME = re.compile(rf"max_volume:\s*(?P<value>{_NUMBER})\s*dB", re.IGNORECASE)
_SAMPLE_COUNT = re.compile(r"n_samples:\s*(?P<value>\d+)", re.IGNORECASE)
_HISTOGRAM_0DB = re.compile(r"histogram_0db:\s*(?P<value>\d+)", re.IGNORECASE)


class DetectorExecutionError(Exception):
    """A bounded detector-process failure without raw FFmpeg output."""

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


def detect_black_segments(
    media_path: str | Path,
    config: BlackDetectorConfig,
    *,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 60,
    short_config: ShortBlackDetectorConfig | None = None,
) -> list[Finding]:
    analysis_minimum = min(
        config.min_duration_seconds,
        short_config.min_duration_seconds if short_config and short_config.enabled else config.min_duration_seconds,
    )
    pixel_threshold = min(
        config.pixel_black_threshold,
        short_config.pixel_black_threshold if short_config and short_config.enabled else config.pixel_black_threshold,
    )
    picture_ratio = max(
        config.picture_black_ratio,
        short_config.picture_black_ratio if short_config and short_config.enabled else config.picture_black_ratio,
    )
    output = _run_ffmpeg(
        media_path,
        [
            "-map",
            "0:v:0",
            "-vf",
            (
                f"blackdetect=d={analysis_minimum:.6f}:"
                f"pic_th={picture_ratio:.6f}:"
                f"pix_th={pixel_threshold:.6f}"
            ),
            "-an",
        ],
        detector_name="black",
        ffmpeg_binary=ffmpeg_binary,
        timeout_seconds=timeout_seconds,
    )
    findings: list[Finding] = []
    for match in _BLACK_EVENT.finditer(output):
        start = float(match.group("start"))
        end = float(match.group("end"))
        duration = float(match.group("duration"))
        if end < start:
            continue
        if duration >= config.min_duration_seconds:
            findings.append(
            Finding(
                code="VIDEO_BLACK_SEGMENT",
                severity=FindingSeverity.WARNING,
                status=FindingStatus.NEEDS_REVIEW,
                message="A sustained near-black video section may need review.",
                source="video.black",
                timestamp_start_seconds=start,
                timestamp_end_seconds=end,
                details={
                    "category": "video",
                    "title": "Sustained near-black section",
                    "duration_seconds": duration,
                    "minimum_duration_seconds": config.min_duration_seconds,
                    "pixel_black_threshold": config.pixel_black_threshold,
                    "picture_black_ratio": config.picture_black_ratio,
                },
                suggestion="Check whether this dark section is intentional and appropriately timed.",
            ))
        elif (
            short_config is not None
            and short_config.enabled
            and short_config.min_duration_seconds <= duration <= short_config.max_duration_seconds
        ):
            findings.append(Finding(
                code="VIDEO_SHORT_BLACK_FLASH",
                severity=FindingSeverity.WARNING,
                status=FindingStatus.NEEDS_REVIEW,
                message="A very brief near-black flash was detected between surrounding frames.",
                source="video.black",
                timestamp_start_seconds=start,
                timestamp_end_seconds=end,
                details={
                    "category": "video",
                    "title": "Brief black flash candidate",
                    "duration_seconds": duration,
                    "minimum_duration_seconds": short_config.min_duration_seconds,
                    "maximum_duration_seconds": short_config.max_duration_seconds,
                },
                suggestion="Review this moment frame by frame to confirm whether the flash is an intentional edit.",
            ))
    return findings


def detect_long_silences(
    media_path: str | Path,
    media: MediaInspection,
    config: SilenceDetectorConfig,
    *,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 60,
) -> list[Finding]:
    if not media.has_audio:
        return []
    output = _run_ffmpeg(
        media_path,
        [
            "-map",
            "0:a:0",
            "-af",
            (
                f"silencedetect=noise={config.noise_threshold_db:.6f}dB:"
                f"d={config.min_duration_seconds:.6f}"
            ),
            "-vn",
        ],
        detector_name="silence",
        ffmpeg_binary=ffmpeg_binary,
        timeout_seconds=timeout_seconds,
    )
    intervals = _parse_silence_intervals(output, media.duration_seconds)
    return [
        Finding(
            code="AUDIO_LONG_SILENCE",
            severity=FindingSeverity.WARNING,
            status=FindingStatus.NEEDS_REVIEW,
            message="A sustained silent audio section may need review.",
            source="audio.silence",
            timestamp_start_seconds=start,
            timestamp_end_seconds=end,
            details={
                "category": "audio",
                "title": "Long silent section",
                "duration_seconds": duration,
                "minimum_duration_seconds": config.min_duration_seconds,
                "noise_threshold_db": config.noise_threshold_db,
            },
            suggestion="Confirm that this silent section is intentional.",
        )
        for start, end, duration in intervals
        if duration >= config.min_duration_seconds and end >= start
    ]


def detect_freeze_segments(
    media_path: str | Path,
    media: MediaInspection,
    config: FreezeDetectorConfig,
    *,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 60,
) -> list[Finding]:
    if not media.has_video:
        return []
    output = _run_ffmpeg(
        media_path,
        [
            "-map",
            "0:v:0",
            "-vf",
            (
                f"freezedetect=n={config.noise_threshold_db:.6f}dB:"
                f"d={config.min_duration_seconds:.6f}"
            ),
            "-an",
        ],
        detector_name="freeze",
        ffmpeg_binary=ffmpeg_binary,
        timeout_seconds=timeout_seconds,
    )
    intervals = _parse_freeze_intervals(output, media.duration_seconds)
    return [
        Finding(
            code="VIDEO_FREEZE_SEGMENT",
            severity=FindingSeverity.WARNING,
            status=FindingStatus.NEEDS_REVIEW,
            message="A sustained static-frame section may need review.",
            source="video.freeze",
            timestamp_start_seconds=start,
            timestamp_end_seconds=end,
            details={
                "category": "video",
                "title": "Sustained static-frame section",
                "duration_seconds": duration,
                "minimum_duration_seconds": config.min_duration_seconds,
                "noise_threshold_db": config.noise_threshold_db,
            },
            suggestion="Check whether this static section is an intentional still or title card.",
        )
        for start, end, duration in intervals
        if duration >= config.min_duration_seconds and end >= start
    ]


def inspect_audio_peak(
    media_path: str | Path,
    media: MediaInspection,
    config: AudioPeakDetectorConfig,
    *,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 60,
) -> list[Finding]:
    if not media.has_audio:
        return []
    output = _run_ffmpeg(
        media_path,
        ["-map", "0:a:0", "-af", "volumedetect", "-vn"],
        detector_name="audio_peak",
        ffmpeg_binary=ffmpeg_binary,
        timeout_seconds=timeout_seconds,
    )
    matches = list(_MAX_VOLUME.finditer(output))
    if not matches:
        raise DetectorExecutionError(
            "detector_output_invalid",
            "Audio peak analysis did not return a usable peak measurement.",
            details={"detector": "audio_peak"},
        )
    measured_peak = float(matches[-1].group("value"))
    if measured_peak < config.warning_threshold_dbfs:
        return []
    sample_counts = [int(match.group("value")) for match in _SAMPLE_COUNT.finditer(output)]
    decoded_sample_count = max(sample_counts, default=0)
    if decoded_sample_count <= 0:
        raise DetectorExecutionError(
            "detector_output_invalid",
            "Audio peak analysis did not return a usable decoded sample count.",
            details={"detector": "audio_peak"},
        )
    histogram_matches = list(_HISTOGRAM_0DB.finditer(output))
    near_full_scale_sample_count = (
        int(histogram_matches[-1].group("value")) if histogram_matches else 0
    )
    near_full_scale_sample_fraction = (
        near_full_scale_sample_count / decoded_sample_count
    )
    if (
        near_full_scale_sample_fraction
        < config.minimum_near_full_scale_sample_fraction
    ):
        return []
    return [
        Finding(
            code="AUDIO_PEAK_WARNING",
            severity=FindingSeverity.WARNING,
            status=FindingStatus.NEEDS_REVIEW,
            message=(
                "A substantial share of decoded audio samples is within the top "
                "1 dBFS and may indicate aggressive limiting or clipping."
            ),
            source="audio.peak",
            details={
                "category": "audio",
                "title": "Sustained near-full-scale audio",
                "measured_peak_dbfs": measured_peak,
                "warning_threshold_dbfs": config.warning_threshold_dbfs,
                "near_full_scale_sample_count": near_full_scale_sample_count,
                "decoded_sample_count": decoded_sample_count,
                "near_full_scale_sample_fraction": near_full_scale_sample_fraction,
                "minimum_near_full_scale_sample_fraction": (
                    config.minimum_near_full_scale_sample_fraction
                ),
                "near_full_scale_bin_lower_bound_dbfs": -1.0,
                "measurement_scope": "global",
            },
            suggestion=(
                "Review the loudest audio and confirm that the level and limiting are intentional."
            ),
        )
    ]


def detect_missing_streams(
    media: MediaInspection, config: StreamExpectationConfig
) -> list[Finding]:
    findings: list[Finding] = []
    if config.expect_video and not media.has_video:
        findings.append(
            _missing_stream_finding(
                code="VIDEO_STREAM_MISSING",
                stream="video",
                severity=config.missing_video_severity,
                message="No video stream was found in an input expected to be a creator video.",
                suggestion="Confirm that the intended video file was selected and exported correctly.",
            )
        )
    if config.expect_audio and not media.has_audio:
        findings.append(
            _missing_stream_finding(
                code="AUDIO_STREAM_MISSING",
                stream="audio",
                severity=config.missing_audio_severity,
                message="No audio stream was found; this may be intentional for a silent video.",
                suggestion="Confirm that a silent export is intentional.",
            )
        )
    return findings


def _missing_stream_finding(
    *,
    code: str,
    stream: str,
    severity: FindingSeverity,
    message: str,
    suggestion: str,
) -> Finding:
    status = {
        FindingSeverity.INFO: FindingStatus.READY,
        FindingSeverity.WARNING: FindingStatus.NEEDS_REVIEW,
        FindingSeverity.ERROR: FindingStatus.BLOCKED,
    }[severity]
    return Finding(
        code=code,
        severity=severity,
        status=status,
        message=message,
        source="media.streams",
        details={
            "category": "media",
            "title": f"Missing {stream} stream",
            "stream_type": stream,
        },
        suggestion=suggestion,
    )


def _run_ffmpeg(
    media_path: str | Path,
    analysis_arguments: list[str],
    *,
    detector_name: str,
    ffmpeg_binary: str,
    timeout_seconds: float,
) -> str:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    try:
        executable = require_media_tool(ffmpeg_binary)
    except MediaInspectionError as exc:
        raise DetectorExecutionError(exc.code, exc.message, details=exc.details) from exc

    command = [
        executable,
        "-hide_banner",
        "-nostats",
        "-v",
        "info",
        "-i",
        str(Path(media_path).resolve()),
        *analysis_arguments,
        "-sn",
        "-dn",
        "-f",
        "null",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise DetectorExecutionError(
            "detector_timeout",
            f"The {detector_name} detector timed out.",
            details={"detector": detector_name, "timeout_seconds": timeout_seconds},
        ) from exc
    except OSError as exc:
        raise DetectorExecutionError(
            "detector_execution_failed",
            f"The {detector_name} detector could not execute FFmpeg.",
            details={"detector": detector_name},
        ) from exc
    if completed.returncode != 0:
        raise DetectorExecutionError(
            "detector_failed",
            f"The {detector_name} detector could not analyze the media.",
            details={
                "detector": detector_name,
                "ffmpeg_exit_code": completed.returncode,
            },
        )
    return completed.stderr


def _parse_silence_intervals(
    output: str, media_duration: float | None
) -> list[tuple[float, float, float]]:
    intervals: list[tuple[float, float, float]] = []
    current_start: float | None = None
    for line in output.splitlines():
        start_match = _SILENCE_START.search(line)
        if start_match:
            current_start = max(0.0, float(start_match.group("value")))
        end_match = _SILENCE_END.search(line)
        if end_match:
            end = max(0.0, float(end_match.group("value")))
            duration_match = _SILENCE_DURATION.search(line)
            if current_start is None and duration_match:
                current_start = max(0.0, end - float(duration_match.group("value")))
            if current_start is not None and end >= current_start:
                intervals.append((current_start, end, end - current_start))
            current_start = None
    if (
        current_start is not None
        and media_duration is not None
        and media_duration >= current_start
    ):
        intervals.append(
            (current_start, media_duration, media_duration - current_start)
        )
    return intervals


def _parse_freeze_intervals(
    output: str, media_duration: float | None
) -> list[tuple[float, float, float]]:
    intervals: list[tuple[float, float, float]] = []
    current_start: float | None = None
    reported_duration: float | None = None
    for line in output.splitlines():
        start_match = _FREEZE_START.search(line)
        if start_match:
            current_start = max(0.0, float(start_match.group("value")))
            reported_duration = None
        duration_match = _FREEZE_DURATION.search(line)
        if duration_match:
            reported_duration = max(0.0, float(duration_match.group("value")))
        end_match = _FREEZE_END.search(line)
        if end_match:
            end = max(0.0, float(end_match.group("value")))
            if current_start is None and reported_duration is not None:
                current_start = max(0.0, end - reported_duration)
            if current_start is not None and end >= current_start:
                intervals.append((current_start, end, end - current_start))
            current_start = None
            reported_duration = None
    if (
        current_start is not None
        and media_duration is not None
        and media_duration >= current_start
    ):
        intervals.append(
            (current_start, media_duration, media_duration - current_start)
        )
    return intervals
