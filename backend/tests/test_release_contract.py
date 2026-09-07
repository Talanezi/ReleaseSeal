import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from creator_preflight.ai_review import AIReviewError, GeminiVideoReviewer
from creator_preflight.captions import CaptionCue
from creator_preflight.config import AIReviewConfig, PreflightConfig
from creator_preflight.engine import PreflightScanner
from creator_preflight.models import CaptionSummary, FindingStatus, MediaInspection, PublishingPackage, ReviewMode, ScanCompleteness
from creator_preflight.release_contract import (
    AspectRatio, CaptionsRequired, ThumbnailRequired, ContractStatus, DescriptionContains, DescriptionUrl,
    ForbiddenClaim, ForbiddenText, MaxDuration, MinResolution, ReleaseContract,
    RequiredBeforeTime, RequiredExactToken, RequiredTalkingPoint, RequiredText,
    RequiredUrl, TitleContains, evaluate_release_contract,
    evaluate_semantic_requirements,
    SemanticRequirementBatch, SemanticRequirementDecision,
    contract_findings,
)
from creator_preflight.release_contract_extraction import GeminiReleaseContractExtractor, validate_extracted_contract
from creator_preflight.release_brief import deterministic_release_brief
from creator_preflight.repairs import build_repair_plan


def media(duration=60, width=1920, height=1080):
    return MediaInspection(duration_seconds=duration, format_name="mp4", file_size_bytes=1, has_video=True,
        video_stream_count=1, video_codec="h264", width=width, height=height, has_audio=True,
        audio_stream_count=1, audio_codec="aac")


def evaluate(requirements, *, cues=None, title="Yellowstone guide", description="Visit https://example.com/deal"):
    cues = cues or []
    return evaluate_release_contract(ReleaseContract(requirements=requirements), package=PublishingPackage(title=title, description=description),
        media=media(), caption_cues=cues, caption_summary=CaptionSummary(source_format="srt", cue_count=len(cues), first_caption_seconds=cues[0].start_seconds if cues else None,
        last_caption_seconds=cues[-1].end_seconds if cues else None, covered_duration_seconds=sum(c.end_seconds-c.start_seconds for c in cues), timeline_coverage_percent=1 if cues else None) if cues else None, caption_findings=[])


def test_deterministic_requirement_matrix_and_evidence_sources():
    cues = [CaptionCue(5, 8, "AcmeVPN code SAVE25 https://acme.test/deal"), CaptionCue(40, 43, "forbidden phrase")]
    requirements = [
        RequiredText(id="text", type="REQUIRED_TEXT", instruction="Mention AcmeVPN", value="AcmeVPN"),
        RequiredExactToken(id="token", type="REQUIRED_EXACT_TOKEN", instruction="Use SAVE25", value="SAVE25"),
        RequiredUrl(id="url", type="REQUIRED_URL", instruction="Say URL", value="https://acme.test/deal"),
        RequiredBeforeTime(id="before", type="REQUIRED_BEFORE_TIME", instruction="Mention early", value="AcmeVPN", before_seconds=30),
        ForbiddenText(id="forbid", type="FORBIDDEN_TEXT", instruction="Avoid phrase", value="forbidden phrase"),
        TitleContains(id="title", type="TITLE_CONTAINS", instruction="Title topic", value="Yellowstone"),
        DescriptionContains(id="desc", type="DESCRIPTION_CONTAINS", instruction="Description says Visit", value="Visit"),
        DescriptionUrl(id="desc-url", type="DESCRIPTION_URL", instruction="Description URL", value="https://example.com/deal"),
        MaxDuration(id="duration", type="MAX_DURATION", instruction="Under 61 seconds", maximum_seconds=61),
        MinResolution(id="resolution", type="MIN_RESOLUTION", instruction="At least HD", minimum_width=1280, minimum_height=720),
        AspectRatio(id="ratio", type="ASPECT_RATIO", instruction="16 by 9", width_ratio=16, height_ratio=9),
        CaptionsRequired(id="captions", type="CAPTIONS_REQUIRED", instruction="Captions required"),
    ]
    result = evaluate(requirements, cues=cues)
    assert [row.status for row in result.results] == [ContractStatus.PASS] * 4 + [ContractStatus.FAIL] + [ContractStatus.PASS] * 7
    assert result.results[3].timestamp_seconds == 5
    assert result.results[0].evidence_source.value == "CAPTION_TEXT"
    assert result.runtime_seconds < .1


