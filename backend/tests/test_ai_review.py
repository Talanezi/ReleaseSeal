import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from releaseseal import ai_review as ai_module
from releaseseal.ai_review import (
    AIObservation,
    AIObservationBatch,
    AIObservationType,
    AIReviewError,
    AIReviewResult,
    GeminiVideoReviewer,
    provider_video_mime_type,
)
from releaseseal.ai_smoke_fixture import generate_ai_smoke_video
from releaseseal.cli import main
from releaseseal.config import AIReviewConfig, PreflightConfig
from releaseseal.engine import PreflightScanner
from releaseseal.models import FindingStatus, PublishingPackage
from releaseseal.media import MediaInspector
from releaseseal.promise_check import (
    PromiseDelivery,
    PromiseProviderResult,
    PromiseReviewResult,
)


def _observation_payload(**changes):
    payload = {
        "observation_type": "visual_change",
        "summary": "Background changes",
        "explanation": "The background changes from blue to green.",
        "evidence": ["Blue is visible before the change", "Green follows"],
        "start_seconds": 4.0,
        "end_seconds": 4.5,
        "confidence": 0.95,
        "suggestion": None,
    }
    payload.update(changes)
    return payload


class FakeFiles:
    def __init__(self, *, state: str = "ACTIVE", cleanup_error: bool = False):
        self.remote = SimpleNamespace(
            name="files/test-video",
            uri="https://provider.invalid/files/test-video",
            mime_type="video/mp4",
            state=SimpleNamespace(name=state),
        )
        self.cleanup_error = cleanup_error
        self.deleted = False
        self.upload_count = 0

    def upload(self, *, file, config=None):
        assert file
        assert config == {"mime_type": "video/mp4", "display_name": Path(file).name}
        self.upload_count += 1
        return self.remote

    def get(self, *, name):
        assert name == self.remote.name
        return self.remote

    def delete(self, *, name):
        assert name == self.remote.name
        if self.cleanup_error:
            raise RuntimeError("cleanup unavailable")
        self.deleted = True


class FakeModels:
    def __init__(self, payload):
        self.payload = payload
        self.kwargs = None

    def create(self, **kwargs):
        raise AssertionError("Interactions API must not be used for video generation")

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(text=json.dumps(self.payload))


class FakeClient:
    def __init__(self, payload, *, state="ACTIVE", cleanup_error=False):
        self.files = FakeFiles(state=state, cleanup_error=cleanup_error)
        self.models = FakeModels(payload)
        self.interactions = FakeModels(payload)
        self.closed = False

    def close(self):
        self.closed = True


def _reviewer(client: FakeClient) -> GeminiVideoReviewer:
    return GeminiVideoReviewer(
        client_factory=lambda api_key, timeout_ms: client,
        environ={"GEMINI_API_KEY": "test-only-key"},
    )


def _test_config() -> PreflightConfig:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    config.rules.video.allowed_aspect_ratios = ["16:9"]
    return config


def _package() -> PublishingPackage:
    return PublishingPackage(title="Valid title", description="Valid description")


def test_ai_smoke_fixture_has_expected_duration_and_small_size(tmp_path: Path) -> None:
    path = generate_ai_smoke_video(tmp_path / "gemini-smoke.mp4")
    media = MediaInspector().inspect(path)

    assert media.duration_seconds == pytest.approx(12.0, abs=0.1)
    assert media.width == 640
    assert media.height == 360
    assert path.stat().st_size < 1_000_000


@pytest.mark.parametrize(
    "format_name, filename, expected",
    [
        ("mov,mp4,m4a,3gp,3g2,mj2", "video.mp4", "video/mp4"),
        ("mov,mp4,m4a,3gp,3g2,mj2", "video.mov", "video/quicktime"),
        ("matroska,webm", "video.webm", "video/webm"),
        ("matroska,webm", "video.mkv", None),
        ("avi", "video.mp4", None),
    ],
)
def test_provider_video_mime_requires_matching_ffprobe_container(
    format_name: str, filename: str, expected: str | None
) -> None:
    assert provider_video_mime_type(format_name, filename) == expected


