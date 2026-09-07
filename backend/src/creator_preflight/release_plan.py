"""Deterministic next-action categories over already trusted report state."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from creator_preflight.release_contract import ContractStatus, EvaluationClass, ReleaseContractEvaluation
from creator_preflight.release_evidence import AudioEvidenceState


class ReleasePlanCategory(str, Enum):
    BLOCKING_REQUIREMENT = "BLOCKING_REQUIREMENT"
    SAFE_AUTOMATION = "SAFE_AUTOMATION"
    CONFIRM_EVIDENCE = "CONFIRM_EVIDENCE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    INFORMATIONAL = "INFORMATIONAL"


class ReleasePlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    item_id: str = Field(min_length=1, max_length=140)
    category: ReleasePlanCategory
    title: str = Field(min_length=1, max_length=300)
    reference_id: str | None = Field(default=None, max_length=100)
    timestamp_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ReleasePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReleasePlanItem] = Field(default_factory=list, max_length=500)
    blocking_requirement_count: int = Field(default=0, ge=0)
    safe_automation_count: int = Field(default=0, ge=0)
    confirm_evidence_count: int = Field(default=0, ge=0)
    human_review_count: int = Field(default=0, ge=0)
    informational_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def counts_match(self) -> "ReleasePlan":
        mapping = {
            "blocking_requirement_count": ReleasePlanCategory.BLOCKING_REQUIREMENT,
            "safe_automation_count": ReleasePlanCategory.SAFE_AUTOMATION,
            "confirm_evidence_count": ReleasePlanCategory.CONFIRM_EVIDENCE,
            "human_review_count": ReleasePlanCategory.HUMAN_REVIEW,
            "informational_count": ReleasePlanCategory.INFORMATIONAL,
        }
        for field, category in mapping.items():
            if getattr(self, field) != sum(item.category is category for item in self.items):
                raise ValueError(f"{field} is inconsistent")
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("release plan item ids must be unique")
        return self


def build_release_plan(
    *,
    contract: ReleaseContractEvaluation,
    repair_plan: Any,
    audio_evidence: AudioEvidenceState,
) -> ReleasePlan:
    """Categorize next actions without changing their underlying truth or authority."""

    items: list[ReleasePlanItem] = []
    confirmed = {item.requirement_id for item in audio_evidence.confirmations}
    candidate_requirements = {item.requirement_id for item in audio_evidence.candidates}
    for result in contract.results:
        if result.status is ContractStatus.FAIL and result.evaluation_class is EvaluationClass.DETERMINISTIC:
            category = ReleasePlanCategory.BLOCKING_REQUIREMENT
        elif result.status is ContractStatus.NEEDS_REVIEW and result.requirement_id not in candidate_requirements:
            category = ReleasePlanCategory.HUMAN_REVIEW
        elif result.status is ContractStatus.NOT_EVALUATED:
            category = (
                ReleasePlanCategory.HUMAN_REVIEW
                if result.evaluation_class is EvaluationClass.SEMANTIC
                else ReleasePlanCategory.INFORMATIONAL
            )
        else:
            continue
        items.append(ReleasePlanItem(
            item_id=f"requirement-{result.requirement_id}", category=category,
            title=result.instruction, reference_id=result.requirement_id,
            timestamp_seconds=result.timestamp_seconds,
        ))
    for proposal in repair_plan.proposals:
        if proposal.finding_code.startswith("RELEASE_CONTRACT_"):
            continue
        if proposal.operation is not None:
            category = (
                ReleasePlanCategory.SAFE_AUTOMATION
                if proposal.repairability.value == "SAFE"
                else ReleasePlanCategory.HUMAN_REVIEW
            )
        elif proposal.repairability.value == "HUMAN_ONLY":
            category = ReleasePlanCategory.HUMAN_REVIEW
        else:
            continue
        items.append(ReleasePlanItem(
            item_id=f"repair-{proposal.proposal_id}", category=category,
            title=proposal.finding_title, reference_id=proposal.proposal_id,
            timestamp_seconds=proposal.start_seconds,
        ))
    for candidate in audio_evidence.candidates:
        if candidate.requirement_id in confirmed:
            continue
        items.append(ReleasePlanItem(
            item_id=f"evidence-{candidate.candidate_id}",
            category=ReleasePlanCategory.CONFIRM_EVIDENCE,
            title=f"Confirm audio evidence for {candidate.expected_value}",
            reference_id=candidate.candidate_id,
            timestamp_seconds=candidate.start_seconds,
        ))
    order = {category: index for index, category in enumerate(ReleasePlanCategory)}
    items.sort(key=lambda item: (order[item.category], item.timestamp_seconds is None, item.timestamp_seconds or 0, item.item_id))
    return ReleasePlan(
        items=items,
        blocking_requirement_count=sum(item.category is ReleasePlanCategory.BLOCKING_REQUIREMENT for item in items),
        safe_automation_count=sum(item.category is ReleasePlanCategory.SAFE_AUTOMATION for item in items),
        confirm_evidence_count=sum(item.category is ReleasePlanCategory.CONFIRM_EVIDENCE for item in items),
        human_review_count=sum(item.category is ReleasePlanCategory.HUMAN_REVIEW for item in items),
        informational_count=sum(item.category is ReleasePlanCategory.INFORMATIONAL for item in items),
    )