def test_missing_text_source_is_not_evaluated_and_late_mention_fails():
    unavailable = evaluate([RequiredText(id="text", type="REQUIRED_TEXT", instruction="Mention", value="Acme")])
    assert unavailable.results[0].status is ContractStatus.NOT_EVALUATED
    late = evaluate([RequiredBeforeTime(id="early", type="REQUIRED_BEFORE_TIME", instruction="Early", value="Acme", before_seconds=30)], cues=[CaptionCue(35, 36, "Acme")])
    assert late.results[0].status is ContractStatus.FAIL
    assert "00:35.00" in late.results[0].evidence
    missing_url = evaluate([DescriptionUrl(id="url", type="DESCRIPTION_URL", instruction="Required URL", value="https://missing.example/path")])
    assert missing_url.results[0].status is ContractStatus.FAIL
    media_failures = evaluate([
        MinResolution(id="resolution", type="MIN_RESOLUTION", instruction="4K required", minimum_width=3840, minimum_height=2160),
        AspectRatio(id="ratio", type="ASPECT_RATIO", instruction="Square required", width_ratio=1, height_ratio=1),
        CaptionsRequired(id="captions", type="CAPTIONS_REQUIRED", instruction="Captions required"),
    ])
    assert [row.status for row in media_failures.results] == [ContractStatus.FAIL] * 3


def test_thumbnail_required_is_presence_only_and_remains_contract_owned():
    missing = evaluate([ThumbnailRequired(id="thumbnail", type="THUMBNAIL_REQUIRED", instruction="Thumbnail required")])
    assert missing.results[0].status is ContractStatus.FAIL
    package = PublishingPackage(title="Title", thumbnail_path="thumbnail.jpg")
    present = evaluate_release_contract(ReleaseContract(requirements=[ThumbnailRequired(id="thumbnail", type="THUMBNAIL_REQUIRED", instruction="Thumbnail required")]), package=package, media=media(), caption_cues=[], caption_summary=None, caption_findings=[])
    assert present.results[0].status is ContractStatus.PASS


def test_exact_token_near_match_is_diagnostic_only():
    result = evaluate([RequiredExactToken(id="promo", type="REQUIRED_EXACT_TOKEN", instruction="Use SAVE25", value="SAVE25")], cues=[CaptionCue(12, 13, "Use SAVE20 today")])
    assert result.results[0].status is ContractStatus.FAIL
    assert "SAVE20" in result.results[0].evidence


def test_semantic_requirements_are_advisory_by_schema():
    result = evaluate([RequiredTalkingPoint(id="point", type="REQUIRED_TALKING_POINT", instruction="Discuss privacy", value="privacy"), ForbiddenClaim(id="claim", type="FORBIDDEN_CLAIM", instruction="Do not guarantee", value="guarantees complete protection")])
    assert all(row.status is ContractStatus.NOT_EVALUATED for row in result.results)
    assert all(row.evaluation_class.value == "SEMANTIC" for row in result.results)


def test_semantic_requirements_use_one_bounded_request_and_low_confidence_reviews():
    evaluation = evaluate([
        RequiredTalkingPoint(id="point", type="REQUIRED_TALKING_POINT", instruction="Discuss privacy", value="privacy"),
        ForbiddenClaim(id="claim", type="FORBIDDEN_CLAIM", instruction="Do not guarantee", value="guarantees complete protection"),
    ], cues=[CaptionCue(2, 4, "Privacy is discussed without a guarantee.")])
    class Session:
        calls = 0
        def generate_text_structured(self, **kwargs):
            self.calls += 1
            assert len(kwargs["prompt"]) < 21_000
            return SimpleNamespace(output=SemanticRequirementBatch(results=[
                SemanticRequirementDecision(requirement_id="point", status="PASS", confidence=.95, reason="The supplied captions discuss privacy.", evidence="Privacy is discussed"),
                SemanticRequirementDecision(requirement_id="claim", status="PASS", confidence=.4, reason="Absence is uncertain.", evidence=None),
            ]))
    session = Session()
    result = evaluate_semantic_requirements(evaluation, caption_cues=[CaptionCue(2, 4, "Privacy is discussed without a guarantee.")], session=session)
    assert session.calls == 1
    assert [item.status for item in result.results] == [ContractStatus.PASS, ContractStatus.NEEDS_REVIEW]
    assert result.results[1].reason_code == "low_confidence"


