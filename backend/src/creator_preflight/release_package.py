"""Deterministic release-package and basic thumbnail delivery evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from creator_preflight.thumbnails import ThumbnailInfo
from creator_preflight.thumbnail_assurance import ThumbnailAssuranceReport, assurance_findings


class PackageComponentState(str, Enum):
    PRESENT_VALID = "PRESENT_VALID"
    PRESENT_INVALID = "PRESENT_INVALID"
    ABSENT = "ABSENT"
    NOT_REQUIRED = "NOT_REQUIRED"


class ThumbnailCheckStatus(str, Enum):
    PASS = "PASS"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class PackageComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: PackageComponentState
    detail: str


class ThumbnailCriticalRegion(BaseModel):
    """Explicit normalized artwork geometry; never inferred from image content."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=100)
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(gt=0, le=1, allow_inf_nan=False)
    height: float = Field(gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def inside_artwork(self) -> "ThumbnailCriticalRegion":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("critical region must remain inside thumbnail bounds")
        return self


class DeliverySurface(BaseModel):
    """Approximate platform presentation geometry, not a platform guarantee."""

    model_config = ConfigDict(extra="forbid")

    surface_id: str
    label: str
    display_width: int = Field(gt=0, le=4096)
    display_height: int = Field(gt=0, le=4096)
    safe_margin_fraction: float = Field(ge=0, le=.2, allow_inf_nan=False)
    badge_x: float = Field(ge=0, le=1, allow_inf_nan=False)
    badge_y: float = Field(ge=0, le=1, allow_inf_nan=False)
    badge_width: float = Field(gt=0, le=1, allow_inf_nan=False)
    badge_height: float = Field(gt=0, le=1, allow_inf_nan=False)


DEFAULT_DELIVERY_SURFACES = (
    DeliverySurface(surface_id="mobile_feed", label="Mobile feed / search", display_width=168, display_height=94, safe_margin_fraction=.035, badge_x=.73, badge_y=.72, badge_width=.23, badge_height=.22),
    DeliverySurface(surface_id="desktop_grid", label="Desktop grid", display_width=246, display_height=138, safe_margin_fraction=.03, badge_x=.76, badge_y=.76, badge_width=.20, badge_height=.18),
    DeliverySurface(surface_id="desktop_sidebar", label="Desktop sidebar", display_width=168, display_height=94, safe_margin_fraction=.035, badge_x=.73, badge_y=.72, badge_width=.23, badge_height=.22),
    DeliverySurface(surface_id="tv_large", label="TV / large surface", display_width=320, display_height=180, safe_margin_fraction=.025, badge_x=.78, badge_y=.78, badge_width=.18, badge_height=.16),
)


class ThumbnailDeliveryCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    label: str
    status: ThumbnailCheckStatus
    measured: str
    expected: str


class CriticalRegionIntersection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_label: str
    surface_id: str
    intersects_duration_badge: bool
    intersects_unsafe_edge: bool


class DeliveryPreviewSurface(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface_id: str
    label: str
    display_width: int
    display_height: int
    safe_margin_fraction: float
    badge_x: float
    badge_y: float
    badge_width: float
    badge_height: float


class DeliveryPreviewMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_badge_text: str | None = None
    surfaces: list[DeliveryPreviewSurface] = Field(default_factory=list)
    critical_region_intersections: list[CriticalRegionIntersection] = Field(default_factory=list)


class ReleasePackageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video: PackageComponent
    thumbnail: PackageComponent
    captions: PackageComponent
    title: PackageComponent
    description: PackageComponent
    chapters: PackageComponent
    release_contract: PackageComponent
    thumbnail_mime_type: str | None = None
    thumbnail_file_size_bytes: int | None = Field(default=None, ge=0)
    thumbnail_width: int | None = Field(default=None, gt=0)
    thumbnail_height: int | None = Field(default=None, gt=0)
    thumbnail_checks: list[ThumbnailDeliveryCheck] = Field(default_factory=list)
    delivery_preview: DeliveryPreviewMetadata | None = None
    thumbnail_assurance: ThumbnailAssuranceReport | None = None
    construction_seconds: float = Field(ge=0, allow_inf_nan=False)
    thumbnail_evaluation_seconds: float = Field(ge=0, allow_inf_nan=False)
    preview_metadata_seconds: float = Field(ge=0, allow_inf_nan=False)


def empty_release_package_summary() -> ReleasePackageSummary:
    """Compatibility default for older in-memory report fixtures."""

    absent = PackageComponent(state=PackageComponentState.ABSENT, detail="Not supplied")
    optional = PackageComponent(state=PackageComponentState.NOT_REQUIRED, detail="Not supplied")
    return ReleasePackageSummary(
        video=absent,
        thumbnail=optional,
        captions=optional,
        title=absent,
        description=absent,
        chapters=optional,
        release_contract=optional,
        construction_seconds=0,
        thumbnail_evaluation_seconds=0,
        preview_metadata_seconds=0,
    )


@dataclass(frozen=True)
class ReleasePackageEvaluation:
    summary: ReleasePackageSummary
    findings: list[Any]
    checks: list[Any]


def evaluate_release_package(
    *,
    package: Any,
    media: Any,
    thumbnail_info: ThumbnailInfo | None,
    thumbnail_error: str | None,
    caption_summary: Any | None,
    caption_findings: list[Any],
    package_findings: list[Any],
    minimum_thumbnail_width: int,
    minimum_thumbnail_height: int,
    target_aspect_ratio: float,
    aspect_ratio_tolerance: float,
    maximum_thumbnail_file_size_bytes: int,
    delivery_surfaces: tuple[DeliverySurface, ...] = DEFAULT_DELIVERY_SURFACES,
    critical_regions: list[ThumbnailCriticalRegion] | None = None,
    thumbnail_assurance: ThumbnailAssuranceReport | None = None,
) -> ReleasePackageEvaluation:
    from creator_preflight.models import CheckResult, Finding, FindingSeverity, FindingStatus
    from creator_preflight.rules import parse_chapters

    started = perf_counter()
    thumbnail_started = perf_counter()
    findings: list[Finding] = []
    checks: list[CheckResult] = []
    thumbnail_checks: list[ThumbnailDeliveryCheck] = []
    if thumbnail_assurance is not None:
        findings.extend(assurance_findings(thumbnail_assurance))

    if package.thumbnail_path is not None and thumbnail_info is None:
        findings.append(Finding(
            code="THUMBNAIL_INVALID",
            severity=FindingSeverity.ERROR,
            status=FindingStatus.BLOCKED,
            message=thumbnail_error or "The supplied thumbnail could not be decoded safely.",
            source="package.thumbnail",
            details={"title": "Thumbnail could not be validated", "category": "package"},
            suggestion="Supply a valid PNG or JPEG thumbnail.",
        ))
        checks.append(CheckResult(check_id="thumbnail.decode", passed=False, finding_codes=["THUMBNAIL_INVALID"]))
    elif thumbnail_info is not None:
        checks.append(CheckResult(check_id="thumbnail.decode", passed=True))
        thumbnail_checks.append(_thumbnail_check("decode", "Decode validity", True, thumbnail_info.mime_type, "Valid PNG or JPEG"))
        size_ok = thumbnail_info.file_size_bytes <= maximum_thumbnail_file_size_bytes
        thumbnail_checks.append(_thumbnail_check("file_size", "File size", size_ok, f"{thumbnail_info.file_size_bytes} bytes", f"At most {maximum_thumbnail_file_size_bytes} bytes"))
        checks.append(CheckResult(check_id="thumbnail.file_size", passed=size_ok, finding_codes=[] if size_ok else ["THUMBNAIL_FILE_SIZE_REVIEW"]))
        resolution_ok = thumbnail_info.width >= minimum_thumbnail_width and thumbnail_info.height >= minimum_thumbnail_height
        thumbnail_checks.append(_thumbnail_check("resolution", "Resolution", resolution_ok, f"{thumbnail_info.width}×{thumbnail_info.height}", f"At least {minimum_thumbnail_width}×{minimum_thumbnail_height}"))
        if not resolution_ok:
            findings.append(_thumbnail_finding("THUMBNAIL_RESOLUTION_LOW", "Thumbnail resolution is low", f"The thumbnail is {thumbnail_info.width}×{thumbnail_info.height}; the practical target is at least {minimum_thumbnail_width}×{minimum_thumbnail_height}.", "Use a higher-resolution thumbnail before delivery."))
        checks.append(CheckResult(check_id="thumbnail.resolution", passed=resolution_ok, finding_codes=[] if resolution_ok else ["THUMBNAIL_RESOLUTION_LOW"]))
        actual_ratio = thumbnail_info.width / thumbnail_info.height
        aspect_ok = abs(actual_ratio - target_aspect_ratio) / target_aspect_ratio <= aspect_ratio_tolerance
        thumbnail_checks.append(_thumbnail_check("aspect_ratio", "Aspect ratio", aspect_ok, f"{thumbnail_info.width}:{thumbnail_info.height}", "16:9 delivery artwork"))
        if not aspect_ok:
            findings.append(_thumbnail_finding("THUMBNAIL_ASPECT_RATIO_REVIEW", "Thumbnail aspect ratio needs review", f"The supplied thumbnail is {thumbnail_info.width}×{thumbnail_info.height}, which does not match the configured 16:9 delivery target.", "Review the crop before delivery."))
        checks.append(CheckResult(check_id="thumbnail.aspect_ratio", passed=aspect_ok, finding_codes=[] if aspect_ok else ["THUMBNAIL_ASPECT_RATIO_REVIEW"]))
    thumbnail_elapsed = perf_counter() - thumbnail_started

    preview_started = perf_counter()
    regions = critical_regions or []
    preview = None
    if thumbnail_info is not None:
        preview = DeliveryPreviewMetadata(
            duration_badge_text=format_duration_badge(media.duration_seconds) if media.duration_seconds is not None else None,
            surfaces=[DeliveryPreviewSurface(**surface.model_dump()) for surface in delivery_surfaces],
            critical_region_intersections=[
                _intersection(region, surface) for region in regions for surface in delivery_surfaces
            ],
        )
    preview_elapsed = perf_counter() - preview_started

    caption_invalid_codes = {
        "CAPTION_PARSE_ERROR", "CAPTION_EMPTY", "CAPTION_TIMING_INVALID",
        "CAPTION_TIMING_NOT_MONOTONIC", "CAPTION_CUE_OUT_OF_RANGE",
        "CAPTION_CUE_OVERLAP", "CAPTION_CUE_EMPTY_TEXT",
    }
    caption_invalid = any(item.code in caption_invalid_codes for item in caption_findings)
    chapter_parse = parse_chapters(package.description)
    chapter_codes = {"CHAPTER_TIMESTAMP_INVALID", "CHAPTER_TIMESTAMPS_NOT_INCREASING", "CHAPTER_BEYOND_MEDIA_DURATION", "CHAPTER_FIRST_NOT_ZERO"}
    chapter_invalid = bool(chapter_parse.invalid_entries) or any(item.code in chapter_codes for item in package_findings)
    summary = ReleasePackageSummary(
        video=PackageComponent(state=PackageComponentState.PRESENT_VALID, detail=_video_detail(media)),
        thumbnail=PackageComponent(
            state=PackageComponentState.PRESENT_VALID if thumbnail_info else PackageComponentState.PRESENT_INVALID if package.thumbnail_path is not None else PackageComponentState.NOT_REQUIRED,
            detail=f"{thumbnail_info.width}×{thumbnail_info.height} {thumbnail_info.mime_type}" if thumbnail_info else thumbnail_error or "Not supplied",
        ),
        captions=PackageComponent(
            state=PackageComponentState.PRESENT_INVALID if package.captions_path is not None and (caption_summary is None or caption_invalid) else PackageComponentState.PRESENT_VALID if package.captions_path is not None else PackageComponentState.NOT_REQUIRED,
            detail=f"{caption_summary.cue_count} cues" if caption_summary is not None else "Invalid" if package.captions_path is not None else "Not supplied",
        ),
        title=PackageComponent(state=PackageComponentState.PRESENT_VALID if package.title.strip() else PackageComponentState.ABSENT, detail="Supplied" if package.title.strip() else "Not supplied"),
        description=PackageComponent(state=PackageComponentState.PRESENT_VALID if package.description.strip() else PackageComponentState.ABSENT, detail="Supplied" if package.description.strip() else "Not supplied"),
        chapters=PackageComponent(state=PackageComponentState.PRESENT_INVALID if chapter_invalid else PackageComponentState.PRESENT_VALID if chapter_parse.chapters else PackageComponentState.NOT_REQUIRED, detail=f"{len(chapter_parse.chapters)} chapters" if chapter_parse.chapters else "Not supplied"),
        release_contract=PackageComponent(state=PackageComponentState.PRESENT_VALID if package.release_contract is not None else PackageComponentState.NOT_REQUIRED, detail=f"{len(package.release_contract.requirements)} requirements" if package.release_contract else "Not supplied"),
        thumbnail_mime_type=thumbnail_info.mime_type if thumbnail_info else None,
        thumbnail_file_size_bytes=thumbnail_info.file_size_bytes if thumbnail_info else None,
        thumbnail_width=thumbnail_info.width if thumbnail_info else None,
        thumbnail_height=thumbnail_info.height if thumbnail_info else None,
        thumbnail_checks=thumbnail_checks,
        delivery_preview=preview,
        thumbnail_assurance=thumbnail_assurance,
        construction_seconds=perf_counter() - started,
        thumbnail_evaluation_seconds=thumbnail_elapsed,
        preview_metadata_seconds=preview_elapsed,
    )
    return ReleasePackageEvaluation(summary=summary, findings=findings, checks=checks)


def _thumbnail_check(check_id: str, label: str, passed: bool, measured: str, expected: str) -> ThumbnailDeliveryCheck:
    return ThumbnailDeliveryCheck(check_id=check_id, label=label, status=ThumbnailCheckStatus.PASS if passed else ThumbnailCheckStatus.NEEDS_REVIEW, measured=measured, expected=expected)


def _thumbnail_finding(code: str, title: str, message: str, suggestion: str):
    from creator_preflight.models import Finding, FindingSeverity, FindingStatus
    return Finding(code=code, severity=FindingSeverity.WARNING, status=FindingStatus.NEEDS_REVIEW, message=message, source="package.thumbnail", details={"title": title, "category": "package"}, suggestion=suggestion)


def _video_detail(media: Any) -> str:
    dimensions = f"{media.width}×{media.height}" if media.width and media.height else "dimensions unavailable"
    return f"{dimensions} · {format_duration_badge(media.duration_seconds) if media.duration_seconds is not None else 'duration unavailable'}"


def format_duration_badge(seconds: float) -> str:
    """Format actual inspected duration like consumer video duration badges."""

    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, whole_seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}" if hours else f"{minutes}:{whole_seconds:02d}"


def _intersection(region: ThumbnailCriticalRegion, surface: DeliverySurface) -> CriticalRegionIntersection:
    badge = (surface.badge_x, surface.badge_y, surface.badge_width, surface.badge_height)
    subject = (region.x, region.y, region.width, region.height)
    margin = surface.safe_margin_fraction
    return CriticalRegionIntersection(
        region_label=region.label,
        surface_id=surface.surface_id,
        intersects_duration_badge=_rectangles_intersect(subject, badge),
        intersects_unsafe_edge=(region.x < margin or region.y < margin or region.x + region.width > 1 - margin or region.y + region.height > 1 - margin),
    )


def _rectangles_intersect(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    return lx < rx + rw and rx < lx + lw and ly < ry + rh and ry < ly + lh
