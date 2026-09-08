from pathlib import Path

from releaseseal.captions import SpeechSegment
from releaseseal.config import PreflightConfig, TranscriptionConfig
from releaseseal.engine import PreflightScanner
from releaseseal.models import PublishingPackage
from releaseseal.transcription import TranscriptionUnavailableError
from releaseseal import transcription
import pytest


def _scan_config(*, enabled: bool) -> PreflightConfig:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    config.rules.video.allowed_aspect_ratios = ["16:9"]
    config.transcription.enabled = enabled
    return config


class RecordingTranscriber:
    def __init__(self, segments: list[SpeechSegment] | None = None) -> None:
        self.calls = 0
        self.segments = segments or []

    def transcribe(
        self, media_path: str | Path, config: TranscriptionConfig
    ) -> list[SpeechSegment]:
        del media_path, config
        self.calls += 1
        return self.segments


class FailingTranscriber:
    def transcribe(
        self, media_path: str | Path, config: TranscriptionConfig
    ) -> list[SpeechSegment]:
        del media_path, config
        raise TranscriptionUnavailableError(
            "transcription_model_unavailable", "The local model could not be loaded."
        )


def test_dependency_unavailable_state_is_structured(monkeypatch, tmp_path: Path) -> None:
    def unavailable(config):
        del config
        raise TranscriptionUnavailableError(
            "transcription_dependency_unavailable", "faster-whisper is not installed."
        )

    monkeypatch.setattr(transcription, "_get_model", unavailable)

    with pytest.raises(TranscriptionUnavailableError) as captured:
        transcription.WhisperTranscriber().transcribe(
            tmp_path / "media.mp4", TranscriptionConfig(enabled=True)
        )
    assert captured.value.code == "transcription_dependency_unavailable"


def test_transcription_runtime_failure_is_structured(monkeypatch, tmp_path: Path) -> None:
    class BrokenModel:
        def transcribe(self, *args, **kwargs):
            del args, kwargs
            raise RuntimeError("decoder failed")

    monkeypatch.setattr(transcription, "_get_model", lambda config: BrokenModel())

    with pytest.raises(TranscriptionUnavailableError) as captured:
        transcription.WhisperTranscriber().transcribe(
            tmp_path / "media.mp4", TranscriptionConfig(enabled=True)
        )
    assert captured.value.code == "transcription_failed"


def test_loaded_whisper_model_is_reused_within_process() -> None:
    config = TranscriptionConfig(enabled=True)
    key = (config.model, config.device, config.compute_type, config.local_files_only)
    cached_model = object()
    transcription.clear_model_cache()
    transcription._MODEL_CACHE[key] = cached_model
    try:
        assert transcription._get_model(config) is cached_model
        assert transcription._get_model(config) is cached_model
    finally:
        transcription.clear_model_cache()


def test_transcription_disabled_never_invokes_optional_adapter(
    video_with_audio: Path,
) -> None:
    transcriber = RecordingTranscriber([SpeechSegment(0, 1, "speech")])
    report = PreflightScanner(
        config=_scan_config(enabled=False), transcriber=transcriber
    ).scan(
        video_with_audio,
        PublishingPackage(title="Title", description="Description"),
    )

    assert transcriber.calls == 0
    assert "captions.speech_coverage" not in [check.check_id for check in report.checks]


def test_optional_dependency_or_model_failure_does_not_break_core_scan(
    video_with_audio: Path,
) -> None:
    report = PreflightScanner(
        config=_scan_config(enabled=True), transcriber=FailingTranscriber()
    ).scan(
        video_with_audio,
        PublishingPackage(title="Title", description="Description"),
    )

    assert "CAPTION_TRANSCRIPTION_UNAVAILABLE" not in [finding.code for finding in report.findings]
    assert report.scan_completeness.value == "PARTIAL"
    assert report.execution_issues[0].component == "captions.transcription"
    assert report.media.has_video is True
    speech_check = next(
        check for check in report.checks if check.check_id == "captions.speech_coverage"
    )
    assert speech_check.passed is False


def test_mocked_speech_segments_integrate_with_real_caption_parser(
    video_with_audio: Path, tmp_path: Path
) -> None:
    captions = tmp_path / "captions.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:00,400\nCovered start\n",
        encoding="utf-8",
    )
    transcriber = RecordingTranscriber([SpeechSegment(0, 0.4, "covered")])
    config = _scan_config(enabled=True)
    config.transcription.speech_gap_minimum_seconds = 0.2
    report = PreflightScanner(config=config, transcriber=transcriber).scan(
        video_with_audio,
        PublishingPackage(
            title="Title", description="Description", captions_path=captions
        ),
    )

    assert transcriber.calls == 1
    assert "CAPTION_SPEECH_GAP" not in [finding.code for finding in report.findings]
    assert next(
        check for check in report.checks if check.check_id == "captions.speech_coverage"
    ).passed
    assert report.caption_summary is not None
    assert report.caption_summary.cue_count == 1
