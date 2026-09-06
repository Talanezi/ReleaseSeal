"""Concise presentation summaries derived only from trusted report state."""

from __future__ import annotations

from creator_preflight.ai_review import AIReviewError, GeminiReviewSession
from creator_preflight.models import Finding, FindingStatus, ScanCompleteness
from creator_preflight.repair_models import RepairPlan
from creator_preflight.release_models import ReleaseBrief, ReleaseBriefDraft, ReleaseBriefSource


def deterministic_release_brief(
    *,
    verdict: FindingStatus,
    completeness: ScanCompleteness,
    findings: list[Finding],
    inconclusive_claim_count: int = 0,
    source: ReleaseBriefSource = ReleaseBriefSource.DETERMINISTIC,
) -> ReleaseBrief:
    actionable = [finding for finding in findings if finding.status is not FindingStatus.READY]
    if verdict is FindingStatus.BLOCKED:
        headline = "Publishing is blocked"
    elif actionable:
        headline = f"{len(actionable)} {('item needs' if len(actionable) == 1 else 'items need')} attention"
    else:
        headline = "No release issues found"
    if completeness is not ScanCompleteness.COMPLETE:
        summary = "Completed checks are shown below, but part of the requested review did not finish."
    elif actionable:
        summary = "Review the most important items below before publishing."
    elif inconclusive_claim_count:
        noun = "claim" if inconclusive_claim_count == 1 else "claims"
        summary = f"No issues were found. {inconclusive_claim_count} factual {noun} could not be verified with enough evidence."
    else:
        summary = "The completed checks found no issue that needs action."
    return ReleaseBrief(
        source=source,
        headline=headline,
        summary=summary,
        top_actions=[_action_text(finding) for finding in actionable[:3]],
        positive_note=("No release issue was detected in the completed checks." if not actionable and completeness is ScanCompleteness.COMPLETE else None),
    )


def ai_release_brief(
    session: GeminiReviewSession,
    *,
    verdict: FindingStatus,
    completeness: ScanCompleteness,
    findings: list[Finding],
    repair_plan: RepairPlan,
    inconclusive_claim_count: int = 0,
) -> ReleaseBrief:
    fallback = deterministic_release_brief(
        verdict=verdict,
        completeness=completeness,
        findings=findings,
        inconclusive_claim_count=inconclusive_claim_count,
        source=ReleaseBriefSource.FALLBACK,
    )
    allowed = {finding.code: _action_text(finding) for finding in findings}
    repairability = {
        (proposal.finding_code, proposal.start_seconds, proposal.end_seconds): proposal.repairability.value
        for proposal in repair_plan.proposals
    }
    facts = {
        "content_verdict": verdict.value,
        "scan_completeness": completeness.value,
        "findings": [
            {
                "code": finding.code,
                "title": str((finding.details or {}).get("title") or finding.code),
                "message": finding.message,
                "start_seconds": finding.timestamp_start_seconds,
                "end_seconds": finding.timestamp_end_seconds,
                "repairability": repairability.get((finding.code, finding.timestamp_start_seconds, finding.timestamp_end_seconds)),
            }
            for finding in findings[:20]
        ],
        "inconclusive_factual_claims": inconclusive_claim_count,
    }
    prompt = (
        "Write an AI review of the REVIEW RESULTS using only the trusted JSON-like facts below. "
        "Do not summarize what the creator's video is about. Explain relationships between supplied "
        "findings when their intervals overlap, identify what can be repaired versus what needs human "
        "judgment, and recommend the best place to start. Use no more than three short paragraphs. "
        "If inconclusive_factual_claims is greater than zero, state briefly that those claims could not "
        "be verified with enough evidence; do not imply every factual claim was supported or conclusively verified. "
        "Do not invent findings, times, repairs, sources, or verification claims. "
        "Return at most three top_action_codes chosen exactly from supplied finding codes. "
        "Use plain creator-facing language and no markdown. Facts: " + repr(facts)
    )
    try:
        result = session.generate_text_structured(
            prompt=prompt,
            response_model=ReleaseBriefDraft,
        )
        if any(code not in allowed for code in result.output.top_action_codes):
            raise AIReviewError("ai_provider_response_invalid", "AI release brief referenced an unknown finding.")
        combined_copy = " ".join(filter(None, [result.output.headline, result.output.summary, result.output.positive_note])).lower()
        if inconclusive_claim_count and any(phrase in combined_copy for phrase in (
            "everything verified", "all claims supported", "fully verified", "every claim was verified",
        )):
            raise AIReviewError("ai_provider_response_invalid", "AI release brief overstated factual verification.")
        factual_note = None
        if inconclusive_claim_count:
            noun = "claim" if inconclusive_claim_count == 1 else "claims"
            factual_note = f"{inconclusive_claim_count} factual {noun} could not be verified with enough evidence."
        return ReleaseBrief(
            source=ReleaseBriefSource.AI,
            headline=result.output.headline,
            summary=result.output.summary,
            top_actions=[allowed[code] for code in result.output.top_action_codes],
            positive_note=factual_note or result.output.positive_note,
        )
    except AIReviewError:
        return fallback


def _action_text(finding: Finding) -> str:
    title = str((finding.details or {}).get("title") or finding.code)
    if finding.timestamp_start_seconds is None:
        return title[:200]
    minutes, seconds = divmod(finding.timestamp_start_seconds, 60)
    return f"{title} at {int(minutes):02d}:{seconds:05.2f}"[:200]
