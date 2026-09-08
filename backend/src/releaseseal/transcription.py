"""Optional lazy faster-whisper adapter with process-local model reuse."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from releaseseal.captions import SpeechSegment
from releaseseal.config import TranscriptionConfig


class SpeechTranscriber(Protocol):
    def transcribe(
        self, media_path: str | Path, config: TranscriptionConfig
    ) -> list[SpeechSegment]: ...


class TranscriptionUnavailableError(Exception):
    """Safe optional-capability failure that must not abort the core scan."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_MODEL_CACHE: dict[tuple[str, str, str, bool], Any] = {}


class WhisperTranscriber:
    """Transcribe locally, importing and loading faster-whisper only on demand."""

    def transcribe(
        self, media_path: str | Path, config: TranscriptionConfig
    ) -> list[SpeechSegment]:
        model = _get_model(config)
        try:
            segments, _ = model.transcribe(str(media_path), vad_filter=True)
            return [
                SpeechSegment(
                    start_seconds=max(0.0, float(segment.start)),
                    end_seconds=max(0.0, float(segment.end)),
                    text=str(segment.text).strip(),
                )
                for segment in segments
                if float(segment.end) >= float(segment.start)
            ]
        except TranscriptionUnavailableError:
            raise
        except Exception as exc:
            raise TranscriptionUnavailableError(
                "transcription_failed",
                "Local speech recognition could not complete; caption parsing and other checks still ran.",
            ) from exc


def _get_model(config: TranscriptionConfig):
    key = (config.model, config.device, config.compute_type, config.local_files_only)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptionUnavailableError(
            "transcription_dependency_unavailable",
            "Local speech recognition is enabled, but the optional faster-whisper dependency is not installed.",
        ) from exc
    try:
        model = WhisperModel(
            config.model,
            device=config.device,
            compute_type=config.compute_type,
            local_files_only=config.local_files_only,
        )
    except Exception as exc:
        raise TranscriptionUnavailableError(
            "transcription_model_unavailable",
            "The configured local speech-recognition model could not be loaded; no model was downloaded automatically.",
        ) from exc
    _MODEL_CACHE[key] = model
    return model


def clear_model_cache() -> None:
    """Test/support hook; ordinary scans retain cached models."""

    _MODEL_CACHE.clear()