def test_ai_observation_rejects_invalid_confidence_and_timestamps() -> None:
    for changes in (
        {"confidence": 1.01},
        {"start_seconds": -0.1},
        {"start_seconds": 5, "end_seconds": 4},
    ):
        with pytest.raises(ValidationError):
            AIObservation.model_validate(_observation_payload(**changes))


def test_missing_api_key_is_structured_unavailable(tmp_path: Path) -> None:
    reviewer = GeminiVideoReviewer(environ={})

    with pytest.raises(AIReviewError) as captured:
        reviewer.review(tmp_path / "video.mp4", 12.0, AIReviewConfig(enabled=True))

    assert captured.value.code == "ai_api_key_missing"
    assert captured.value.unavailable is True


def test_missing_optional_dependency_is_structured(
    monkeypatch, tmp_path: Path
) -> None:
    def missing_sdk():
        raise ModuleNotFoundError("google.genai")

    monkeypatch.setattr(ai_module, "_load_google_genai", missing_sdk)
    reviewer = GeminiVideoReviewer(environ={"GEMINI_API_KEY": "test-only-key"})

    with pytest.raises(AIReviewError) as captured:
        reviewer.review(tmp_path / "video.mp4", 12.0, AIReviewConfig(enabled=True))

    assert captured.value.code == "ai_dependency_unavailable"
    assert captured.value.unavailable is True


def test_successful_typed_provider_response_and_native_schema(tmp_path: Path) -> None:
    client = FakeClient({"observations": [_observation_payload()]})
    result = _reviewer(client).review(
        tmp_path / "video.mp4", 12.0, AIReviewConfig(enabled=True)
    )

    assert result.observations[0].observation_type is AIObservationType.VISUAL_CHANGE
    assert result.observations[0].start_seconds == 4.0
    assert client.files.deleted is True
    assert client.closed is True
    request = client.models.kwargs
    assert request["model"] == "gemini-3.7-flash"
    assert request["config"]["response_mime_type"] == "application/json"
    assert request["config"]["response_json_schema"]["title"] == "AIObservationBatch"
    assert request["config"]["automatic_function_calling"]["disable"] is True
    assert request["contents"][0] is client.files.remote


def test_structured_task_includes_thumbnail_in_same_single_upload(
    tmp_path: Path, monkeypatch
) -> None:
    client = FakeClient({"observations": []})
    thumbnail = tmp_path / "thumbnail.png"
    thumbnail.write_bytes(b"image bytes")
    inline_part = object()
    fake_types = SimpleNamespace(
        Part=SimpleNamespace(from_bytes=lambda **kwargs: inline_part)
    )
    monkeypatch.setattr(ai_module, "_load_google_genai_types", lambda: fake_types)

    result = _reviewer(client).review_structured(
        tmp_path / "video.mp4",
        config=AIReviewConfig(enabled=True),
        prompt="Task prompt",
        response_model=AIObservationBatch,
        image_path=thumbnail,
        image_mime_type="image/png",
    )

    assert result.output.observations == []
    assert client.files.upload_count == 1
    assert client.models.kwargs["contents"] == [
        client.files.remote,
        inline_part,
        "Task prompt",
    ]


@pytest.mark.parametrize(
    "payload, expected_code",
    [
        ({"unexpected": []}, "ai_provider_response_invalid"),
        (
            {"observations": [_observation_payload(confidence=2)]},
            "ai_provider_response_invalid",
        ),
        (
            {"observations": [_observation_payload(start_seconds=13, end_seconds=14)]},
            "ai_observation_timestamp_invalid",
        ),
    ],
)
def test_invalid_provider_output_is_rejected_safely(
    tmp_path: Path, payload, expected_code: str
) -> None:
    client = FakeClient(payload)

    with pytest.raises(AIReviewError) as captured:
        _reviewer(client).review(
            tmp_path / "video.mp4", 12.0, AIReviewConfig(enabled=True)
        )

    assert captured.value.code == expected_code
    assert client.files.deleted is True


