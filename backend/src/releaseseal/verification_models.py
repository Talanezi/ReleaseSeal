"""Strict contracts for verifying ReleaseSeal-produced repairs."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from releaseseal.models import Finding, PreflightReport, ScanCompleteness


class RepairVerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INCOMPLETE = "INCOMPLETE"


class FindingComparisonStatus(str, Enum):
    RESOLVED = "RESOLVED"
    REMAINING = "REMAINING"
    NEW = "NEW"


class FindingComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: FindingComparisonStatus
    original_finding: Finding | None = None
    repaired_finding: Finding | None = None
    expected_repaired_start_seconds: float | None = Field(default=None, ge=0)
    expected_repaired_end_seconds: float | None = Field(default=None, ge=0)
    deterministically_verified: bool = False
    explanation: str = Field(min_length=1, max_length=600)


class RepairIntegrityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    duration_matches: bool
    streams_match: bool
    resolution_matches: bool
    operations_verified: int = Field(ge=0, le=10)
    reference_intervals_survived: bool
    explanation: str = Field(min_length=1, max_length=600)


class UnexpectedChangeInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    maximum_mean_difference: float = Field(ge=0, le=255)
    sample_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_interval(self) -> "UnexpectedChangeInterval":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("unexpected-change end must exceed start")
        return self


class ReviewReelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reel_start_seconds: float = Field(ge=0)
    reel_end_seconds: float = Field(gt=0)
    source_start_seconds: float = Field(ge=0)
    source_end_seconds: float = Field(gt=0)
    reason: str = Field(min_length=1, max_length=600)
    category: str = Field(min_length=1, max_length=80)
    source_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_ranges(self) -> "ReviewReelEntry":
        if self.reel_end_seconds <= self.reel_start_seconds or self.source_end_seconds <= self.source_start_seconds:
            raise ValueError("review reel ranges must have positive duration")
        if abs((self.reel_end_seconds - self.reel_start_seconds) - (self.source_end_seconds - self.source_start_seconds)) > 0.1:
            raise ValueError("review reel and source interval durations must match")
        return self


class ReviewReelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[ReviewReelEntry] = Field(default_factory=list, max_length=12)
    total_duration_seconds: float = Field(default=0, ge=0, le=600)

    @model_validator(mode="after")
    def validate_manifest(self) -> "ReviewReelManifest":
        cursor = 0.0
        for entry in self.entries:
            if abs(entry.reel_start_seconds - cursor) > 0.1:
                raise ValueError("review reel entries must be contiguous and ordered")
            cursor = entry.reel_end_seconds
        if abs(cursor - self.total_duration_seconds) > 0.1:
            raise ValueError("review reel total duration must match entries")
        return self


class VerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    status: RepairVerificationStatus
    approved_repair_count: int = Field(ge=1, le=10)
    resolved: list[FindingComparison] = Field(default_factory=list, max_length=200)
    remaining: list[FindingComparison] = Field(default_factory=list, max_length=200)
    new: list[FindingComparison] = Field(default_factory=list, max_length=200)
    unexpected_changes: list[UnexpectedChangeInterval] = Field(default_factory=list, max_length=200)
    original_duration_seconds: float = Field(gt=0)
    repaired_duration_seconds: float = Field(gt=0)
    expected_duration_seconds: float = Field(gt=0)
    integrity: RepairIntegrityResult
    repaired_preflight_report: PreflightReport
    regression_analysis_completeness: ScanCompleteness
    review_reel_manifest: ReviewReelManifest
    review_reel_available: bool
    limitations: list[str] = Field(default_factory=list, max_length=10)
