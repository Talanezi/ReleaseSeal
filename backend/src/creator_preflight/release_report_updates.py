"""Rebuild report truth after bounded Release Contract evidence updates."""

from __future__ import annotations

from creator_preflight.engine import finding_sort_key, reconcile_findings
from creator_preflight.models import CheckResult, ExecutionIssue, FindingStatus, PreflightReport, ScanCompleteness
from creator_preflight.release_brief import deterministic_release_brief
from creator_preflight.release_contract import ContractStatus, ReleaseContractEvaluation, contract_findings
from creator_preflight.release_evidence import AudioEvidenceState
from creator_preflight.release_plan import build_release_plan
from creator_preflight.repairs import build_repair_plan


def with_contract_evidence(
    report: PreflightReport,
    *,
    evaluation: ReleaseContractEvaluation,
    audio_evidence: AudioEvidenceState,
) -> PreflightReport:
    """Apply backend-evaluated evidence without rerunning unrelated analysis."""

    non_contract_findings = [
        finding for finding in report.findings
        if not finding.source.startswith("release_contract.")
    ]
    findings = reconcile_findings([*non_contract_findings, *contract_findings(evaluation)])
    findings.sort(key=finding_sort_key)
    checks = [check for check in report.checks if not check.check_id.startswith("release_contract.")]
    checks.extend(
        CheckResult(
            check_id=f"release_contract.{item.requirement_id}",
            passed=item.status is ContractStatus.PASS,
            finding_codes=[f"RELEASE_CONTRACT_{item.requirement_id.upper()}"]
            if item.status in {ContractStatus.FAIL, ContractStatus.NEEDS_REVIEW} else [],
        )
        for item in evaluation.results
    )
    incomplete = [item for item in evaluation.results if item.status is ContractStatus.NOT_EVALUATED]
    issues = [issue for issue in report.execution_issues if issue.component != "release_contract"]
    if incomplete:
        issues.append(ExecutionIssue(
            component="release_contract",
            reason_code="release_contract_not_evaluated",
            message=f"{len(incomplete)} release requirement(s) could not be evaluated from the available evidence.",
        ))
    warning_count = sum(item.status is FindingStatus.NEEDS_REVIEW for item in findings)
    critical_count = sum(item.status is FindingStatus.BLOCKED for item in findings)
    verdict = (
        FindingStatus.BLOCKED if critical_count else
        FindingStatus.NEEDS_REVIEW if warning_count else FindingStatus.READY
    )
    completeness = ScanCompleteness.PARTIAL if issues else ScanCompleteness.COMPLETE
    repair_plan = build_repair_plan(findings)
    release_plan = build_release_plan(
        contract=evaluation, repair_plan=repair_plan, audio_evidence=audio_evidence
    )
    brief = deterministic_release_brief(
        verdict=verdict,
        completeness=completeness,
        findings=findings,
        inconclusive_claim_count=report.claim_review.insufficient_evidence_count,
        repair_plan=repair_plan,
        promise_check=report.promise_check,
        viewer_pass=report.viewer_pass,
        claim_review=report.claim_review,
    )
    return report.model_copy(update={
        "verdict": verdict,
        "scan_completeness": completeness,
        "execution_issues": issues,
        "findings": findings,
        "checks": checks,
        "checks_run_count": len(checks),
        "passed_check_count": sum(check.passed for check in checks),
        "warning_count": warning_count,
        "critical_count": critical_count,
        "release_contract": evaluation,
        "audio_evidence": audio_evidence,
        "repair_plan": repair_plan,
        "release_plan": release_plan,
        "release_brief": brief,
    })