def test_provider_timeout_and_api_error_are_structured(tmp_path: Path) -> None:
    class TimeoutFiles(FakeFiles):
        def upload(self, *, file, config=None):
            del file, config
            raise TimeoutError("provider timeout")

    timeout_client = FakeClient({"observations": []})
    timeout_client.files = TimeoutFiles()
    with pytest.raises(AIReviewError) as timeout_error:
        _reviewer(timeout_client).review(
            tmp_path / "video.mp4", 12.0, AIReviewConfig(enabled=True)
        )
    assert timeout_error.value.code == "ai_provider_timeout"

    class BrokenFiles(FakeFiles):
        def upload(self, *, file, config=None):
            del file, config
            raise RuntimeError("provider rejected upload")

    broken_client = FakeClient({"observations": []})
    broken_client.files = BrokenFiles()
    with pytest.raises(AIReviewError) as provider_error:
        _reviewer(broken_client).review(
            tmp_path / "video.mp4", 12.0, AIReviewConfig(enabled=True)
        )
    assert provider_error.value.code == "ai_upload_failed"


@pytest.mark.parametrize(
    "status_code, expected_code, retryable",
    [
        (401, "ai_provider_authentication_failed", False),
        (403, "ai_provider_permission_denied", False),
        (429, "ai_provider_quota_exhausted", True),
        (503, "ai_provider_unavailable", True),
    ],
)
def test_provider_http_statuses_have_safe_reason_codes(
    tmp_path: Path, status_code: int, expected_code: str, retryable: bool
) -> None:
    class ProviderError(Exception):
        def __init__(self, code: int):
            super().__init__("sensitive provider detail")
            self.code = code

    client = FakeClient({"observations": []})
    client.files.upload = lambda **kwargs: (_ for _ in ()).throw(ProviderError(status_code))
    with pytest.raises(AIReviewError) as captured:
        _reviewer(client).review(tmp_path / "video.mp4", 12.0, AIReviewConfig(enabled=True))

    assert captured.value.code == expected_code
    assert captured.value.retryable is retryable
    assert "sensitive" not in captured.value.message


def test_unsupported_video_container_is_rejected_before_provider_upload(tmp_path: Path) -> None:
    client = FakeClient({"observations": []})
    reviewer = _reviewer(client)
    session = reviewer.open_session(tmp_path / "video.avi", AIReviewConfig(enabled=True))

    with pytest.raises(AIReviewError) as captured:
        session.start()

    assert captured.value.code == "ai_media_unsupported"
    assert client.files.upload_count == 0


def test_generation_quota_error_is_safe_and_marked_unavailable(tmp_path: Path) -> None:
    client = FakeClient({"observations": []})
    client.models.generate_content = lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("429 RESOURCE_EXHAUSTED provider quota")
    )

    with pytest.raises(AIReviewError) as captured:
        _reviewer(client).review(
            tmp_path / "video.mp4", 12.0, AIReviewConfig(enabled=True)
        )

    assert captured.value.code == "ai_provider_quota_exhausted"
    assert captured.value.unavailable is True
    assert "429" not in captured.value.message


def test_processing_timeout_is_bounded(tmp_path: Path) -> None:
    client = FakeClient({"observations": []}, state="PROCESSING")

    with pytest.raises(AIReviewError) as captured:
        _reviewer(client).review(
            tmp_path / "video.mp4",
            12.0,
            AIReviewConfig(enabled=True, timeout_seconds=0.01),
        )

    assert captured.value.code == "ai_file_processing_timeout"
    assert client.files.deleted is True


