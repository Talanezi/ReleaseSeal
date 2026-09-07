"""Strict portable evidence bundle generated from production services."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from creator_preflight.models import PreflightReport
from creator_preflight.release_contract import ReleaseContract
from creator_preflight.release_receipt import (
    FinalExportReceipt,
    ReceiptVerificationResult,
    RevisionReceipt,
)
from creator_preflight.repair_models import RepairOperation
from creator_preflight.revision_check_models import RevisionCheckReport
from creator_preflight.verification_models import VerificationReport


class ProofArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_path: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    mime_type: str = Field(min_length=1, max_length=100)

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("proof artifact path must be relative and contained")
        return value


class ProofProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["public_domain", "generated_control"]
    source_credit: str
    source_title: str
    source_url: str | None = None
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_demo_generator_version: str | None = None


class FinalExportProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_origin: Literal["GENERATED_FROM_ENGINE"] = "GENERATED_FROM_ENGINE"
    original_video: ProofArtifact
    repaired_video: ProofArtifact
    thumbnail: ProofArtifact
    title: str
    description: str
    original_report: PreflightReport
    repair_operation: RepairOperation
    verification: VerificationReport
    receipt: FinalExportReceipt
    receipt_valid: ReceiptVerificationResult
    receipt_mutated_artifact: ReceiptVerificationResult


class ContractProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_origin: Literal["GENERATED_FROM_ENGINE"] = "GENERATED_FROM_ENGINE"
    provenance: ProofProvenance
    video: ProofArtifact
    captions: ProofArtifact
    title: str
    description: str
    contract: ReleaseContract
    report: PreflightReport


class RevisionProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_origin: Literal["GENERATED_FROM_ENGINE"] = "GENERATED_FROM_ENGINE"
    previous_video: ProofArtifact
    revised_video: ProofArtifact
    notes: str
    report: RevisionCheckReport
    receipt: RevisionReceipt
    receipt_valid: ReceiptVerificationResult


class JudgeProofBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    generator_version: Literal["1"] = "1"
    generation_origin: Literal["GENERATED_FROM_ENGINE"] = "GENERATED_FROM_ENGINE"
    generated_at: datetime
    provenance: ProofProvenance
    final_export: FinalExportProof
    release_contract: ContractProof
    revision: RevisionProof


def artifact(path: Path, *, root: Path, mime_type: str) -> ProofArtifact:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return ProofArtifact(
        relative_path=path.relative_to(root).as_posix(),
        sha256=digest.hexdigest(),
        size_bytes=size,
        mime_type=mime_type,
    )


def proof_artifacts(bundle: JudgeProofBundle) -> list[ProofArtifact]:
    return [
        bundle.final_export.original_video,
        bundle.final_export.repaired_video,
        bundle.final_export.thumbnail,
        bundle.release_contract.video,
        bundle.release_contract.captions,
        bundle.revision.previous_video,
        bundle.revision.revised_video,
    ]
