"""Strict contracts for deterministic previous-cut Revision Check reports."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from creator_preflight.revision_models import RevisionMap, RevisionSegmentKind


class RevisionRequestStatus(str, Enum):
    CHANGE_DETECTED = "CHANGE_DETECTED"
    NO_CHANGE_DETECTED = "NO_CHANGE_DETECTED"
    NEEDS_LOCATION = "NEEDS_LOCATION"


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^request-\d{4}$")
    source_line: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=500)
    previous_start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    previous_end_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    explicit_range: bool = False
    status: RevisionRequestStatus
    matched_segment_ids: list[str] = Field(default_factory=list, max_length=100)
    evidence: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_location(self) -> "RevisionRequest":
        located = self.previous_start_seconds is not None
        if located != (self.previous_end_seconds is not None):
            raise ValueError("revision request requires both timeline bounds")
        if located and self.previous_end_seconds < self.previous_start_seconds:
            raise ValueError("revision request range is reversed")
        if self.status is RevisionRequestStatus.NEEDS_LOCATION and located:
            raise ValueError("located request cannot need a location")
        if self.status is not RevisionRequestStatus.NEEDS_LOCATION and not located:
            raise ValueError("evaluated request requires a location")
        return self


class AdditionalRevisionChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(pattern=r"^segment-\d{4}$")
    kind: RevisionSegmentKind
    previous_start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    previous_end_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    revised_start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    revised_end_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    visual_changed: bool
    audio_changed: bool
    boundary_confidence: str = Field(pattern=r"^(high|approximate|ambiguous)$")


class RevisionCheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    previous_filename: str = Field(min_length=1, max_length=500)
    revised_filename: str = Field(min_length=1, max_length=500)
    revision_map: RevisionMap
    revision_requests: list[RevisionRequest] = Field(default_factory=list, max_length=500)
    requested_change_count: int = Field(ge=0)
    requested_changes_detected_count: int = Field(ge=0)
    requested_changes_not_detected_count: int = Field(ge=0)
    requests_needing_location_count: int = Field(ge=0)
    additional_changes: list[AdditionalRevisionChange] = Field(default_factory=list, max_length=4000)
    additional_change_count: int = Field(ge=0)
    analysis_runtime_seconds: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_counts(self) -> "RevisionCheckReport":
        statuses = [request.status for request in self.revision_requests]
        if self.requested_change_count != len(self.revision_requests):
            raise ValueError("requested change count is inconsistent")
        if self.requested_changes_detected_count != statuses.count(RevisionRequestStatus.CHANGE_DETECTED):
            raise ValueError("detected request count is inconsistent")
        if self.requested_changes_not_detected_count != statuses.count(RevisionRequestStatus.NO_CHANGE_DETECTED):
            raise ValueError("unchanged request count is inconsistent")
        if self.requests_needing_location_count != statuses.count(RevisionRequestStatus.NEEDS_LOCATION):
            raise ValueError("unlocated request count is inconsistent")
        if self.additional_change_count != len(self.additional_changes):
            raise ValueError("additional change count is inconsistent")
        return self
