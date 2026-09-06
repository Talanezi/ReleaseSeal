"""Shared typed contracts for media inspection and future findings."""

from enum import Enum
from typing import Any, Literal

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from creator_preflight.repair_models import RepairPlan
from creator_preflight.release_models import ReleaseBrief, ReleaseBriefSource


class FindingSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class FindingStatus(str, Enum):
    READY = "READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"


class ReviewMode(str, Enum):
    FULL = "full"
    LOCAL = "local"


class ScanCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class Finding(BaseModel):
    """Stable normalized finding shape shared by later detectors."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    severity: FindingSeverity
    status: FindingStatus
    message: str = Field(min_length=1)
    source: str = Field(min_length=1)
    timestamp_start_seconds: float | None = Field(default=None, ge=0)
    timestamp_end_seconds: float | None = Field(default=None, ge=0)
    details: dict[str, JsonValue] | None = None
    suggestion: str | None = None

    @model_validator(mode="after")
    def validate_timestamp_range(self) -> "Finding":
        if (
            self.timestamp_end_seconds is not None
            and self.timestamp_start_seconds is None
        ):
            raise ValueError("timestamp_end_seconds requires timestamp_start_seconds")
        if (
            self.timestamp_start_seconds is not None
            and self.timestamp_end_seconds is not None
            and self.timestamp_end_seconds < self.timestamp_start_seconds
        ):
            raise ValueError(
                "timestamp_end_seconds cannot be earlier than timestamp_start_seconds"
            )
        return self


class MediaInspection(BaseModel):
    """Normalized technical metadata for one local media file."""

    model_config = ConfigDict(extra="forbid")

    duration_seconds: float | None = Field(default=None, ge=0)
    format_name: str | None = None
    file_size_bytes: int = Field(ge=0)

    has_video: bool
    video_stream_count: int = Field(ge=0)
    video_codec: str | None = None
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    display_aspect_ratio: str | None = None
    frame_rate: float | None = Field(default=None, ge=0)
    pixel_format: str | None = None

    has_audio: bool
    audio_stream_count: int = Field(ge=0)
    audio_codec: str | None = None
    channel_count: int | None = Field(default=None, ge=0)
    sample_rate: int | None = Field(default=None, ge=0)


class AnomalyScanResult(BaseModel):
    """Milestone 2 media metadata and detector findings, without a verdict."""

    model_config = ConfigDict(extra="forbid")

    media: MediaInspection
    findings: list[Finding]


class PublishingPackage(BaseModel):
    """Creator-supplied publishing metadata, independent of any adapter."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    description: str = ""
    captions_path: Path | None = None
    thumbnail_path: Path | None = None
    profile_id: str | None = Field(default=None, min_length=1)


class CheckResult(BaseModel):
    """One explicitly executed check and the findings that caused it to fail."""

    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(min_length=1)
    passed: bool
    finding_codes: list[str] = Field(default_factory=list)


class CaptionSummary(BaseModel):
    """Compact timeline coverage statistics for a parsed caption file."""

    model_config = ConfigDict(extra="forbid")

    source_format: str
    cue_count: int = Field(ge=0)
    first_caption_seconds: float | None = Field(default=None, ge=0)
    last_caption_seconds: float | None = Field(default=None, ge=0)
    covered_duration_seconds: float = Field(ge=0)
    timeline_coverage_percent: float | None = Field(default=None, ge=0, le=100)


