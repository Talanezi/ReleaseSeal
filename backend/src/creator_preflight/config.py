"""Typed configuration for Milestone 2 deterministic media detectors."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from creator_preflight.models import FindingSeverity
from creator_preflight.thumbnail_assurance import ThumbnailAssurancePolicy


class BlackDetectorConfig(BaseModel):
    """Blackdetect thresholds; durations use seconds and ratios use 0..1."""

    model_config = ConfigDict(extra="forbid")

    min_duration_seconds: float = Field(default=2.0, gt=0, le=3600)
    pixel_black_threshold: float = Field(default=0.10, gt=0, le=1)
    picture_black_ratio: float = Field(default=0.98, gt=0, le=1)


class ShortBlackDetectorConfig(BaseModel):
    """Conservative near-black flash candidates below the sustained threshold."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    min_duration_seconds: float = Field(default=0.08, gt=0, le=1)
    max_duration_seconds: float = Field(default=0.35, gt=0, le=2)
    pixel_black_threshold: float = Field(default=0.10, gt=0, le=1)
    picture_black_ratio: float = Field(default=0.98, gt=0, le=1)


class SilenceDetectorConfig(BaseModel):
    """Silencedetect thresholds in seconds and decibels relative to full scale."""

    model_config = ConfigDict(extra="forbid")

    min_duration_seconds: float = Field(default=2.0, gt=0, le=3600)
    noise_threshold_db: float = Field(default=-50.0, ge=-120, le=0)


class FreezeDetectorConfig(BaseModel):
    """Freezedetect thresholds in seconds and frame-difference decibels."""

    model_config = ConfigDict(extra="forbid")

    min_duration_seconds: float = Field(default=2.5, gt=0, le=3600)
    noise_threshold_db: float = Field(default=-60.0, ge=-120, le=0)


class AudioPeakDetectorConfig(BaseModel):
    """Global decoded near-full-scale density thresholds."""

    model_config = ConfigDict(extra="forbid")

    warning_threshold_dbfs: float = Field(default=-1.0, ge=-120, le=0)
    minimum_near_full_scale_sample_fraction: float = Field(
        default=0.05, gt=0, le=1
    )


class StreamExpectationConfig(BaseModel):
    """Expected streams and finding severities for creator-video inputs."""

    model_config = ConfigDict(extra="forbid")

    expect_video: bool = True
    expect_audio: bool = True
    missing_video_severity: FindingSeverity = FindingSeverity.ERROR
    missing_audio_severity: FindingSeverity = FindingSeverity.WARNING


class DetectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    black: BlackDetectorConfig = Field(default_factory=BlackDetectorConfig)
    short_black: ShortBlackDetectorConfig = Field(default_factory=ShortBlackDetectorConfig)
    silence: SilenceDetectorConfig = Field(default_factory=SilenceDetectorConfig)
    freeze: FreezeDetectorConfig = Field(default_factory=FreezeDetectorConfig)
    audio_peak: AudioPeakDetectorConfig = Field(default_factory=AudioPeakDetectorConfig)
    streams: StreamExpectationConfig = Field(default_factory=StreamExpectationConfig)


def _parse_aspect_ratio(value: str) -> float:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("aspect ratio must use WIDTH:HEIGHT format")
    try:
        width, height = (float(part) for part in parts)
    except ValueError as exc:
        raise ValueError("aspect ratio components must be numeric") from exc
    if width <= 0 or height <= 0:
        raise ValueError("aspect ratio components must be greater than zero")
    return width / height


class VideoRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_width: int = Field(default=1280, gt=0)
    minimum_height: int = Field(default=720, gt=0)
    allowed_aspect_ratios: list[str] = Field(
        default_factory=lambda: ["16:9", "9:16", "1:1"], min_length=1
    )
    aspect_ratio_tolerance: float = Field(default=0.02, ge=0, le=0.25)
    require_video: bool = True
    require_audio: bool = True

    @field_validator("allowed_aspect_ratios")
    @classmethod
    def validate_aspect_ratios(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            normalized = value.strip()
            _parse_aspect_ratio(normalized)
            if normalized not in cleaned:
                cleaned.append(normalized)
        if not cleaned:
            raise ValueError("at least one allowed aspect ratio is required")
        return cleaned


class TitleRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require: bool = True
    maximum_recommended_length: int = Field(default=100, gt=0, le=10000)


class DescriptionRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require: bool = True
    required_phrases: list[str] = Field(default_factory=list)
    validate_urls: bool = True

    @field_validator("required_phrases")
    @classmethod
    def validate_required_phrases(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("required phrases cannot be empty")
        return list(dict.fromkeys(cleaned))


class ChapterRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require: bool = False
    require_first_at_zero: bool = True


class CaptionRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require: bool = False
    maximum_file_size_bytes: int = Field(default=5_000_000, gt=0, le=50_000_000)
    maximum_uncovered_gap_seconds: float = Field(default=10.0, gt=0, le=3600)
    overlap_warning_threshold_seconds: float = Field(default=0.5, gt=0, le=3600)
    warn_on_empty_cues: bool = True


class TranscriptionConfig(BaseModel):
    """Opt-in local faster-whisper settings; disabled and network-free by default."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    model: str = Field(default="tiny.en", min_length=1, max_length=200)
    device: Literal["cpu", "cuda", "auto"] = "cpu"
    compute_type: str = Field(default="int8", min_length=1, max_length=50)
    local_files_only: bool = True
    speech_gap_minimum_seconds: float = Field(default=2.0, gt=0, le=3600)
    boundary_tolerance_seconds: float = Field(default=0.3, ge=0, le=5)
    adjacent_gap_merge_seconds: float = Field(default=0.5, ge=0, le=10)


class AIReviewConfig(BaseModel):
    """Opt-in server-side Gemini video review settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: Literal["gemini"] = "gemini"
    model: str = Field(default="gemini-3.7-flash", min_length=1, max_length=100)
    timeout_seconds: float = Field(default=180.0, gt=0, le=900)
    maximum_observations: int = Field(default=5, ge=1, le=10)
    timestamp_tolerance_seconds: float = Field(default=1.0, ge=0, le=10)
    promise_check: "PromiseCheckConfig" = Field(default_factory=lambda: PromiseCheckConfig())
    viewer_pass: "ViewerPassConfig" = Field(default_factory=lambda: ViewerPassConfig())
    claim_review: "ClaimReviewConfig" = Field(default_factory=lambda: ClaimReviewConfig())
    release_brief: "ReleaseBriefConfig" = Field(default_factory=lambda: ReleaseBriefConfig())
    metadata_assist: "MetadataAssistConfig" = Field(default_factory=lambda: MetadataAssistConfig())


class PromiseCheckConfig(BaseModel):
    """Conservative application policy applied to validated Promise output."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    opening_review_horizon_seconds: float = Field(default=30.0, gt=0, le=120)
    # Accepted only for compatibility with older profiles; no timer-based warning uses it.
    delay_warning_seconds: float | None = Field(default=None, gt=0, le=600)
    minimum_issue_confidence: float = Field(default=0.70, ge=0, le=1)
    maximum_thumbnail_file_size_bytes: int = Field(
        default=5_000_000, gt=0, le=20_000_000
    )
    maximum_thumbnail_width: int = Field(default=8192, gt=0, le=32768)
    maximum_thumbnail_height: int = Field(default=8192, gt=0, le=32768)
    maximum_thumbnail_pixels: int = Field(
        default=16_777_216, gt=0, le=268_435_456
    )
    maximum_thumbnail_decompressed_bytes: int = Field(
        default=64_000_000, gt=0, le=268_435_456
    )


class ViewerPassConfig(BaseModel):
    """Conservative policy for concrete final-export inconsistencies."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    minimum_issue_confidence: float = Field(default=0.75, ge=0, le=1)
    maximum_issues: int = Field(default=5, ge=1, le=10)


class ClaimReviewConfig(BaseModel):
    """Conservative policy for optional grounded factual-claim review."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    maximum_claims: int = Field(default=3, ge=1, le=3)
    minimum_extraction_confidence: float = Field(default=0.75, ge=0, le=1)
    minimum_conflict_confidence: float = Field(default=0.75, ge=0, le=1)


class ReleaseBriefConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False


class MetadataAssistConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    visual_sample_count: int = Field(default=8, ge=2, le=16)
    visual_sample_seconds: float = Field(default=4.0, gt=0, le=10)
    proxy_width: int = Field(default=320, ge=160, le=640)
    proxy_height: int = Field(default=180, ge=90, le=360)
    proxy_timeout_seconds: float = Field(default=120.0, gt=0, le=600)


class APIConfig(BaseModel):
    """Bounded process-local settings for the FastAPI adapter."""

    model_config = ConfigDict(extra="forbid")

    maximum_video_upload_size_bytes: int = Field(
        default=2_147_483_648, gt=0, le=10_737_418_240
    )
    maximum_concurrent_scans: int = Field(default=2, ge=1, le=8)
    allowed_browser_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    @field_validator("allowed_browser_origins")
    @classmethod
    def validate_allowed_origins(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip().rstrip("/") for value in values]
        if any(not value.startswith(("http://", "https://")) for value in cleaned):
            raise ValueError("browser origins must use http:// or https://")
        return list(dict.fromkeys(cleaned))


class ReleasePackageConfig(BaseModel):
    """Cheap, deterministic thumbnail delivery policy."""

    model_config = ConfigDict(extra="forbid")

    minimum_thumbnail_width: int = Field(default=1280, gt=0, le=16384)
    minimum_thumbnail_height: int = Field(default=720, gt=0, le=16384)
    target_thumbnail_aspect_ratio: float = Field(default=16 / 9, gt=0, le=10)
    thumbnail_aspect_ratio_tolerance: float = Field(default=.02, ge=0, le=.1)
    thumbnail_assurance: ThumbnailAssurancePolicy = Field(default_factory=ThumbnailAssurancePolicy)


class VerificationConfig(BaseModel):
    """Bounded deterministic repaired-output comparison and reel settings."""

    model_config = ConfigDict(extra="forbid")

    visual_sample_fps: float = Field(default=2.0, gt=0, le=10)
    maximum_visual_samples: int = Field(default=1200, ge=10, le=10000)
    visual_mean_difference_threshold: float = Field(default=18.0, ge=0, le=255)
    changed_pixel_difference_threshold: int = Field(default=24, ge=1, le=255)
    changed_pixel_fraction_threshold: float = Field(default=0.20, gt=0, le=1)
    edit_boundary_tolerance_seconds: float = Field(default=0.75, ge=0, le=10)
    review_reel_context_seconds: float = Field(default=3.0, ge=0, le=30)
    review_reel_maximum_segments: int = Field(default=12, ge=1, le=50)
    review_reel_maximum_duration_seconds: float = Field(default=180.0, gt=0, le=600)


class RevisionMapConfig(BaseModel):
    """Bounded deterministic sampling and monotonic revision-alignment policy."""

    model_config = ConfigDict(extra="forbid")

    visual_samples_per_second: float = Field(default=2.0, gt=0, le=10)
    maximum_visual_samples: int = Field(default=1200, ge=10, le=1800)
    descriptor_width: int = Field(default=17, ge=9, le=33)
    descriptor_height: int = Field(default=9, ge=5, le=18)
    strong_match_threshold: float = Field(default=0.12, ge=0, le=1)
    plausible_match_threshold: float = Field(default=0.28, ge=0, le=1)
    visual_changed_threshold: float = Field(default=0.28, ge=0, le=1)
    audio_changed_threshold: float = Field(default=0.30, ge=0, le=1)
    gap_penalty: float = Field(default=0.04, gt=0, le=2)
    maximum_substitution_cost: float = Field(default=0.64, gt=0, le=2)
    low_information_variance_threshold: float = Field(default=80.0, ge=0, le=10000)
    low_information_edge_threshold: float = Field(default=4.0, ge=0, le=255)
    low_information_penalty: float = Field(default=0.08, ge=0, le=1)
    audio_weight: float = Field(default=0.20, ge=0, le=0.5)
    audio_sample_rate: int = Field(default=8000, ge=1000, le=48000)
    minimum_segment_duration_seconds: float = Field(default=0.35, ge=0, le=5)
    merge_tolerance_seconds: float = Field(default=0.51, ge=0, le=5)
    refinement_radius_seconds: float = Field(default=2.0, ge=0, le=10)
    refinement_samples_per_second: float = Field(default=6.0, gt=0, le=20)
    maximum_refinement_samples: int = Field(default=240, ge=20, le=1000)
    extraction_timeout_seconds: float = Field(default=180.0, gt=0, le=900)
    alignment_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    @model_validator(mode="after")
    def validate_revision_thresholds(self) -> "RevisionMapConfig":
        if self.strong_match_threshold > self.plausible_match_threshold:
            raise ValueError("strong match threshold must not exceed plausible match threshold")
        return self


class RevisionCheckConfig(BaseModel):
    """Deterministic policy for correlating notes to physical revision regions."""

    model_config = ConfigDict(extra="forbid")

    point_neighborhood_seconds: float = Field(default=3.0, gt=0, le=30)
    explicit_range_tolerance_seconds: float = Field(default=0.25, ge=0, le=3)
    maximum_notes: int = Field(default=100, ge=1, le=500)
    maximum_notes_characters: int = Field(default=50_000, ge=1, le=250_000)
    maximum_note_characters: int = Field(default=500, ge=1, le=2_000)


class RevisionSemanticReviewConfig(BaseModel):
    """Bounded opt-in semantic comparison of deterministic revision regions."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    maximum_requests: int = Field(default=5, ge=1, le=10)
    maximum_parallel_requests: int = Field(default=2, ge=1, le=4)
    context_before_seconds: float = Field(default=2.5, ge=0, le=6)
    context_after_seconds: float = Field(default=2.5, ge=0, le=6)
    maximum_clip_duration_seconds: float = Field(default=12.0, gt=1, le=20)
    clip_width: int = Field(default=320, ge=160, le=640)
    clip_height: int = Field(default=180, ge=90, le=360)
    confidence_threshold: float = Field(default=0.80, ge=0, le=1)
    clip_timeout_seconds: float = Field(default=60.0, gt=0, le=300)


class CreatorRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(default="default", min_length=1)
    video: VideoRuleConfig = Field(default_factory=VideoRuleConfig)
    title: TitleRuleConfig = Field(default_factory=TitleRuleConfig)
    description: DescriptionRuleConfig = Field(default_factory=DescriptionRuleConfig)
    chapters: ChapterRuleConfig = Field(default_factory=ChapterRuleConfig)
    captions: CaptionRuleConfig = Field(default_factory=CaptionRuleConfig)


class PreflightConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    detectors: DetectorConfig = Field(default_factory=DetectorConfig)
    rules: CreatorRuleConfig = Field(default_factory=CreatorRuleConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    ai_review: AIReviewConfig = Field(default_factory=AIReviewConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    release_package: ReleasePackageConfig = Field(default_factory=ReleasePackageConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    revision_map: RevisionMapConfig = Field(default_factory=RevisionMapConfig)
    revision_check: RevisionCheckConfig = Field(default_factory=RevisionCheckConfig)
    revision_semantic_review: RevisionSemanticReviewConfig = Field(default_factory=RevisionSemanticReviewConfig)


class ConfigurationError(Exception):
    """Configuration failure with a concise application-level explanation."""

    def __init__(self, message: str, *, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors


def load_config(path: str | Path) -> PreflightConfig:
    """Load and validate detector and creator-rule configuration from YAML."""

    config_path = Path(path)
    try:
        raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(
            f"Could not read configuration file: {config_path}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError("Configuration file is not valid YAML.") from exc

    if not isinstance(raw_config, dict):
        raise ConfigurationError("Configuration root must be a YAML mapping.")
    try:
        return PreflightConfig.model_validate(raw_config)
    except ValidationError as exc:
        errors = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        raise ConfigurationError(
            "Creator Preflight configuration is invalid.", errors=errors
        ) from exc


def aspect_ratio_value(value: str) -> float:
    """Return the numeric value of an already validated WIDTH:HEIGHT ratio."""

    return _parse_aspect_ratio(value)
