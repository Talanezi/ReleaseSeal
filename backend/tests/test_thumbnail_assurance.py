from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from releaseseal.config import PreflightConfig
from releaseseal.engine import PreflightScanner
from releaseseal.models import PublishingPackage
from releaseseal.release_package import DEFAULT_DELIVERY_SURFACES
from releaseseal.thumbnail_assurance import (
    AssuranceEvidenceClass,
    AssuranceStatus,
    EdgeSafetyStatus,
    ThumbnailAssurancePolicy,
    ThumbnailAssuranceReport,
    ThumbnailAssuranceService,
    assurance_findings,
)
from releaseseal.thumbnail_assurance_fixture import generate_thumbnail_assurance_fixtures
from releaseseal.thumbnails import inspect_thumbnail


@pytest.fixture(scope="module")
def artwork(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return generate_thumbnail_assurance_fixtures(tmp_path_factory.mktemp("thumbnail-assurance"))


def analyze(path: Path, policy: ThumbnailAssurancePolicy | None = None) -> ThumbnailAssuranceReport:
    info = inspect_thumbnail(path, maximum_bytes=10_000_000)
    return ThumbnailAssuranceService().analyze(
        path,
        thumbnail=info,
        delivery_surfaces=DEFAULT_DELIVERY_SURFACES,
        policy=policy,
    )


def substantive(report: ThumbnailAssuranceReport) -> dict:
    return report.model_dump(exclude={"decode_seconds", "text_detection_seconds", "contrast_seconds", "detail_seconds", "total_seconds"})


def test_large_and_tiny_text_calibrate_delivered_height(artwork: dict[str, Path]) -> None:
    large = analyze(artwork["large_text"])
    tiny = analyze(artwork["tiny_text"])
    assert large.status is AssuranceStatus.CLEAR
    assert large.evidence_class is AssuranceEvidenceClass.ADVISORY
    assert large.confident_region_count == 1
    assert large.regions[0].evidence_class is AssuranceEvidenceClass.ADVISORY
    assert large.delivered_text[0].evidence_class is AssuranceEvidenceClass.MEASURED
    assert min(item.delivered_height_pixels for item in large.delivered_text) >= 8
    assert tiny.status is AssuranceStatus.NEEDS_REVIEW
    assert "THUMBNAIL_TEXT_DELIVERY_SMALL" in tiny.finding_codes
    assert min(item.delivered_height_pixels for item in tiny.delivered_text) < 8


def test_contrast_badge_and_edge_evidence_are_region_grounded(artwork: dict[str, Path]) -> None:
    low = analyze(artwork["low_contrast"])
    badge = analyze(artwork["badge_collision"])
    edge = analyze(artwork["unsafe_edge"])
    safe = analyze(artwork["safe_region"])
    assert low.regions[0].estimated_local_contrast_ratio < low.minimum_estimated_contrast_ratio
    assert low.finding_codes == ["THUMBNAIL_TEXT_CONTRAST_REVIEW"]
    assert "THUMBNAIL_TEXT_CHROME_COLLISION" in badge.finding_codes
    assert any(item.badge_overlap_fraction >= .1 for item in badge.delivered_text)
    assert badge.delivered_text[0].badge_overlap_fraction == .8364
    assert "THUMBNAIL_TEXT_EDGE_RISK" in edge.finding_codes
    assert any(item.edge_safety is EdgeSafetyStatus.INTERSECTS_UNSAFE_AREA for item in edge.delivered_text)
    assert safe.finding_codes == []


def test_multiple_sizes_and_outline_consolidation(artwork: dict[str, Path]) -> None:
    multiple = analyze(artwork["multiple_sizes"])
    outlined = analyze(artwork["outlined_text"])
    assert multiple.confident_region_count == 2
    assert "THUMBNAIL_TEXT_DELIVERY_SMALL" in multiple.finding_codes
    assert outlined.confident_region_count == 1
    assert outlined.finding_codes == []


def test_textless_and_busy_images_abstain_instead_of_false_text_failure(artwork: dict[str, Path]) -> None:
    textless = analyze(artwork["textless_natural"])
    busy = analyze(artwork["busy_background"])
    assert textless.status is AssuranceStatus.NOT_EVALUATED
    assert busy.status is AssuranceStatus.NOT_EVALUATED
    assert textless.confident_region_count == busy.confident_region_count == 0
    assert textless.finding_codes == busy.finding_codes == []


def test_authentic_usgs_title_uses_conservative_segmentation_fallback() -> None:
    thumbnail = Path(__file__).parents[2] / ".demo" / "owner" / "thumbnail.jpg"
    if not thumbnail.exists():
        pytest.skip("ignored authentic owner-demo thumbnail is not present")
    report = analyze(thumbnail)
    assert report.confident_region_count >= 1
    assert report.confident_region_count <= 4
    assert all(region.detector == "SEGMENTATION_FALLBACK" for region in report.regions)
    assert any(
        region.source_x < 200 and region.source_y < 500
        and region.source_width > 500 and region.source_height > 100
        for region in report.regions
    )


def test_detail_survival_is_advisory_and_distinguishes_compositions(artwork: dict[str, Path]) -> None:
    detail = analyze(artwork["detail_heavy"])
    simple = analyze(artwork["simple_composition"])
    assert detail.surfaces[0].detail_status is AssuranceStatus.NEEDS_REVIEW
    assert detail.surfaces[0].detail_retention_ratio < .2
    assert simple.surfaces[0].detail_status is AssuranceStatus.CLEAR
    assert detail.finding_codes == []


def test_png_and_jpeg_are_stable_and_pixels_are_deterministic(artwork: dict[str, Path]) -> None:
    png = analyze(artwork["large_text"])
    jpeg = analyze(artwork["large_text_jpeg"])
    repeated = analyze(artwork["large_text"])
    assert substantive(png) == substantive(repeated)
    assert png.status is jpeg.status is AssuranceStatus.CLEAR
    assert len(png.regions) == len(jpeg.regions) == 1
    assert png.regions[0].box.model_dump() == pytest.approx(jpeg.regions[0].box.model_dump(), abs=.015)
    assert png.surfaces[0].detail_retention_ratio == pytest.approx(jpeg.surfaces[0].detail_retention_ratio, abs=.02)


def test_low_confidence_policy_abstains_and_disabled_mode_is_not_evaluated(artwork: dict[str, Path]) -> None:
    strict = analyze(artwork["large_text"], ThumbnailAssurancePolicy(minimum_region_confidence=.95))
    disabled = analyze(artwork["large_text"], ThumbnailAssurancePolicy(enabled=False))
    assert strict.confident_region_count == 0
    assert strict.status is AssuranceStatus.NOT_EVALUATED
    assert disabled.evidence_class is AssuranceEvidenceClass.NOT_EVALUATED
    assert disabled.finding_codes == []


def test_assurance_findings_are_review_only(artwork: dict[str, Path]) -> None:
    findings = assurance_findings(analyze(artwork["badge_collision"]))
    assert findings
    assert all(item.status.value == "NEEDS_REVIEW" for item in findings)
    assert all(item.severity.value == "warning" for item in findings)
    assert not any(item.status.value == "BLOCKED" for item in findings)


def test_scanner_integrates_assurance_without_provider_or_deterministic_block(
    artwork: dict[str, Path], video_with_audio: Path,
) -> None:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    report = PreflightScanner(config=config).scan(
        video_with_audio,
        PublishingPackage(
            title="Controlled thumbnail",
            description="A local deterministic check.",
            thumbnail_path=artwork["tiny_text"],
        ),
    )
    assert report.release_package.thumbnail_assurance is not None
    assert report.release_package.thumbnail_assurance.status is AssuranceStatus.NEEDS_REVIEW
    finding = next(item for item in report.findings if item.code == "THUMBNAIL_TEXT_DELIVERY_SMALL")
    assert finding.status.value == "NEEDS_REVIEW"
    assert finding.source == "package.thumbnail.assurance"
    assert report.ai_review.status.value == "disabled"
    assert report.critical_count == 0


def test_no_thumbnail_keeps_assurance_absent(video_with_audio: Path) -> None:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    report = PreflightScanner(config=config).scan(
        video_with_audio,
        PublishingPackage(title="No thumbnail", description="Optional artwork omitted."),
    )
    assert report.release_package.thumbnail.state.value == "NOT_REQUIRED"
    assert report.release_package.thumbnail_assurance is None
    assert not any(item.source == "package.thumbnail.assurance" for item in report.findings)


def test_assurance_schema_rejects_unknown_fields_and_inconsistent_evidence(artwork: dict[str, Path]) -> None:
    payload = analyze(artwork["large_text"]).model_dump()
    payload["unknown"] = True
    with pytest.raises(ValidationError):
        ThumbnailAssuranceReport.model_validate(payload)
    payload.pop("unknown")
    payload["confident_region_count"] = 2
    with pytest.raises(ValidationError, match="count is inconsistent"):
        ThumbnailAssuranceReport.model_validate(payload)