def test_semantic_review_rejects_unsupplied_quote():
    evaluation = evaluate([RequiredTalkingPoint(id="point", type="REQUIRED_TALKING_POINT", instruction="Discuss privacy", value="privacy")], cues=[CaptionCue(2, 4, "Privacy matters.")])
    session = SimpleNamespace(generate_text_structured=lambda **kwargs: SimpleNamespace(output=SemanticRequirementBatch(results=[SemanticRequirementDecision(requirement_id="point", status="PASS", confidence=.9, reason="Covered.", evidence="invented quote")])))
    with pytest.raises(AIReviewError, match="evidence"):
        evaluate_semantic_requirements(evaluation, caption_cues=[CaptionCue(2, 4, "Privacy matters.")], session=session)


def test_contract_rejects_impossible_and_untyped_rules():
    with pytest.raises(ValidationError):
        ReleaseContract.model_validate({"requirements": [{"id": "x", "type": "ARBITRARY", "instruction": "no"}]})
    with pytest.raises(ValidationError):
        ReleaseContract(requirements=[MinResolution(id="bad", type="MIN_RESOLUTION", instruction="bad", minimum_width=-1, minimum_height=1080)])
    with pytest.raises(ValidationError):
        ReleaseContract(requirements=[RequiredText(id="same", type="REQUIRED_TEXT", instruction="one", value="x"), RequiredText(id="same", type="REQUIRED_TEXT", instruction="two", value="y")])
    with pytest.raises(ValidationError):
        ReleaseContract(requirements=[RequiredTalkingPoint(id=f"point-{index}", type="REQUIRED_TALKING_POINT", instruction="point", value="value") for index in range(6)])
    with pytest.raises(ValidationError):
        ReleaseContract(requirements=[RequiredText(id=f"item-{index}", type="REQUIRED_TEXT", instruction="item", value="value") for index in range(31)])


@pytest.mark.parametrize("requirement", [
    {"id": "unknown", "type": "UNKNOWN", "instruction": "Unknown"},
    {"id": "missing", "type": "REQUIRED_TEXT", "instruction": "Missing value"},
    {"id": "negative", "type": "REQUIRED_BEFORE_TIME", "instruction": "Early", "value": "Acme", "before_seconds": -1},
    {"id": "url", "type": "DESCRIPTION_URL", "instruction": "URL", "value": "not a url"},
    {"id": "giant", "type": "REQUIRED_TEXT", "instruction": "Text", "value": "x" * 501},
])
def test_hostile_or_malformed_requirement_payloads_fail_closed(requirement):
    with pytest.raises(ValidationError):
        ReleaseContract.model_validate({"requirements": [requirement]})


def test_deterministic_contract_failure_blocks_real_scan(video_with_audio: Path, tmp_path: Path):
    captions = tmp_path / "captions.srt"
    captions.write_text("1\n00:00:00,000 --> 00:00:00,800\nUse SAVE20\n", encoding="utf-8")
    config = PreflightConfig()
    config.rules.video.minimum_width = 160; config.rules.video.minimum_height = 90
    contract = ReleaseContract(requirements=[RequiredExactToken(id="promo", type="REQUIRED_EXACT_TOKEN", instruction="Use SAVE25", value="SAVE25")])
    report = PreflightScanner(config=config).scan(video_with_audio, PublishingPackage(title="A title", description="A description", captions_path=captions, release_contract=contract))
    assert report.verdict is FindingStatus.BLOCKED
    assert report.release_contract.failed_count == 1
    assert report.findings[0].source == "release_contract.deterministic"


def test_semantic_provider_unavailable_is_partial_not_content_failure(video_with_audio: Path, tmp_path: Path):
    captions = tmp_path / "captions.srt"
    captions.write_text("1\n00:00:00,000 --> 00:00:00,900\nPrivacy matters.\n", encoding="utf-8")
    config = PreflightConfig()
    config.rules.video.minimum_width = 160; config.rules.video.minimum_height = 90
    config.ai_review.enabled = True
    contract = ReleaseContract(requirements=[RequiredTalkingPoint(id="point", type="REQUIRED_TALKING_POINT", instruction="Discuss privacy", value="privacy")])
    scanner = PreflightScanner(config=config, ai_adapter=GeminiVideoReviewer(environ={}))
    report = scanner.scan(video_with_audio, PublishingPackage(title="A title", description="A description", captions_path=captions, release_contract=contract), review_mode=ReviewMode.FULL)
    assert report.scan_completeness is ScanCompleteness.PARTIAL
    assert report.release_contract.results[0].status is ContractStatus.NOT_EVALUATED
    assert not any(finding.source.startswith("release_contract") for finding in report.findings)
    assert report.verdict is FindingStatus.READY


