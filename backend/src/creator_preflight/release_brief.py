"""Concise presentation summaries derived only from trusted report state."""

from __future__ import annotations

import re

from creator_preflight.ai_review import AIReviewError, GeminiReviewSession
from creator_preflight.models import (
    ClaimReviewStatus,
    ClaimReviewSummary,
    Finding,
    FindingStatus,
    PromiseCheckStatus,
    PromiseCheckSummary,
    ScanCompleteness,
    ViewerPassStatus,
    ViewerPassSummary,
)
from creator_preflight.repair_models import RepairPlan
from creator_preflight.release_models import ReleaseBrief, ReleaseBriefDraft, ReleaseBriefSource
from creator_preflight.presentation import format_timecode_interval


_RAW_FLOAT_SECONDS = re.compile(r"\b\d+\.\d{3,}\s+seconds?\b", re.IGNORECASE)


def deterministic_release_brief(
    *,
    verdict: FindingStatus,
    completeness: ScanCompleteness,
    findings: list[Finding],
    inconclusive_claim_count: int = 0,
    repair_plan: RepairPlan | None = None,
    promise_check: PromiseCheckSummary | None = None,
    viewer_pass: ViewerPassSummary | None = None,
    claim_review: ClaimReviewSummary | None = None,
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
        summary = _synthesized_summary(
            actionable,
            repair_plan,
            promise_check,
            viewer_pass,
            claim_review,
        )
    elif inconclusive_claim_count:
        noun = "claim" if inconclusive_claim_count == 1 else "claims"
        summary = f"No issues were found. {inconclusive_claim_count} factual {noun} could not be verified with enough evidence."
    else:
        summary = "The completed checks found no issue that needs action."
    return ReleaseBrief(
        source=source,
        headline=headline,
        summary=summary,
        top_actions=_prioritized_actions(actionable, repair_plan),
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
    promise_check: PromiseCheckSummary | None = None,
    viewer_pass: ViewerPassSummary | None = None,
    claim_review: ClaimReviewSummary | None = None,
) -> ReleaseBrief:
    fallback = deterministic_release_brief(
        verdict=verdict,
        completeness=completeness,
        findings=findings,
        inconclusive_claim_count=inconclusive_claim_count,
        repair_plan=repair_plan,
        promise_check=promise_check,
        viewer_pass=viewer_pass,
        claim_review=claim_review,
        source=ReleaseBriefSource.FALLBACK,
    )
    groups = _finding_groups(findings)
    allowed = {
        code: _group_action(group, repair_plan)
        for code, group in groups.items()
    }
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
                "timecode": (
                    format_timecode_interval(
                        finding.timestamp_start_seconds,
                        finding.timestamp_end_seconds,
                    )
                    if finding.timestamp_start_seconds is not None
                    else None
                ),
                "repairability": repairability.get((finding.code, finding.timestamp_start_seconds, finding.timestamp_end_seconds)),
            }
            for finding in findings[:20]
        ],
        "finding_groups": [
            {
                "code": code,
                "count": len(group),
                "first_timecode": (
                    format_timecode_interval(group[0].timestamp_start_seconds)
                    if group[0].timestamp_start_seconds is not None
                    else None
                ),
                "suggested_action": allowed[code],
            }
            for code, group in groups.items()
        ],
        "successful_review_checks": _successful_review_checks(
            promise_check,
            viewer_pass,
            claim_review,
        ),
        "inconclusive_factual_claims": inconclusive_claim_count,
    }
    prompt = (
        "Write an AI review of the REVIEW RESULTS using only the trusted JSON-like facts below. "
        "Do not summarize what the creator's video is about. Explain relationships between supplied "
        "findings when their intervals overlap, group repeated finding types, identify what can be repaired "
        "versus what needs human judgment, and prioritize the best place to start. The summary must synthesize "
        "the review rather than repeat a list of titles. Mention a clean review subsystem only when it appears "
        "in successful_review_checks. Use no more than three short paragraphs. "
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
        if _RAW_FLOAT_SECONDS.search(combined_copy):
            raise AIReviewError("ai_provider_response_invalid", "AI release brief used a raw numeric timestamp.")
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
    return f"{title} at {format_timecode_interval(finding.timestamp_start_seconds)}"[:200]


def _finding_groups(findings: list[Finding]) -> dict[str, list[Finding]]:
    groups: dict[str, list[Finding]] = {}
    for finding in findings:
        groups.setdefault(finding.code, []).append(finding)
    return groups


def _repairable_keys(repair_plan: RepairPlan | None) -> set[tuple[str, float | None, float | None]]:
    if repair_plan is None:
        return set()
    return {
        (proposal.finding_code, proposal.start_seconds, proposal.end_seconds)
        for proposal in repair_plan.proposals
        if proposal.operation is not None
    }


def _group_action(group: list[Finding], repair_plan: RepairPlan | None) -> str:
    first = group[0]
    title = str((first.details or {}).get("title") or first.code)
    location = (
        format_timecode_interval(first.timestamp_start_seconds)
        if first.timestamp_start_seconds is not None
        else None
    )
    repairable = (first.code, first.timestamp_start_seconds, first.timestamp_end_seconds) in _repairable_keys(repair_plan)
    if repairable:
        return f"Preview the repair for {title.lower()}{f' at {location}' if location else ''}"[:200]
    if len(group) > 1:
        grouped_title = title.lower().removesuffix(" section")
        return f"Review {len(group)} related {grouped_title} findings together{f', starting at {location}' if location else ''}"[:200]
    if first.code == "AUDIO_LONG_SILENCE":
        return f"Confirm whether {title.lower()}{f' at {location}' if location else ''} is intentional"[:200]
    return _action_text(first)


def _prioritized_actions(findings: list[Finding], repair_plan: RepairPlan | None) -> list[str]:
    groups = _finding_groups(findings)
    repairable = _repairable_keys(repair_plan)
    ordered = sorted(
        groups.items(),
        key=lambda item: (
            0 if any(finding.source == "release_contract.deterministic" for finding in item[1])
            else 1 if any((finding.code, finding.timestamp_start_seconds, finding.timestamp_end_seconds) in repairable for finding in item[1])
            else 2 if item[0] == "AUDIO_LONG_SILENCE"
            else 3 if len(item[1]) > 1
            else 4,
            findings.index(item[1][0]),
        ),
    )
    return [_group_action(group, repair_plan) for _, group in ordered[:3]]


def _synthesized_summary(
    findings: list[Finding],
    repair_plan: RepairPlan | None,
    promise_check: PromiseCheckSummary | None,
    viewer_pass: ViewerPassSummary | None,
    claim_review: ClaimReviewSummary | None,
) -> str:
    groups = _finding_groups(findings)
    actions = _prioritized_actions(findings, repair_plan)
    lead = f"Start here: {actions[0][0].lower() + actions[0][1:]}" if actions else "Review the findings below"
    audio_group = groups.get("AUDIO_LONG_SILENCE")
    if audio_group is not None:
        audio_action = _group_action(audio_group, repair_plan)
        if audio_action not in actions[:1]:
            lead += f", then {audio_action[0].lower() + audio_action[1:]}"
    sentences = [lead + "."]
    repeated = next((group for group in groups.values() if len(group) > 1), None)
    if repeated is not None and len(actions) > 1:
        grouped_action = _group_action(repeated, repair_plan)
        if grouped_action not in actions[:1]:
            sentences.append(grouped_action[0].upper() + grouped_action[1:] + ".")
    clean = _successful_review_checks(promise_check, viewer_pass, claim_review)
    if clean:
        sentences.append(f"{_human_list(clean)} review did not surface another high-confidence issue.")
    return " ".join(sentences)[:500]


def _successful_review_checks(
    promise_check: PromiseCheckSummary | None,
    viewer_pass: ViewerPassSummary | None,
    claim_review: ClaimReviewSummary | None,
) -> list[str]:
    clean: list[str] = []
    if promise_check is not None and promise_check.status is PromiseCheckStatus.ALIGNED:
        clean.append("Opening")
    if viewer_pass is not None and viewer_pass.status is ViewerPassStatus.CLEAN:
        clean.append("continuity")
    if claim_review is not None and claim_review.status in {ClaimReviewStatus.CLEAN, ClaimReviewStatus.NO_CLAIMS}:
        clean.append("factual")
    return clean


def _human_list(values: list[str]) -> str:
    if len(values) < 2:
        return values[0] if values else ""
    if len(values) == 2:
        return " and ".join(values)
    return ", ".join(values[:-1]) + f", and {values[-1]}"
