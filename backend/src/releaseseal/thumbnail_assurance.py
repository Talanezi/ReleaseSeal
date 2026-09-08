"""Bounded, deterministic thumbnail delivery measurements from validated pixels."""

from __future__ import annotations

import math
import subprocess
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from releaseseal.thumbnails import ThumbnailInfo


class AssuranceEvidenceClass(str, Enum):
    MEASURED = "MEASURED"
    ADVISORY = "ADVISORY"
    NOT_EVALUATED = "NOT_EVALUATED"


class AssuranceStatus(str, Enum):
    CLEAR = "CLEAR"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_EVALUATED = "NOT_EVALUATED"


class EdgeSafetyStatus(str, Enum):
    CLEAR = "CLEAR"
    NEAR_EDGE = "NEAR_EDGE"
    INTERSECTS_UNSAFE_AREA = "INTERSECTS_UNSAFE_AREA"


class NormalizedBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(gt=0, le=1, allow_inf_nan=False)
    height: float = Field(gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def inside_artwork(self) -> "NormalizedBox":
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("evidence box must remain inside the artwork")
        return self


class TextLikeRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: str = Field(min_length=1, max_length=40)
    evidence_class: AssuranceEvidenceClass = AssuranceEvidenceClass.ADVISORY
    box: NormalizedBox
    source_x: int = Field(ge=0)
    source_y: int = Field(ge=0)
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    estimated_cap_height_pixels: float = Field(gt=0, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    estimated_local_contrast_ratio: float = Field(ge=1, allow_inf_nan=False)
    contrast_evidence_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    detector: Literal["PRIMARY", "SEGMENTATION_FALLBACK"] = "PRIMARY"


class DeliveredTextMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: str
    evidence_class: AssuranceEvidenceClass = AssuranceEvidenceClass.MEASURED
    surface_id: str = Field(min_length=1, max_length=60)
    delivered_height_pixels: float = Field(ge=0, allow_inf_nan=False)
    status: AssuranceStatus
    badge_overlap_fraction: float = Field(ge=0, le=1, allow_inf_nan=False)
    edge_safety: EdgeSafetyStatus


class SurfaceAssurance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface_id: str = Field(min_length=1, max_length=60)
    evidence_class: AssuranceEvidenceClass = AssuranceEvidenceClass.ADVISORY
    label: str
    display_width: int = Field(gt=0)
    display_height: int = Field(gt=0)
    unreadable_text_area_share: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    detail_retention_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    detail_status: AssuranceStatus


class ThumbnailAssuranceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    evidence_class: AssuranceEvidenceClass
    status: AssuranceStatus
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    analysis_width: int = Field(gt=0)
    analysis_height: int = Field(gt=0)
    confident_region_count: int = Field(ge=0)
    regions: list[TextLikeRegion] = Field(default_factory=list, max_length=12)
    delivered_text: list[DeliveredTextMeasurement] = Field(default_factory=list, max_length=96)
    surfaces: list[SurfaceAssurance] = Field(default_factory=list, max_length=8)
    minimum_region_confidence: float = Field(ge=0, le=1)
    minimum_delivered_text_height_pixels: float = Field(gt=0)
    minimum_estimated_contrast_ratio: float = Field(gt=1)
    minimum_detail_retention_ratio: float = Field(ge=0, le=1)
    reason: str
    finding_codes: list[Literal[
        "THUMBNAIL_TEXT_DELIVERY_SMALL",
        "THUMBNAIL_TEXT_CONTRAST_REVIEW",
        "THUMBNAIL_TEXT_CHROME_COLLISION",
        "THUMBNAIL_TEXT_EDGE_RISK",
    ]] = Field(default_factory=list, max_length=4)
    decode_seconds: float = Field(ge=0, allow_inf_nan=False)
    text_detection_seconds: float = Field(ge=0, allow_inf_nan=False)
    contrast_seconds: float = Field(ge=0, allow_inf_nan=False)
    detail_seconds: float = Field(ge=0, allow_inf_nan=False)
    total_seconds: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def internally_consistent(self) -> "ThumbnailAssuranceReport":
        region_ids = [item.region_id for item in self.regions]
        surface_ids = [item.surface_id for item in self.surfaces]
        if self.confident_region_count != len(self.regions):
            raise ValueError("confident region count is inconsistent")
        if len(region_ids) != len(set(region_ids)) or len(surface_ids) != len(set(surface_ids)):
            raise ValueError("region and surface ids must be unique")
        delivered_pairs = [(item.region_id, item.surface_id) for item in self.delivered_text]
        expected_pairs = {(region, surface) for region in region_ids for surface in surface_ids}
        if len(delivered_pairs) != len(set(delivered_pairs)) or set(delivered_pairs) != expected_pairs:
            raise ValueError("delivered text measurements are inconsistent")
        if len(self.finding_codes) != len(set(self.finding_codes)):
            raise ValueError("finding codes must be unique")
        for region in self.regions:
            if region.source_x + region.source_width > self.source_width or region.source_y + region.source_height > self.source_height:
                raise ValueError("source evidence region exceeds the thumbnail")
        return self


class ThumbnailAssurancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    analysis_max_dimension: int = Field(default=320, ge=160, le=640)
    minimum_region_confidence: float = Field(default=.72, ge=.5, le=.95)
    minimum_delivered_text_height_pixels: float = Field(default=8.0, ge=4, le=20)
    minimum_estimated_contrast_ratio: float = Field(default=2.5, ge=1.2, le=7)
    minimum_detail_retention_ratio: float = Field(default=.72, ge=.2, le=.95)


class ThumbnailAssuranceService:
    """Analyze a safely validated PNG/JPEG through one bounded FFmpeg decode."""

    def __init__(self, *, ffmpeg_binary: str = "ffmpeg", timeout_seconds: float = 15) -> None:
        self.ffmpeg_binary = ffmpeg_binary
        self.timeout_seconds = timeout_seconds

    def analyze(
        self,
        path: str | Path,
        *,
        thumbnail: ThumbnailInfo,
        delivery_surfaces: tuple[Any, ...],
        policy: ThumbnailAssurancePolicy | None = None,
    ) -> ThumbnailAssuranceReport:
        policy = policy or ThumbnailAssurancePolicy()
        started = perf_counter()
        analysis_width, analysis_height = _fit_dimensions(
            thumbnail.width, thumbnail.height, policy.analysis_max_dimension
        )
        if not policy.enabled:
            return _not_evaluated(thumbnail, analysis_width, analysis_height, policy, "Thumbnail delivery assurance is disabled.", perf_counter() - started)

        decode_started = perf_counter()
        pixels = _decode_rgb(
            Path(path), analysis_width, analysis_height,
            ffmpeg_binary=self.ffmpeg_binary, timeout_seconds=self.timeout_seconds,
        )
        decode_seconds = perf_counter() - decode_started
        if pixels is None:
            return _not_evaluated(
                thumbnail, analysis_width, analysis_height, policy,
                "Validated artwork could not be decoded into the bounded analysis plane.",
                perf_counter() - started, decode_seconds=decode_seconds,
            )

        grayscale = _grayscale(pixels)
        text_started = perf_counter()
        candidates = _text_candidates(grayscale, analysis_width, analysis_height)
        detector: Literal["PRIMARY", "SEGMENTATION_FALLBACK"] = "PRIMARY"
        primary_regions = _regions(
            candidates, grayscale, analysis_width, analysis_height,
            thumbnail.width, thumbnail.height,
            detector=detector,
        )
        if not any(item.confidence >= policy.minimum_region_confidence for item in primary_regions):
            candidates = _segmentation_text_candidates(grayscale, analysis_width, analysis_height)
            detector = "SEGMENTATION_FALLBACK"
        text_seconds = perf_counter() - text_started
        contrast_started = perf_counter()
        regions = _regions(
            candidates, grayscale, analysis_width, analysis_height,
            thumbnail.width, thumbnail.height,
            detector=detector,
        )
        contrast_seconds = perf_counter() - contrast_started
        confident = [item for item in regions if item.confidence >= policy.minimum_region_confidence]

        delivered: list[DeliveredTextMeasurement] = []
        surface_reports: list[SurfaceAssurance] = []
        detail_started = perf_counter()
        for surface in delivery_surfaces:
            total_area = sum(item.box.width * item.box.height for item in confident)
            unreadable_area = 0.0
            for region in confident:
                delivered_height = region.estimated_cap_height_pixels * surface.display_height / thumbnail.height
                status = AssuranceStatus.CLEAR if delivered_height >= policy.minimum_delivered_text_height_pixels else AssuranceStatus.NEEDS_REVIEW
                if status is AssuranceStatus.NEEDS_REVIEW:
                    unreadable_area += region.box.width * region.box.height
                delivered.append(DeliveredTextMeasurement(
                    region_id=region.region_id,
                    surface_id=surface.surface_id,
                    delivered_height_pixels=round(delivered_height, 2),
                    status=status,
                    badge_overlap_fraction=round(_overlap_fraction(region.box, surface), 4),
                    edge_safety=_edge_safety(region.box, surface.safe_margin_fraction),
                ))
            retention = _detail_retention(
                grayscale, analysis_width, analysis_height,
                min(surface.display_width, analysis_width), min(surface.display_height, analysis_height),
            )
            surface_reports.append(SurfaceAssurance(
                surface_id=surface.surface_id,
                label=surface.label,
                display_width=surface.display_width,
                display_height=surface.display_height,
                unreadable_text_area_share=round(unreadable_area / total_area, 4) if total_area else None,
                detail_retention_ratio=round(retention, 4),
                detail_status=AssuranceStatus.CLEAR if retention >= policy.minimum_detail_retention_ratio else AssuranceStatus.NEEDS_REVIEW,
            ))
        detail_seconds = perf_counter() - detail_started

        finding_codes = _finding_codes(confident, delivered, surface_reports, policy)
        if finding_codes:
            status = AssuranceStatus.NEEDS_REVIEW
            evidence_class = AssuranceEvidenceClass.ADVISORY
            reason = "Measured delivery evidence identified thumbnail details worth reviewing."
        elif confident:
            status = AssuranceStatus.CLEAR
            evidence_class = AssuranceEvidenceClass.ADVISORY
            reason = "Confident text-like regions clear the configured delivery checks."
        else:
            status = AssuranceStatus.NOT_EVALUATED
            evidence_class = AssuranceEvidenceClass.NOT_EVALUATED
            reason = "No confident text-like region was detected; text-specific checks abstained. Detail-retention measurements remain advisory."
        return ThumbnailAssuranceReport(
            evidence_class=evidence_class,
            status=status,
            source_width=thumbnail.width,
            source_height=thumbnail.height,
            analysis_width=analysis_width,
            analysis_height=analysis_height,
            confident_region_count=len(confident),
            regions=confident,
            delivered_text=[item for item in delivered if item.region_id in {region.region_id for region in confident}],
            surfaces=surface_reports,
            minimum_region_confidence=policy.minimum_region_confidence,
            minimum_delivered_text_height_pixels=policy.minimum_delivered_text_height_pixels,
            minimum_estimated_contrast_ratio=policy.minimum_estimated_contrast_ratio,
            minimum_detail_retention_ratio=policy.minimum_detail_retention_ratio,
            reason=reason,
            finding_codes=finding_codes,
            decode_seconds=decode_seconds,
            text_detection_seconds=text_seconds,
            contrast_seconds=contrast_seconds,
            detail_seconds=detail_seconds,
            total_seconds=perf_counter() - started,
        )


def assurance_findings(report: ThumbnailAssuranceReport) -> list[Any]:
    """Convert only strong advisory conditions into review-only product findings."""

    from releaseseal.models import Finding, FindingSeverity, FindingStatus

    copy = {
        "THUMBNAIL_TEXT_DELIVERY_SMALL": (
            "Thumbnail text may become too small",
            "Confident text-like regions fall below the configured delivered-height floor on a modeled surface.",
            "Review the supplied artwork at the smallest delivery preview.",
        ),
        "THUMBNAIL_TEXT_CONTRAST_REVIEW": (
            "Thumbnail text contrast needs review",
            "A confident text-like region has weak estimated local luminance separation.",
            "Review foreground/background separation in the flagged region.",
        ),
        "THUMBNAIL_TEXT_CHROME_COLLISION": (
            "Thumbnail text overlaps delivery chrome",
            "A confident text-like region intersects the modeled duration-badge area.",
            "Move important artwork away from the modeled duration badge.",
        ),
        "THUMBNAIL_TEXT_EDGE_RISK": (
            "Thumbnail text is close to an unsafe edge",
            "A confident text-like region intersects the modeled unsafe edge area.",
            "Review the artwork with the safe-area overlay enabled.",
        ),
    }
    return [
        Finding(
            code=code,
            severity=FindingSeverity.WARNING,
            status=FindingStatus.NEEDS_REVIEW,
            message=copy[code][1],
            source="package.thumbnail.assurance",
            details={"title": copy[code][0], "category": "package", "evidence_class": report.evidence_class.value},
            suggestion=copy[code][2],
        )
        for code in report.finding_codes
        if code in copy
    ]


def _not_evaluated(thumbnail, width, height, policy, reason, total, *, decode_seconds=0.0):
    return ThumbnailAssuranceReport(
        evidence_class=AssuranceEvidenceClass.NOT_EVALUATED,
        status=AssuranceStatus.NOT_EVALUATED,
        source_width=thumbnail.width,
        source_height=thumbnail.height,
        analysis_width=width,
        analysis_height=height,
        confident_region_count=0,
        minimum_region_confidence=policy.minimum_region_confidence,
        minimum_delivered_text_height_pixels=policy.minimum_delivered_text_height_pixels,
        minimum_estimated_contrast_ratio=policy.minimum_estimated_contrast_ratio,
        minimum_detail_retention_ratio=policy.minimum_detail_retention_ratio,
        reason=reason,
        decode_seconds=decode_seconds,
        text_detection_seconds=0,
        contrast_seconds=0,
        detail_seconds=0,
        total_seconds=total,
    )


def _fit_dimensions(width: int, height: int, maximum: int) -> tuple[int, int]:
    scale = min(maximum / width, maximum / height, 1)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _decode_rgb(path: Path, width: int, height: int, *, ffmpeg_binary: str, timeout_seconds: float) -> bytes | None:
    command = [
        ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path),
        "-vf", f"scale={width}:{height}:flags=lanczos", "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired):
        return None
    expected = width * height * 3
    return result.stdout if result.returncode == 0 and len(result.stdout) == expected else None


def _grayscale(rgb: bytes) -> bytearray:
    result = bytearray(len(rgb) // 3)
    for target, source in enumerate(range(0, len(rgb), 3)):
        result[target] = (77 * rgb[source] + 150 * rgb[source + 1] + 29 * rgb[source + 2]) >> 8
    return result


def _text_candidates(gray: bytearray, width: int, height: int) -> list[tuple[int, int, int, int, float]]:
    edges = bytearray(width * height)
    row_counts = [0] * height
    threshold = 42
    for y in range(1, height - 1):
        row = y * width
        for x in range(1, width - 1):
            index = row + x
            strength = abs(gray[index + 1] - gray[index - 1]) + abs(gray[index + width] - gray[index - width])
            if strength >= threshold:
                edges[index] = 1
                row_counts[y] += 1
    active = [count >= max(6, width // 64) and count <= width * .72 for count in row_counts]
    bands = _runs_with_gap(active, maximum_gap=2)
    candidates = []
    for top, bottom in bands:
        band_height = bottom - top
        if band_height < 3 or band_height > max(54, height // 3):
            continue
        columns = [sum(edges[y * width + x] for y in range(top, bottom)) for x in range(width)]
        active_columns = [value >= max(1, band_height // 7) for value in columns]
        raw_runs = _runs_with_gap(active_columns, maximum_gap=0)
        if len(raw_runs) < 3:
            continue
        left = raw_runs[0][0]
        right = raw_runs[-1][1]
        region_width = right - left
        if region_width < 14 or region_width / band_height < 1.1:
            continue
        edge_count = sum(edges[y * width + x] for y in range(top, bottom) for x in range(left, right))
        density = edge_count / max(1, region_width * band_height)
        values = [gray[y * width + x] for y in range(top, bottom) for x in range(left, right)]
        span = _percentile(values, .9) - _percentile(values, .1)
        confidence = min(1.0, .25 + .20 * min(1, (region_width / band_height - 1) / 5) + .25 * min(1, len(raw_runs) / 12) + .15 * min(1, density / .12) + .15 * min(1, span / 100))
        candidates.append((left, top, region_width, band_height, round(confidence, 4)))
    return _merge_vertical_duplicates(candidates)


def _segmentation_text_candidates(
    gray: bytearray, width: int, height: int
) -> list[tuple[int, int, int, int, float]]:
    """Locate strongly grouped glyph-like components after primary abstention.

    The fallback deliberately requires several similarly sized, baseline-aligned
    components. This recognizes text laid over a coherent light/dark substrate
    without interpreting isolated photographic edges as lettering.
    """

    radius = max(3, round(min(width, height) / 45))
    integral = _integral_image(gray, width, height)
    masks = [bytearray(width * height), bytearray(width * height)]
    for y in range(height):
        for x in range(width):
            local = _local_mean(integral, width, height, x, y, radius)
            value = gray[y * width + x]
            masks[0][y * width + x] = value <= 105 and local - value >= 34
            masks[1][y * width + x] = value >= 180 and value - local >= 34

    candidates: list[tuple[int, int, int, int, float]] = []
    for polarity, mask in enumerate(masks):
        components = [
            item for item in _connected_components(mask, width, height)
            if _glyph_component(item, width, height)
        ]
        candidates.extend(_group_glyph_components(
            components, gray, width, height, background_is_light=polarity == 0
        ))
    return _merge_vertical_duplicates(candidates)


def _integral_image(gray: bytearray, width: int, height: int) -> list[int]:
    stride = width + 1
    integral = [0] * (stride * (height + 1))
    for y in range(height):
        row_sum = 0
        for x in range(width):
            row_sum += gray[y * width + x]
            integral[(y + 1) * stride + x + 1] = integral[y * stride + x + 1] + row_sum
    return integral


def _local_mean(
    integral: list[int], width: int, height: int, x: int, y: int, radius: int
) -> float:
    left, right = max(0, x - radius), min(width, x + radius + 1)
    top, bottom = max(0, y - radius), min(height, y + radius + 1)
    stride = width + 1
    total = (
        integral[bottom * stride + right]
        - integral[top * stride + right]
        - integral[bottom * stride + left]
        + integral[top * stride + left]
    )
    return total / ((right - left) * (bottom - top))


def _connected_components(
    mask: bytearray, width: int, height: int
) -> list[tuple[int, int, int, int, int]]:
    visited = bytearray(width * height)
    result: list[tuple[int, int, int, int, int]] = []
    for start, active in enumerate(mask):
        if not active or visited[start]:
            continue
        stack = [start]
        visited[start] = 1
        left = right = start % width
        top = bottom = start // width
        area = 0
        while stack:
            index = stack.pop()
            x, y = index % width, index // width
            area += 1
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            for next_y in range(max(0, y - 1), min(height, y + 2)):
                for next_x in range(max(0, x - 1), min(width, x + 2)):
                    neighbor = next_y * width + next_x
                    if mask[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        stack.append(neighbor)
        result.append((left, top, right - left + 1, bottom - top + 1, area))
    return result


def _glyph_component(
    component: tuple[int, int, int, int, int], width: int, height: int
) -> bool:
    _, _, box_width, box_height, area = component
    fill = area / (box_width * box_height)
    return (
        2 <= box_width <= max(8, width // 7)
        and 3 <= box_height <= max(10, height // 4)
        and .08 <= fill <= .86
        and .12 <= box_width / box_height <= 2.2
    )


def _group_glyph_components(
    components: list[tuple[int, int, int, int, int]],
    gray: bytearray,
    width: int,
    height: int,
    *,
    background_is_light: bool,
) -> list[tuple[int, int, int, int, float]]:
    groups: list[list[tuple[int, int, int, int, int]]] = []
    for component in sorted(components, key=lambda item: (item[1] + item[3] / 2, item[0])):
        center = component[1] + component[3] / 2
        matching = next((
            group for group in groups
            if abs(center - _median([item[1] + item[3] / 2 for item in group]))
            <= max(2.5, _median([item[3] for item in group]) * .42)
            and .45 <= component[3] / max(1, _median([item[3] for item in group])) <= 2.2
        ), None)
        if matching is None:
            matching = []
            groups.append(matching)
        matching.append(component)

    result: list[tuple[int, int, int, int, float]] = []
    for group in groups:
        ordered = sorted(group, key=lambda item: item[0])
        typical_height = _median([item[3] for item in ordered])
        linked: list[list[tuple[int, int, int, int, int]]] = [[]]
        for item in ordered:
            previous = linked[-1][-1] if linked[-1] else None
            gap = item[0] - (previous[0] + previous[2]) if previous else 0
            if previous and gap > typical_height * 1.8:
                linked.append([])
            linked[-1].append(item)
        for line in linked:
            if len(line) < 4:
                continue
            left = min(item[0] for item in line)
            top = min(item[1] for item in line)
            right = max(item[0] + item[2] for item in line)
            bottom = max(item[1] + item[3] for item in line)
            box_width, box_height = right - left, bottom - top
            if box_width < max(15, width * .055) or box_width / box_height < 1.45:
                continue
            baselines = [item[1] + item[3] for item in line]
            baseline_spread = max(baselines) - min(baselines)
            heights = [item[3] for item in line]
            height_spread = max(heights) - min(heights)
            values = [gray[y * width + x] for y in range(top, bottom) for x in range(left, right)]
            substrate_share = (
                sum(value >= 150 for value in values) / len(values)
                if background_is_light else
                sum(value <= 125 for value in values) / len(values)
            )
            if substrate_share < .45:
                continue
            span = _percentile(values, .9) - _percentile(values, .1)
            alignment = max(0.0, 1 - baseline_spread / max(1, typical_height))
            consistency = max(0.0, 1 - height_spread / max(1, typical_height * 1.5))
            confidence = min(
                .92,
                .48
                + .15 * min(1, (len(line) - 3) / 6)
                + .12 * alignment
                + .10 * consistency
                + .10 * min(1, span / 100)
                + .05 * min(1, (substrate_share - .45) / .30),
            )
            if confidence >= .72:
                padding = max(1, round(typical_height * .12))
                left, top = max(0, left - padding), max(0, top - padding)
                right, bottom = min(width, right + padding), min(height, bottom + padding)
                result.append((left, top, right - left, bottom - top, round(confidence, 4)))
    return result[:12]


def _median(values: list[float | int]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _runs_with_gap(active: list[bool], *, maximum_gap: int) -> list[tuple[int, int]]:
    indexes = [index for index, value in enumerate(active) if value]
    if not indexes:
        return []
    runs = []
    start = previous = indexes[0]
    for index in indexes[1:]:
        if index - previous > maximum_gap + 1:
            runs.append((start, previous + 1))
            start = index
        previous = index
    runs.append((start, previous + 1))
    return runs


def _merge_vertical_duplicates(candidates):
    result = []
    for candidate in sorted(candidates, key=lambda item: (item[1], item[0])):
        if result and (
            _box_overlap(candidate[:4], result[-1][:4]) > .65
            or _same_text_line_fragments(candidate[:4], result[-1][:4])
        ):
            left = min(candidate[0], result[-1][0])
            top = min(candidate[1], result[-1][1])
            right = max(candidate[0] + candidate[2], result[-1][0] + result[-1][2])
            bottom = max(candidate[1] + candidate[3], result[-1][1] + result[-1][3])
            result[-1] = (left, top, right - left, bottom - top, max(candidate[4], result[-1][4]))
        else:
            result.append(candidate)
    return result[:12]


def _regions(candidates, gray, width, height, source_width, source_height, *, detector="PRIMARY"):
    result = []
    for index, (x, y, box_width, box_height, confidence) in enumerate(candidates, 1):
        values = [gray[row * width + column] for row in range(y, y + box_height) for column in range(x, x + box_width)]
        low, high = _percentile(values, .15), _percentile(values, .85)
        ratio = (_linear_luminance(high / 255) + .05) / (_linear_luminance(low / 255) + .05)
        scale_x, scale_y = source_width / width, source_height / height
        source_x, source_y = round(x * scale_x), round(y * scale_y)
        source_box_width = min(source_width - source_x, max(1, round(box_width * scale_x)))
        source_box_height = min(source_height - source_y, max(1, round(box_height * scale_y)))
        result.append(TextLikeRegion(
            region_id=f"text-{index}",
            box=NormalizedBox(x=x / width, y=y / height, width=box_width / width, height=box_height / height),
            source_x=source_x,
            source_y=source_y,
            source_width=source_box_width,
            source_height=source_box_height,
            estimated_cap_height_pixels=source_box_height,
            confidence=confidence,
            estimated_local_contrast_ratio=round(max(1, ratio), 2),
            contrast_evidence_confidence=round(min(confidence, .55 + min(1, (high - low) / 80) * .45), 4),
            detector=detector,
        ))
    return result


def _finding_codes(regions, delivered, surfaces, policy):
    codes = []
    if regions:
        smallest = min(surface.display_height for surface in surfaces)
        smallest_reports = [surface for surface in surfaces if surface.display_height == smallest]
        total_area = sum(region.box.width * region.box.height for region in regions)
        meaningful_small_region = any(
            item.delivered_height_pixels < policy.minimum_delivered_text_height_pixels
            and next(region.box.width * region.box.height for region in regions if region.region_id == item.region_id) / total_area >= .05
            for item in delivered
            if any(surface.surface_id == item.surface_id for surface in smallest_reports)
        )
        if any((surface.unreadable_text_area_share or 0) >= .30 for surface in smallest_reports) or meaningful_small_region:
            codes.append("THUMBNAIL_TEXT_DELIVERY_SMALL")
        if any(region.estimated_local_contrast_ratio < policy.minimum_estimated_contrast_ratio and region.contrast_evidence_confidence >= policy.minimum_region_confidence for region in regions):
            codes.append("THUMBNAIL_TEXT_CONTRAST_REVIEW")
        if any(item.badge_overlap_fraction >= .10 for item in delivered):
            codes.append("THUMBNAIL_TEXT_CHROME_COLLISION")
        if any(item.edge_safety is EdgeSafetyStatus.INTERSECTS_UNSAFE_AREA for item in delivered):
            codes.append("THUMBNAIL_TEXT_EDGE_RISK")
    return codes


def _edge_safety(box: NormalizedBox, margin: float) -> EdgeSafetyStatus:
    distance = min(box.x, box.y, 1 - box.x - box.width, 1 - box.y - box.height)
    if distance < margin:
        return EdgeSafetyStatus.INTERSECTS_UNSAFE_AREA
    if distance < margin * 1.75:
        return EdgeSafetyStatus.NEAR_EDGE
    return EdgeSafetyStatus.CLEAR


def _overlap_fraction(box: NormalizedBox, surface: Any) -> float:
    left = max(box.x, surface.badge_x)
    top = max(box.y, surface.badge_y)
    right = min(box.x + box.width, surface.badge_x + surface.badge_width)
    bottom = min(box.y + box.height, surface.badge_y + surface.badge_height)
    intersection = max(0, right - left) * max(0, bottom - top)
    return min(1, intersection / (box.width * box.height))


def _box_overlap(left, right):
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    area = max(0, min(lx + lw, rx + rw) - max(lx, rx)) * max(0, min(ly + lh, ry + rh) - max(ly, ry))
    return area / max(1, min(lw * lh, rw * rh))


def _same_text_line_fragments(left, right):
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    horizontal_overlap = max(0, min(lx + lw, rx + rw) - max(lx, rx)) / max(1, min(lw, rw))
    vertical_gap = max(0, max(ly, ry) - min(ly + lh, ry + rh))
    return horizontal_overlap >= .65 and vertical_gap <= max(lh, rh) * .5


def _detail_retention(gray: bytearray, width: int, height: int, target_width: int, target_height: int) -> float:
    if target_width >= width and target_height >= height:
        return 1.0
    reduced = _resize_bilinear(gray, width, height, target_width, target_height)
    restored = _resize_bilinear(reduced, target_width, target_height, width, height)
    error = sum(abs(left - right) for left, right in zip(gray, restored)) / len(gray)
    return max(0.0, min(1.0, 1 - error / 48.0))


def _resize_bilinear(source, source_width, source_height, target_width, target_height):
    if source_width == target_width and source_height == target_height:
        return bytearray(source)
    target = bytearray(target_width * target_height)
    for y in range(target_height):
        source_y = (y + .5) * source_height / target_height - .5
        y0 = max(0, min(source_height - 1, math.floor(source_y)))
        y1 = min(source_height - 1, y0 + 1)
        fy = max(0.0, source_y - y0)
        for x in range(target_width):
            source_x = (x + .5) * source_width / target_width - .5
            x0 = max(0, min(source_width - 1, math.floor(source_x)))
            x1 = min(source_width - 1, x0 + 1)
            fx = max(0.0, source_x - x0)
            top = source[y0 * source_width + x0] * (1 - fx) + source[y0 * source_width + x1] * fx
            bottom = source[y1 * source_width + x0] * (1 - fx) + source[y1 * source_width + x1] * fx
            target[y * target_width + x] = round(top * (1 - fy) + bottom * fy)
    return target


def _percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))]


def _linear_luminance(value: float) -> float:
    return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
