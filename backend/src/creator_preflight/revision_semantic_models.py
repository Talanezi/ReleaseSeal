"""Strict contracts for optional semantic review of deterministic revision evidence."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RevisionSemanticStatus(str, Enum):
    APPEARS_SATISFIED = "APPEARS_SATISFIED"
    APPEARS_UNRESOLVED = "APPEARS_UNRESOLVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_REVIEWED = "NOT_REVIEWED"


class RevisionSemanticProviderOutput(BaseModel):
    """Untrusted structured provider output for one revision request."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: RevisionSemanticStatus
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    rationale: str = Field(min_length=1, max_length=600)
    observed_previous: str = Field(min_length=1, max_length=400)
    observed_revised: str = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def provider_cannot_return_not_reviewed(self) -> "RevisionSemanticProviderOutput":
        if self.status is RevisionSemanticStatus.NOT_REVIEWED:
            raise ValueError("provider cannot return NOT_REVIEWED")
        return self


class RevisionEvidenceRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_order(self) -> "RevisionEvidenceRange":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("evidence range must have positive duration")
        return self


class RevisionSemanticResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^request-\d{4}$")
    status: RevisionSemanticStatus
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    rationale: str = Field(min_length=1, max_length=600)
    observed_previous: str | None = Field(default=None, max_length=400)
    observed_revised: str | None = Field(default=None, max_length=400)
    reviewed_previous_range: RevisionEvidenceRange | None = None
    reviewed_revised_range: RevisionEvidenceRange | None = None
    partial_evidence: bool = False
    limitation: str | None = Field(default=None, max_length=300)
    reason_code: str | None = Field(default=None, max_length=100)


class RevisionSemanticReviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    provider: str
    model: str
    eligible_count: int = Field(ge=0)
    requested_count: int = Field(ge=0)
    reviewed_count: int = Field(ge=0)
    appears_satisfied_count: int = Field(ge=0)
    appears_unresolved_count: int = Field(ge=0)
    inconclusive_count: int = Field(ge=0)
    not_reviewed_count: int = Field(ge=0)
    results: list[RevisionSemanticResult] = Field(default_factory=list, max_length=500)
    evidence_render_seconds: float = Field(ge=0, allow_inf_nan=False)
    provider_seconds: float = Field(ge=0, allow_inf_nan=False)
    total_seconds: float = Field(ge=0, allow_inf_nan=False)
    upload_count: int = Field(ge=0)
    generation_count: int = Field(ge=0)
    delete_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "RevisionSemanticReviewReport":
        statuses = [item.status for item in self.results]
        expected = {
            "appears_satisfied_count": statuses.count(RevisionSemanticStatus.APPEARS_SATISFIED),
            "appears_unresolved_count": statuses.count(RevisionSemanticStatus.APPEARS_UNRESOLVED),
            "inconclusive_count": statuses.count(RevisionSemanticStatus.INCONCLUSIVE),
            "not_reviewed_count": statuses.count(RevisionSemanticStatus.NOT_REVIEWED),
        }
        for field, count in expected.items():
            if getattr(self, field) != count:
                raise ValueError(f"{field} is inconsistent")
        if self.reviewed_count != len(self.results) - self.not_reviewed_count:
            raise ValueError("reviewed_count is inconsistent")
        if self.requested_count != len(self.results):
            raise ValueError("requested_count is inconsistent")
        return self
