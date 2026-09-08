from pathlib import Path

import pytest
from pydantic import ValidationError

from releaseseal.config import (
    APIConfig,
    AIReviewConfig,
    AudioPeakDetectorConfig,
    BlackDetectorConfig,
    CaptionRuleConfig,
    ConfigurationError,
    PreflightConfig,
    TitleRuleConfig,
    TranscriptionConfig,
    VideoRuleConfig,
    load_config,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_default_detector_configuration_loads() -> None:
    config = load_config(REPOSITORY_ROOT / "config" / "releaseseal.default.yml")

    assert config.detectors.black.min_duration_seconds == 2.0
    assert config.detectors.silence.noise_threshold_db == -50.0
    assert config.detectors.freeze.min_duration_seconds == 2.5
    assert config.detectors.audio_peak.warning_threshold_dbfs == -1.0
    assert config.detectors.audio_peak.minimum_near_full_scale_sample_fraction == 0.05
    assert config.ai_review.enabled is False
    assert config.ai_review.provider == "gemini"
    assert config.ai_review.model == "gemini-3.7-flash"
    assert config.ai_review.promise_check.opening_review_horizon_seconds == 30.0
    assert config.ai_review.metadata_assist.visual_sample_count == 8
    assert config.ai_review.promise_check.minimum_issue_confidence == 0.70
    assert config.ai_review.viewer_pass.enabled is True
    assert config.ai_review.viewer_pass.minimum_issue_confidence == 0.75
    assert config.ai_review.claim_review.enabled is False
    assert config.ai_review.claim_review.maximum_claims == 3
    assert config.ai_review.promise_check.maximum_thumbnail_pixels == 16_777_216
    assert config.ai_review.promise_check.maximum_thumbnail_decompressed_bytes == 64_000_000
    assert config.api.maximum_video_upload_size_bytes == 2_147_483_648
    assert config.api.maximum_concurrent_scans == 2
    assert "http://127.0.0.1:5173" in config.api.allowed_browser_origins
    assert "https://talanezi.github.io" in config.api.allowed_browser_origins
    assert config.rules.video.minimum_width == 1280
    assert config.rules.title.maximum_recommended_length == 100
    assert config.rules.description.validate_urls is True
    assert config.rules.captions.maximum_uncovered_gap_seconds == 10.0
    assert config.release_package.thumbnail_assurance.enabled is True
    assert config.release_package.thumbnail_assurance.analysis_max_dimension == 320
    assert config.release_package.thumbnail_assurance.minimum_delivered_text_height_pixels == 8.0
    assert config.transcription.enabled is False
    assert config.transcription.local_files_only is True


def test_hosted_configuration_uses_public_demo_resource_bounds() -> None:
    config = load_config(REPOSITORY_ROOT / "config" / "releaseseal.hosted.yml")

    assert config.api.maximum_video_upload_size_bytes == 262_144_000
    assert config.api.maximum_concurrent_scans == 1
    assert config.api.allowed_browser_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://talanezi.github.io",
    ]
    assert config.transcription.enabled is False
    assert config.transcription.local_files_only is True
    assert config.detectors.black.min_duration_seconds == 2.0


@pytest.mark.parametrize(
    "origin",
    ["*", "talanezi.github.io", "https://talanezi.github.io/ReleaseSeal", "https://user@example.com"],
)
def test_browser_origins_must_be_exact_http_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        APIConfig(allowed_browser_origins=[origin])


def test_detector_configuration_rejects_invalid_threshold() -> None:
    with pytest.raises(ValidationError):
        BlackDetectorConfig(min_duration_seconds=0)


def test_yaml_configuration_error_is_structured(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.yml"
    config_path.write_text(
        "schema_version: 1\ndetectors:\n  silence:\n    noise_threshold_db: 4\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as captured:
        load_config(config_path)

    assert captured.value.message == "ReleaseSeal configuration is invalid."
    assert captured.value.errors is not None
    assert captured.value.errors[0]["location"] == "detectors.silence.noise_threshold_db"


def test_extended_configuration_is_valid() -> None:
    config = PreflightConfig.model_validate(
        {
            "schema_version": 1,
            "rules": {
                "profile_id": "demo",
                "video": {
                    "minimum_width": 1920,
                    "minimum_height": 1080,
                    "allowed_aspect_ratios": ["16:9"],
                },
                "description": {"required_phrases": ["Sources:"]},
                "captions": {"require": True},
            },
        }
    )

    assert config.rules.profile_id == "demo"
    assert config.rules.captions.require is True


@pytest.mark.parametrize("field", ["minimum_width", "minimum_height"])
def test_invalid_video_dimensions_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        VideoRuleConfig(**{field: 0})


def test_invalid_title_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TitleRuleConfig(maximum_recommended_length=0)


@pytest.mark.parametrize(
    "model,values",
    [
        (CaptionRuleConfig, {"maximum_uncovered_gap_seconds": 0}),
        (CaptionRuleConfig, {"overlap_warning_threshold_seconds": -1}),
        (CaptionRuleConfig, {"maximum_file_size_bytes": 0}),
        (TranscriptionConfig, {"speech_gap_minimum_seconds": 0}),
        (TranscriptionConfig, {"boundary_tolerance_seconds": -0.1}),
        (AudioPeakDetectorConfig, {"minimum_near_full_scale_sample_fraction": 0}),
        (AIReviewConfig, {"timeout_seconds": 0}),
        (AIReviewConfig, {"maximum_observations": 11}),
        (AIReviewConfig, {"timestamp_tolerance_seconds": -0.1}),
    ],
)
def test_invalid_caption_and_transcription_thresholds_are_rejected(model, values) -> None:
    with pytest.raises(ValidationError):
        model(**values)


@pytest.mark.parametrize("ratios", [[], ["16x9"], ["16:0"]])
def test_invalid_aspect_ratio_configuration_is_rejected(ratios: list[str]) -> None:
    with pytest.raises(ValidationError):
        VideoRuleConfig(allowed_aspect_ratios=ratios)
