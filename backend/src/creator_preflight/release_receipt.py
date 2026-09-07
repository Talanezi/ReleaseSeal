"""Deterministic, artifact-bound release receipts and verification."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from creator_preflight.config import PreflightConfig
from creator_preflight.models import FindingStatus, PreflightReport, ScanCompleteness
from creator_preflight.release_contract import ContractRequirementResult, ReleaseContract
from creator_preflight.repair_models import RepairOperation
from creator_preflight.revision_check_models import AdditionalRevisionChange, RevisionCheckReport
from creator_preflight.revision_semantic_models import RevisionSemanticResult, RevisionSemanticReviewReport
from creator_preflight.verification_models import UnexpectedChangeInterval, VerificationReport


SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ReceiptKind(str, Enum):
    FINAL_EXPORT = "FINAL_EXPORT"
    REVISION = "REVISION"


class ReceiptVerificationStatus(str, Enum):
    VALID = "VALID"
    MISMATCH = "MISMATCH"
    INVALID_RECEIPT = "INVALID_RECEIPT"
    INCOMPLETE_VERIFICATION = "INCOMPLETE_VERIFICATION"


class AssetPresence(str, Enum):
    ABSENT = "ABSENT"
    PRESENT = "PRESENT"


class ArtifactIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=0)


class OptionalArtifactIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    presence: AssetPresence
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    size_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_presence(self) -> "OptionalArtifactIdentity":
        populated = self.sha256 is not None and self.size_bytes is not None
        if (self.presence is AssetPresence.PRESENT) != populated:
            raise ValueError("optional artifact presence must match its identity")
        return self


class DeterministicReceiptSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks_run: int = Field(ge=0)
    checks_passed: int = Field(ge=0)
    finding_codes: list[str] = Field(default_factory=list, max_length=1000)
    contract_passed: int = Field(ge=0)
    contract_failed: int = Field(ge=0)
    contract_not_evaluated: int = Field(ge=0)


class AdvisoryReceiptSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai_review_status: str
    opening_status: str
    continuity_status: str
    factual_status: str
    finding_codes: list[str] = Field(default_factory=list, max_length=1000)
    semantic_contract_passed: int = Field(ge=0)
    semantic_contract_needs_review: int = Field(ge=0)
    semantic_contract_not_evaluated: int = Field(ge=0)


class HumanDispositionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=100)
    disposition: Literal["PENDING", "ACCEPTED_INTENTIONAL", "NEEDS_CHANGE"]


class ContractReceiptSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    presence: AssetPresence
    contract: ReleaseContract | None = None
    canonical_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    deterministic_results_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    semantic_results_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    deterministic_results: list[ContractRequirementResult] = Field(default_factory=list, max_length=30)
    semantic_results: list[ContractRequirementResult] = Field(default_factory=list, max_length=5)
    deterministic_failed_count: int = Field(default=0, ge=0)
    semantic_needs_review_count: int = Field(default=0, ge=0)
    verdict_contribution: Literal["NONE", "BLOCKED", "NEEDS_REVIEW", "PARTIAL"] = "NONE"

    @model_validator(mode="after")
    def validate_presence(self) -> "ContractReceiptSummary":
        if self.presence is AssetPresence.ABSENT:
            if self.contract is not None or any((self.canonical_sha256, self.deterministic_results_sha256, self.semantic_results_sha256)):
                raise ValueError("absent contract cannot contain digests")
            if self.deterministic_results or self.semantic_results:
                raise ValueError("absent contract cannot contain evaluation results")
        elif not all((self.canonical_sha256, self.deterministic_results_sha256, self.semantic_results_sha256)):
            raise ValueError("present contract requires all contract digests")
        elif self.contract is None:
            raise ValueError("present contract requires the canonical contract")
        else:
            if self.canonical_sha256 != canonical_sha256(self.contract):
                raise ValueError("contract digest does not match the embedded contract")
            if self.deterministic_results_sha256 != canonical_sha256([item.model_dump(mode="json") for item in self.deterministic_results]):
                raise ValueError("deterministic contract-result digest does not match")
            if self.semantic_results_sha256 != canonical_sha256([item.model_dump(mode="json") for item in self.semantic_results]):
                raise ValueError("semantic contract-result digest does not match")
        return self


class FinalExportPackageIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipping_video: ArtifactIdentity
    shipping_role: Literal["ORIGINAL", "REPAIRED"]
    thumbnail: OptionalArtifactIdentity
    captions: OptionalArtifactIdentity
    normalized_title_sha256: str = Field(pattern=SHA256_PATTERN)
    normalized_description_sha256: str = Field(pattern=SHA256_PATTERN)
    contract: ContractReceiptSummary
    package_fingerprint_sha256: str = Field(pattern=SHA256_PATTERN)


class RepairReceiptRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_video: ArtifactIdentity
    repaired_video: ArtifactIdentity
    approved_operations: list[RepairOperation] = Field(min_length=1, max_length=10)
    verification_status: str
    repaired_rescan_verdict: FindingStatus
    repaired_rescan_completeness: ScanCompleteness
    unexpected_change_count: int = Field(ge=0)
    unexpected_changes: list[UnexpectedChangeInterval] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_relationship(self) -> "RepairReceiptRelationship":
        if self.original_video.sha256 == self.repaired_video.sha256:
            raise ValueError("a repaired artifact must differ from its original")
        ordered = sorted(self.approved_operations, key=lambda item: item.start_seconds)
        if ordered != self.approved_operations:
            raise ValueError("repair operations must be in original-timeline order")
        if self.unexpected_change_count != len(self.unexpected_changes):
            raise ValueError("unexpected-change count must match its intervals")
        return self


class FinalExportReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_schema_version: Literal["1.0"] = "1.0"
    receipt_kind: Literal[ReceiptKind.FINAL_EXPORT] = ReceiptKind.FINAL_EXPORT
    created_at: datetime
    scanner_version: str = Field(min_length=1, max_length=100)
    verdict: FindingStatus
    scan_completeness: ScanCompleteness
    configuration_fingerprint_sha256: str = Field(pattern=SHA256_PATTERN)
    deterministic_results: DeterministicReceiptSummary
    advisory_results: AdvisoryReceiptSummary
    human_dispositions: list[HumanDispositionRecord] = Field(default_factory=list, max_length=200)
    package: FinalExportPackageIdentity
    repair: RepairReceiptRelationship | None = None
    receipt_content_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receipt creation timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_repair_identity(self) -> "FinalExportReceipt":
        if self.package.shipping_role == "REPAIRED":
            if self.repair is None or self.package.shipping_video != self.repair.repaired_video:
                raise ValueError("repaired shipping identity must match the repair relationship")
        elif self.repair is not None:
            raise ValueError("an original shipping artifact cannot contain a repair relationship")
        return self


class RevisionReceiptSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unchanged_percentage: float = Field(ge=0, le=100, allow_inf_nan=False)
    requested_results: list["RevisionRequestedResult"] = Field(default_factory=list, max_length=500)
    additional_changes: list[AdditionalRevisionChange] = Field(default_factory=list, max_length=4000)


class RevisionRequestedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^request-\d{4}$")
    instruction: str = Field(min_length=1, max_length=500)
    status: str = Field(min_length=1, max_length=50)
    matched_segment_ids: list[str] = Field(default_factory=list, max_length=100)


class RevisionAdvisorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_present: bool
    results: list[RevisionSemanticResult] = Field(default_factory=list, max_length=500)


class RevisionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_schema_version: Literal["1.0"] = "1.0"
    receipt_kind: Literal[ReceiptKind.REVISION] = ReceiptKind.REVISION
    created_at: datetime
    scanner_version: str = Field(min_length=1, max_length=100)
    verdict: Literal["NOT_APPLICABLE"] = "NOT_APPLICABLE"
    scan_completeness: Literal[ScanCompleteness.COMPLETE] = ScanCompleteness.COMPLETE
    configuration_fingerprint_sha256: str = Field(pattern=SHA256_PATTERN)
    previous_video: ArtifactIdentity
    revised_video: ArtifactIdentity
    revision_notes_sha256: str = Field(pattern=SHA256_PATTERN)
    revision_fingerprint_sha256: str = Field(pattern=SHA256_PATTERN)
    deterministic_results: RevisionReceiptSummary
    advisory_results: RevisionAdvisorySummary
    human_dispositions: list[HumanDispositionRecord] = Field(default_factory=list, max_length=200)
    receipt_content_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receipt creation timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_distinct_roles(self) -> "RevisionReceipt":
        if self.previous_video.sha256 == self.revised_video.sha256:
            # Identical-file Revision checks are valid; roles remain explicit.
            return self
        return self


ReleaseReceipt = Annotated[FinalExportReceipt | RevisionReceipt, Field(discriminator="receipt_kind")]
RECEIPT_ADAPTER = TypeAdapter(ReleaseReceipt)


class ReceiptVerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReceiptVerificationStatus
    receipt_kind: ReceiptKind | None = None
    recorded_verdict: str | None = None
    recorded_completeness: str | None = None
    checks: list[str] = Field(default_factory=list, max_length=50)
    mismatches: list[str] = Field(default_factory=list, max_length=50)


def canonical_json_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_identity(path: Path) -> ArtifactIdentity:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return ArtifactIdentity(sha256=digest.hexdigest(), size_bytes=size)


def optional_file_identity(path: Path | None) -> OptionalArtifactIdentity:
    if path is None:
        return OptionalArtifactIdentity(presence=AssetPresence.ABSENT)
    identity = file_identity(path)
    return OptionalArtifactIdentity(
        presence=AssetPresence.PRESENT,
        sha256=identity.sha256,
        size_bytes=identity.size_bytes,
    )


def normalized_text_digest(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def revision_notes_digest(value: str) -> str:
    normalized_lines = [" ".join(line.split()) for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return hashlib.sha256("\n".join(normalized_lines).strip().encode("utf-8")).hexdigest()


def configuration_fingerprint(config: PreflightConfig) -> str:
    return canonical_sha256(config.model_dump(mode="json"))


def package_fingerprint(package: FinalExportPackageIdentity) -> str:
    return canonical_sha256(package.model_dump(mode="json", exclude={"package_fingerprint_sha256"}))


def revision_fingerprint(previous: ArtifactIdentity, revised: ArtifactIdentity, notes_sha256: str) -> str:
    return canonical_sha256({
        "previous": previous.model_dump(mode="json"),
        "revised": revised.model_dump(mode="json"),
        "revision_notes_sha256": notes_sha256,
    })


def build_final_export_receipt(
    *,
    shipping_video_path: Path,
    report: PreflightReport,
    config: PreflightConfig,
    title: str,
    description: str,
    thumbnail_path: Path | None = None,
    captions_path: Path | None = None,
    original_video_path: Path | None = None,
    operations: list[RepairOperation] | None = None,
    verification: VerificationReport | None = None,
    human_dispositions: list[HumanDispositionRecord] | None = None,
    created_at: datetime | None = None,
) -> FinalExportReceipt:
    shipping = file_identity(shipping_video_path)
    repaired = original_video_path is not None
    if repaired != (verification is not None and bool(operations)):
        raise ValueError("repair receipt requires original video, operations, and verification together")
    target_report = verification.repaired_preflight_report if verification else report
    if shipping.size_bytes != target_report.media.file_size_bytes:
        raise ValueError("shipping artifact size does not match the trusted scan report")
    if original_video_path is not None and file_identity(original_video_path).size_bytes != report.media.file_size_bytes:
        raise ValueError("original artifact size does not match the trusted scan report")
    if verification is not None and operations is not None and verification.approved_repair_count != len(operations):
        raise ValueError("approved repair count does not match the operations")
    disposition_rows = human_dispositions or []
    if len({item.proposal_id for item in disposition_rows}) != len(disposition_rows):
        raise ValueError("human disposition IDs must be unique")
    known_human_ids = {item.proposal_id for item in report.repair_plan.proposals if item.repairability.value == "HUMAN_ONLY"}
    if any(item.proposal_id not in known_human_ids for item in disposition_rows):
        raise ValueError("human disposition does not belong to this report")
    contract = _contract_summary(target_report)
    package = FinalExportPackageIdentity(
        shipping_video=shipping,
        shipping_role="REPAIRED" if repaired else "ORIGINAL",
        thumbnail=optional_file_identity(thumbnail_path),
        captions=optional_file_identity(captions_path),
        normalized_title_sha256=normalized_text_digest(title),
        normalized_description_sha256=normalized_text_digest(description),
        contract=contract,
        package_fingerprint_sha256="0" * 64,
    )
    package.package_fingerprint_sha256 = package_fingerprint(package)
    repair = None
    if repaired and original_video_path and verification and operations:
        repair = RepairReceiptRelationship(
            original_video=file_identity(original_video_path),
            repaired_video=shipping,
            approved_operations=sorted(operations, key=lambda item: item.start_seconds),
            verification_status=verification.status.value,
            repaired_rescan_verdict=verification.repaired_preflight_report.verdict,
            repaired_rescan_completeness=verification.repaired_preflight_report.scan_completeness,
            unexpected_change_count=len(verification.unexpected_changes),
            unexpected_changes=verification.unexpected_changes,
        )
    draft = FinalExportReceipt(
        created_at=_timestamp(created_at),
        scanner_version=_scanner_version(),
        verdict=target_report.verdict,
        scan_completeness=target_report.scan_completeness,
        configuration_fingerprint_sha256=configuration_fingerprint(config),
        deterministic_results=_deterministic_summary(target_report),
        advisory_results=_advisory_summary(target_report),
        human_dispositions=sorted(disposition_rows, key=lambda item: item.proposal_id),
        package=package,
        repair=repair,
        receipt_content_sha256="0" * 64,
    )
    draft.receipt_content_sha256 = receipt_digest(draft)
    return draft


def build_revision_receipt(
    *,
    previous_path: Path,
    revised_path: Path,
    notes: str,
    report: RevisionCheckReport,
    config: PreflightConfig,
    semantic: RevisionSemanticReviewReport | None = None,
    created_at: datetime | None = None,
) -> RevisionReceipt:
    previous = file_identity(previous_path)
    revised = file_identity(revised_path)
    if previous.sha256 != report.revision_map.previous_sha256 or revised.sha256 != report.revision_map.revised_sha256:
        raise ValueError("revision artifacts do not match the supplied deterministic report")
    notes_sha = revision_notes_digest(notes)
    draft = RevisionReceipt(
        created_at=_timestamp(created_at),
        scanner_version=_scanner_version(),
        configuration_fingerprint_sha256=configuration_fingerprint(config),
        previous_video=previous,
        revised_video=revised,
        revision_notes_sha256=notes_sha,
        revision_fingerprint_sha256=revision_fingerprint(previous, revised, notes_sha),
        deterministic_results=RevisionReceiptSummary(
            unchanged_percentage=report.revision_map.unchanged_ratio * 100,
            requested_results=[{
                "request_id": item.request_id,
                "instruction": item.text,
                "status": item.status.value,
                "matched_segment_ids": item.matched_segment_ids,
            } for item in report.revision_requests],
            additional_changes=report.additional_changes,
        ),
        advisory_results=RevisionAdvisorySummary(
            review_present=semantic is not None,
            results=semantic.results if semantic else [],
        ),
        receipt_content_sha256="0" * 64,
    )
    draft.receipt_content_sha256 = receipt_digest(draft)
    return draft


def receipt_digest(receipt: FinalExportReceipt | RevisionReceipt) -> str:
    return canonical_sha256(receipt.model_dump(mode="json", exclude={"receipt_content_sha256"}))


class ReceiptVerifier:
    def verify(
        self,
        receipt_data: bytes | str | dict,
        *,
        video_path: Path | None = None,
        thumbnail_path: Path | None = None,
        captions_path: Path | None = None,
        title: str | None = None,
        description: str | None = None,
        contract: ReleaseContract | None = None,
        previous_path: Path | None = None,
        revised_path: Path | None = None,
        revision_notes: str | None = None,
    ) -> ReceiptVerificationResult:
        try:
            raw = json.loads(receipt_data) if isinstance(receipt_data, (bytes, str)) else receipt_data
            receipt = RECEIPT_ADAPTER.validate_python(raw)
        except (ValueError, TypeError, json.JSONDecodeError):
            return ReceiptVerificationResult(status=ReceiptVerificationStatus.INVALID_RECEIPT, mismatches=["Receipt schema is invalid."])
        base = dict(
            receipt_kind=ReceiptKind(receipt.receipt_kind),
            recorded_verdict=receipt.verdict.value if isinstance(receipt.verdict, Enum) else receipt.verdict,
            recorded_completeness=receipt.scan_completeness.value if isinstance(receipt.scan_completeness, Enum) else receipt.scan_completeness,
        )
        if receipt_digest(receipt) != receipt.receipt_content_sha256:
            return ReceiptVerificationResult(status=ReceiptVerificationStatus.INVALID_RECEIPT, mismatches=["Receipt content digest does not match."], **base)
        if isinstance(receipt, FinalExportReceipt):
            return self._verify_final(receipt, video_path, thumbnail_path, captions_path, title, description, contract, base)
        return self._verify_revision(receipt, previous_path or video_path, revised_path, revision_notes, base)

    def _verify_final(self, receipt, video_path, thumbnail_path, captions_path, title, description, contract, base):
        mismatches: list[str] = []
        checks = ["Receipt content digest matches."]
        if package_fingerprint(receipt.package) != receipt.package.package_fingerprint_sha256:
            return ReceiptVerificationResult(status=ReceiptVerificationStatus.INVALID_RECEIPT, mismatches=["Package fingerprint is internally inconsistent."], **base)
        checks.append("Package fingerprint matches the recorded package.")
        if video_path is None:
            return ReceiptVerificationResult(status=ReceiptVerificationStatus.INCOMPLETE_VERIFICATION, checks=checks, mismatches=["A final video was not supplied."], **base)
        _compare_identity("Video", file_identity(video_path), receipt.package.shipping_video, mismatches, checks)
        _compare_optional("Thumbnail", thumbnail_path, receipt.package.thumbnail, mismatches, checks)
        _compare_optional("Captions", captions_path, receipt.package.captions, mismatches, checks)
        if title is not None and normalized_text_digest(title) != receipt.package.normalized_title_sha256:
            mismatches.append("Title does not match this receipt.")
        elif title is not None:
            checks.append("Title matches.")
        if description is not None and normalized_text_digest(description) != receipt.package.normalized_description_sha256:
            mismatches.append("Description does not match this receipt.")
        elif description is not None:
            checks.append("Description matches.")
        if contract is not None:
            expected = canonical_sha256(contract)
            if receipt.package.contract.canonical_sha256 != expected:
                mismatches.append("Release Contract does not match this receipt.")
            else:
                checks.append("Release Contract matches.")
        if receipt.repair and receipt.package.shipping_video != receipt.repair.repaired_video:
            return ReceiptVerificationResult(status=ReceiptVerificationStatus.INVALID_RECEIPT, mismatches=["Original and repaired artifact roles are inconsistent."], **base)
        return ReceiptVerificationResult(status=ReceiptVerificationStatus.MISMATCH if mismatches else ReceiptVerificationStatus.VALID, checks=checks, mismatches=mismatches, **base)

    def _verify_revision(self, receipt, previous_path, revised_path, notes, base):
        mismatches: list[str] = []
        checks = ["Receipt content digest matches."]
        expected_fp = revision_fingerprint(receipt.previous_video, receipt.revised_video, receipt.revision_notes_sha256)
        if expected_fp != receipt.revision_fingerprint_sha256:
            return ReceiptVerificationResult(status=ReceiptVerificationStatus.INVALID_RECEIPT, mismatches=["Revision fingerprint is internally inconsistent."], **base)
        if previous_path is None:
            return ReceiptVerificationResult(status=ReceiptVerificationStatus.INCOMPLETE_VERIFICATION, checks=checks, mismatches=["A Previous video was not supplied."], **base)
        _compare_identity("Previous video", file_identity(previous_path), receipt.previous_video, mismatches, checks)
        if revised_path is not None:
            _compare_identity("Revised video", file_identity(revised_path), receipt.revised_video, mismatches, checks)
        if notes is not None:
            if revision_notes_digest(notes) != receipt.revision_notes_sha256:
                mismatches.append("Revision notes do not match this receipt.")
            else:
                checks.append("Revision notes match.")
        return ReceiptVerificationResult(status=ReceiptVerificationStatus.MISMATCH if mismatches else ReceiptVerificationStatus.VALID, checks=checks, mismatches=mismatches, **base)


def _contract_summary(report: PreflightReport) -> ContractReceiptSummary:
    evaluation = report.release_contract
    if evaluation.contract is None:
        return ContractReceiptSummary(presence=AssetPresence.ABSENT)
    deterministic = [item.model_dump(mode="json") for item in evaluation.results if item.evaluation_class.value == "DETERMINISTIC"]
    semantic = [item.model_dump(mode="json") for item in evaluation.results if item.evaluation_class.value == "SEMANTIC"]
    contribution = "BLOCKED" if evaluation.failed_count else "NEEDS_REVIEW" if evaluation.needs_review_count else "PARTIAL" if evaluation.not_evaluated_count else "NONE"
    return ContractReceiptSummary(
        presence=AssetPresence.PRESENT,
        contract=evaluation.contract,
        canonical_sha256=canonical_sha256(evaluation.contract),
        deterministic_results_sha256=canonical_sha256(deterministic),
        semantic_results_sha256=canonical_sha256(semantic),
        deterministic_results=[item for item in evaluation.results if item.evaluation_class.value == "DETERMINISTIC"],
        semantic_results=[item for item in evaluation.results if item.evaluation_class.value == "SEMANTIC"],
        deterministic_failed_count=sum(item.status.value == "FAIL" for item in evaluation.results if item.evaluation_class.value == "DETERMINISTIC"),
        semantic_needs_review_count=sum(item.status.value == "NEEDS_REVIEW" for item in evaluation.results if item.evaluation_class.value == "SEMANTIC"),
        verdict_contribution=contribution,
    )


def _deterministic_summary(report: PreflightReport) -> DeterministicReceiptSummary:
    deterministic_findings = [item.code for item in report.findings if not _is_advisory_source(item.source)]
    rows = [item for item in report.release_contract.results if item.evaluation_class.value == "DETERMINISTIC"]
    return DeterministicReceiptSummary(
        checks_run=report.checks_run_count,
        checks_passed=report.passed_check_count,
        finding_codes=deterministic_findings,
        contract_passed=sum(item.status.value == "PASS" for item in rows),
        contract_failed=sum(item.status.value == "FAIL" for item in rows),
        contract_not_evaluated=sum(item.status.value == "NOT_EVALUATED" for item in rows),
    )


def _advisory_summary(report: PreflightReport) -> AdvisoryReceiptSummary:
    rows = [item for item in report.release_contract.results if item.evaluation_class.value == "SEMANTIC"]
    return AdvisoryReceiptSummary(
        ai_review_status=report.ai_review.status.value,
        opening_status=report.promise_check.status.value,
        continuity_status=report.viewer_pass.status.value,
        factual_status=report.claim_review.status.value,
        finding_codes=[item.code for item in report.findings if _is_advisory_source(item.source)],
        semantic_contract_passed=sum(item.status.value == "PASS" for item in rows),
        semantic_contract_needs_review=sum(item.status.value == "NEEDS_REVIEW" for item in rows),
        semantic_contract_not_evaluated=sum(item.status.value == "NOT_EVALUATED" for item in rows),
    )


def _is_advisory_source(source: str) -> bool:
    return source.startswith("ai.") or source == "release_contract.semantic"


def _compare_identity(label: str, actual: ArtifactIdentity, expected: ArtifactIdentity, mismatches: list[str], checks: list[str]) -> None:
    if actual != expected:
        mismatches.append(f"{label} hash or size does not match this receipt.")
    else:
        checks.append(f"{label} hash matches.")


def _compare_optional(label: str, path: Path | None, expected: OptionalArtifactIdentity, mismatches: list[str], checks: list[str]) -> None:
    if path is None:
        return
    if expected.presence is AssetPresence.ABSENT:
        mismatches.append(f"{label} was supplied but the receipt records it as absent.")
        return
    actual = file_identity(path)
    if actual.sha256 != expected.sha256 or actual.size_bytes != expected.size_bytes:
        mismatches.append(f"{label} does not match this receipt.")
    else:
        checks.append(f"{label} matches.")


def _timestamp(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("receipt creation timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def _scanner_version() -> str:
    try:
        return version("creator-preflight")
    except PackageNotFoundError:
        return "0.0.0"