def test_contract_failure_is_prioritized_in_release_actions():
    evaluation = evaluate([MaxDuration(id="duration", type="MAX_DURATION", instruction="Client maximum duration", maximum_seconds=30)])
    findings = contract_findings(evaluation)
    brief = deterministic_release_brief(verdict=FindingStatus.BLOCKED, completeness=ScanCompleteness.COMPLETE, findings=findings, repair_plan=build_repair_plan(findings))
    assert brief.top_actions[0] == "Client maximum duration"


def extracted_contract(value="SAVE25", excerpt="Use promo code SAVE25"):
    return ReleaseContract(requirements=[RequiredExactToken(id="promo", type="REQUIRED_EXACT_TOKEN", instruction="Use promo code", value=value, provenance="extracted", source_excerpt=excerpt)])


def test_extraction_grounding_rejects_mutation_invention_and_duplicates():
    assert validate_extracted_contract(ReleaseContract(), "Upload by Friday").requirements == []
    assert validate_extracted_contract(extracted_contract(), "Use promo code SAVE25").requirements[0].value == "SAVE25"
    with pytest.raises(AIReviewError, match="literal"):
        validate_extracted_contract(extracted_contract("SAVE20", "Use promo code SAVE25"), "Use promo code SAVE25")
    with pytest.raises(AIReviewError, match="supplied brief"):
        validate_extracted_contract(extracted_contract(excerpt="Captions are required"), "Use promo code SAVE25")
    duplicate = ReleaseContract(requirements=[
        RequiredExactToken(id="one", type="REQUIRED_EXACT_TOKEN", instruction="one", value="SAVE25", provenance="extracted", source_excerpt="Use SAVE25"),
        RequiredExactToken(id="two", type="REQUIRED_EXACT_TOKEN", instruction="two", value="SAVE25", provenance="extracted", source_excerpt="Use SAVE25"),
    ])
    with pytest.raises(AIReviewError, match="duplicate"):
        validate_extracted_contract(duplicate, "Use SAVE25")


def test_extraction_preserves_url_and_deadline_literals():
    brief = "Mention AcmeVPN before 00:30. Include https://acmevpn.com/thamer. Use SAVE25."
    contract = ReleaseContract(requirements=[
        RequiredBeforeTime(id="mention", type="REQUIRED_BEFORE_TIME", instruction="Mention early", value="AcmeVPN", before_seconds=30, provenance="extracted", source_excerpt="Mention AcmeVPN before 00:30."),
        DescriptionUrl(id="url", type="DESCRIPTION_URL", instruction="Include URL", value="https://acmevpn.com/thamer", provenance="extracted", source_excerpt="Include https://acmevpn.com/thamer."),
        RequiredExactToken(id="promo", type="REQUIRED_EXACT_TOKEN", instruction="Use code", value="SAVE25", provenance="extracted", source_excerpt="Use SAVE25."),
    ])
    validated = validate_extracted_contract(contract, brief)
    assert validated.requirements[0].before_seconds == 30
    assert validated.requirements[1].value == "https://acmevpn.com/thamer"
    assert validated.requirements[2].value == "SAVE25"
    mutated_url = ReleaseContract(requirements=[DescriptionUrl(id="url", type="DESCRIPTION_URL", instruction="Include URL", value="https://evil.example", provenance="extracted", source_excerpt="Include https://acmevpn.com/thamer.")])
    with pytest.raises(AIReviewError, match="literal"):
        validate_extracted_contract(mutated_url, brief)


def test_extractor_uses_native_schema_and_exact_brief():
    payload = extracted_contract().model_dump_json()
    client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text=payload)), close=lambda: None)
    adapter = GeminiVideoReviewer(client_factory=lambda key, timeout: client, environ={"GEMINI_API_KEY": "not-logged"})
    result = GeminiReleaseContractExtractor(adapter).extract("Use promo code SAVE25", AIReviewConfig())
    assert result.requirements[0].value == "SAVE25"
    with pytest.raises(AIReviewError, match="between 1"):
        GeminiReleaseContractExtractor(adapter).extract("x" * 20_001, AIReviewConfig())
