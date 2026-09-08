"""Strict repair contracts shared by planning, rendering, API, and reports."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class Repairability(str, Enum):
    SAFE = "SAFE"
    PREVIEW_REQUIRED = "PREVIEW_REQUIRED"
    HUMAN_ONLY = "HUMAN_ONLY"


class RepairOperationType(str, Enum):
    REMOVE_RANGE = "REMOVE_RANGE"


class RepairOperation(BaseModel):
    """One backend-supported edit expressed in original-timeline coordinates."""

    model_config = ConfigDict(extra="forbid")

    operation_type: RepairOperationType
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_range(self) -> "RepairOperation":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class RepairOperationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[RepairOperation] = Field(min_length=1, max_length=10)


class RepairProposal(BaseModel):
    """Deterministic explanation of what ReleaseSeal can safely offer."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=100)
    finding_code: str = Field(min_length=1, max_length=100)
    finding_title: str = Field(min_length=1, max_length=300)
    explanation: str = Field(min_length=1, max_length=1000)
    source: str = Field(min_length=1, max_length=200)
    repairability: Repairability
    operation: RepairOperation | None = None
    start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    end_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    expected_duration_change_seconds: float | None = Field(
        default=None, le=0, allow_inf_nan=False
    )
    original_start_seconds: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    original_end_seconds: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    evidence: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_proposal(self) -> "RepairProposal":
        if self.repairability is Repairability.HUMAN_ONLY:
            if self.operation is not None or self.expected_duration_change_seconds is not None:
                raise ValueError("human-only proposals cannot contain an operation")
        elif self.operation is None:
            raise ValueError("repairable proposals require an operation")
        if self.operation is not None and (
            self.start_seconds != self.operation.start_seconds
            or self.end_seconds != self.operation.end_seconds
        ):
            raise ValueError("proposal timestamps must match its operation")
        if (self.original_start_seconds is None) != (self.original_end_seconds is None):
            raise ValueError("reference interval requires both timestamps")
        if (
            self.original_start_seconds is not None
            and self.original_end_seconds is not None
            and self.original_end_seconds <= self.original_start_seconds
        ):
            raise ValueError("reference interval end must be greater than its start")
        return self


class RepairPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposals: list[RepairProposal] = Field(default_factory=list, max_length=200)
    safe_count: int = Field(default=0, ge=0)
    preview_required_count: int = Field(default=0, ge=0)
    human_only_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "RepairPlan":
        expected = {
            Repairability.SAFE: self.safe_count,
            Repairability.PREVIEW_REQUIRED: self.preview_required_count,
            Repairability.HUMAN_ONLY: self.human_only_count,
        }
        if len({proposal.proposal_id for proposal in self.proposals}) != len(self.proposals):
            raise ValueError("repair proposal IDs must be unique")
        for repairability, count in expected.items():
            if count != sum(item.repairability is repairability for item in self.proposals):
                raise ValueError("repair plan counts must match proposals")
        return self