class AIReviewStatus(str, Enum):
    DISABLED = "disabled"
    NOT_RUN = "not_run"
    SUCCEEDED = "succeeded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class AIReviewSummary(BaseModel):
    """Safe provider provenance for one optional AI review attempt."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    provider: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=100)
    status: AIReviewStatus
    observation_count: int = Field(default=0, ge=0, le=10)
    runtime_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cleanup_succeeded: bool | None = None
    reason_code: str | None = Field(default=None, min_length=1, max_length=100)


class ExecutionIssue(BaseModel):
    """Safe non-content failure that prevented part of a scan from completing."""

    model_config = ConfigDict(extra="forbid")

    component: str = Field(min_length=1, max_length=100)
    reason_code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False


class PromiseCheckStatus(str, Enum):
    DISABLED = "disabled"
    ALIGNED = "aligned"
    NEEDS_REVIEW = "needs_review"
    NOT_EVALUABLE = "not_evaluable"
    UNAVAILABLE = "unavailable"


class PromiseCheckSummary(BaseModel):
    """Compact validated editorial result for title/thumbnail/video alignment."""

    model_config = ConfigDict(extra="forbid")

    status: PromiseCheckStatus
    inferred_promise: str | None = Field(default=None, max_length=500)
    first_substantive_address_seconds: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    first_substantive_address_evidence: str | None = Field(
        default=None, max_length=1000
    )
    opening_alignment: Literal[
        "direct_delivery", "relevant_hook", "relevant_setup", "unrelated_delay",
        "contradiction", "not_evaluable"
    ] | None = None
    overall_delivery: Literal["aligned", "partial", "mismatched", "not_evaluable"] | None = None
    explanation: str | None = Field(default=None, max_length=1500)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    thumbnail_alignment: Literal["aligned", "mismatched", "not_evaluable"] | None = None


class ViewerPassStatus(str, Enum):
    DISABLED = "disabled"
    CLEAN = "clean"
    NEEDS_REVIEW = "needs_review"
    NOT_EVALUABLE = "not_evaluable"
    UNAVAILABLE = "unavailable"


class ViewerPassSummary(BaseModel):
    """Compact result from the optional AI Final Viewer Pass."""

    model_config = ConfigDict(extra="forbid")

    status: ViewerPassStatus
    summary: str | None = Field(default=None, max_length=1000)
    issue_count: int = Field(default=0, ge=0, le=10)


class ClaimReviewStatus(str, Enum):
    DISABLED = "disabled"
    NO_CLAIMS = "no_claims"
    CLEAN = "clean"
    INCONCLUSIVE = "inconclusive"
    NEEDS_REVIEW = "needs_review"
    UNAVAILABLE = "unavailable"


class ClaimReviewSummary(BaseModel):
    """Compact, cautious result from optional grounded claim review."""

    model_config = ConfigDict(extra="forbid")

    status: ClaimReviewStatus
    claims_checked: int = Field(default=0, ge=0, le=3)
    supported_count: int = Field(default=0, ge=0, le=3)
    conflict_count: int = Field(default=0, ge=0, le=3)
    insufficient_evidence_count: int = Field(default=0, ge=0, le=3)
    explanation: str | None = Field(default=None, max_length=1000)


class PreflightReport(BaseModel):
    """Unified, explainable Creator Preflight scan report."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.8"
    verdict: FindingStatus
    scan_completeness: ScanCompleteness = ScanCompleteness.COMPLETE
    review_mode: ReviewMode = ReviewMode.LOCAL
    execution_issues: list[ExecutionIssue] = Field(default_factory=list)
    media: MediaInspection
    findings: list[Finding]
    checks: list[CheckResult]
    checks_run_count: int = Field(ge=0)
    passed_check_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    configuration_profile: str
    configuration_source: str | None = None
    caption_summary: CaptionSummary | None = None
    ai_review: AIReviewSummary
    promise_check: PromiseCheckSummary
    viewer_pass: ViewerPassSummary
    claim_review: ClaimReviewSummary
    repair_plan: RepairPlan = Field(default_factory=RepairPlan)
    release_brief: ReleaseBrief = Field(default_factory=lambda: ReleaseBrief(
        source=ReleaseBriefSource.DETERMINISTIC,
        headline="Review complete",
        summary="The completed checks are summarized in this report.",
    ))
    scan_duration_seconds: float = Field(ge=0)


class MediaToolAvailability(BaseModel):
    """Availability of local media executables required by the project."""

    model_config = ConfigDict(extra="forbid")

    ffprobe_available: bool
    ffprobe_path: str | None
    ffmpeg_available: bool
    ffmpeg_path: str | None


class CapabilityReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=300)


class PreflightCapabilities(BaseModel):
    """Non-secret runtime capability information used by the local web client."""

    model_config = ConfigDict(extra="forbid")

    ffprobe_available: bool
    ffmpeg_available: bool
    gemini_dependency_available: bool
    gemini_api_key_configured: bool
    full_review_available: bool
    metadata_assist_available: bool
    local_checks_available: bool
    revision_check_available: bool
    revision_semantic_review_available: bool
    transcription_dependency_available: bool
    transcription_enabled: bool
    supported_review_modes: list[ReviewMode]
    maximum_video_upload_size_bytes: int = Field(gt=0)
    full_review_unavailable_reasons: list[CapabilityReason] = Field(
        default_factory=list
    )


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