def test_cleanup_failure_does_not_replace_success(tmp_path: Path) -> None:
    client = FakeClient({"observations": []}, cleanup_error=True)

    result = _reviewer(client).review(
        tmp_path / "video.mp4", 12.0, AIReviewConfig(enabled=True)
    )

    assert result.observations == []
    assert result.cleanup_succeeded is False


class ExplodingReviewer:
    def review(self, media_path, media_duration_seconds, **kwargs):
        raise AssertionError("disabled AI must not invoke the provider")


class ResultReviewer:
    def review(self, media_path, media_duration_seconds, **kwargs):
        return PromiseProviderResult(
            provider="gemini",
            model=kwargs["config"].model,
            review=PromiseReviewResult(
                inferred_promise="Explain the subject.",
                first_substantive_address_seconds=0.1,
                first_substantive_address_evidence="The explanation begins.",
                overall_delivery=PromiseDelivery.ALIGNED,
                overall_delivery_explanation="The video delivers the title.",
                confidence=0.95,
            ),
            upload_seconds=0.1,
            processing_seconds=0.2,
            generation_seconds=0.3,
            total_seconds=0.6,
            cleanup_succeeded=True,
        )


class UnavailableReviewer:
    def review(self, media_path, media_duration_seconds, **kwargs):
        raise AIReviewError(
            "ai_provider_unavailable", "Gemini is temporarily unavailable."
        )


def test_ai_disabled_never_invokes_provider(video_with_audio: Path) -> None:
    report = PreflightScanner(
        config=_test_config(), promise_reviewer=ExplodingReviewer()
    ).scan(video_with_audio, _package())

    assert report.verdict is FindingStatus.READY
    assert report.ai_review.status.value == "disabled"
    assert "ai.review" not in [check.check_id for check in report.checks]


def test_successful_ai_promise_review_is_recorded_without_fabricated_finding(
    video_with_audio: Path,
) -> None:
    config = _test_config()
    config.ai_review.enabled = True
    report = PreflightScanner(
        config=config, promise_reviewer=ResultReviewer()
    ).scan(video_with_audio, _package())

    assert report.verdict is FindingStatus.READY
    assert report.critical_count == 0
    assert report.warning_count == 0
    assert report.ai_review.status.value == "succeeded"
    assert report.ai_review.observation_count == 0
    assert report.promise_check.status.value == "aligned"
    assert report.findings == []


def test_ai_failure_preserves_deterministic_findings_and_never_blocks(
    video_with_audio: Path,
) -> None:
    config = _test_config()
    config.ai_review.enabled = True
    config.rules.title.maximum_recommended_length = 5
    report = PreflightScanner(
        config=config, promise_reviewer=UnavailableReviewer()
    ).scan(
        video_with_audio,
        PublishingPackage(title="Long valid title", description="Valid description"),
    )

    assert report.verdict is FindingStatus.NEEDS_REVIEW
    assert report.critical_count == 0
    assert [finding.code for finding in report.findings] == ["TITLE_LENGTH_RECOMMENDATION"]
    assert report.scan_completeness.value == "PARTIAL"
    assert report.execution_issues[0].reason_code == "ai_provider_unavailable"
    assert report.ai_review.status.value == "failed"
    assert report.promise_check.status.value == "unavailable"


def test_cli_json_remains_valid_when_ai_is_unavailable(
    video_with_audio: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config = _test_config()
    config.ai_review.enabled = True
    config_path = tmp_path / "ai-enabled.yml"
    config_path.write_text(
        yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8"
    )

    exit_code = main(
        [
            "scan",
            str(video_with_audio),
            "--title",
            "Valid title",
            "--description",
            "Valid description",
            "--config",
            str(config_path),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 2
    assert payload["ai_review"]["status"] == "unavailable"
    assert payload["verdict"] == "READY"
    assert payload["scan_completeness"] == "PARTIAL"
    assert payload["findings"] == []
    assert captured.err == ""
