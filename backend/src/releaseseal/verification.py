"""Closed-loop verification for ReleaseSeal-produced REMOVE_RANGE repairs."""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from releaseseal.config import VerificationConfig
from releaseseal.captions import CaptionCue, parse_caption_text, serialize_caption_cues
from releaseseal.media import MediaInspection, MediaInspector, require_media_tool
from releaseseal.models import Finding, PreflightReport, ScanCompleteness
from releaseseal.repair_models import RepairOperation, RepairProposal
from releaseseal.repairs import RepairError, validate_repair_operations
from releaseseal.verification_models import (
    FindingComparison,
    FindingComparisonStatus,
    RepairIntegrityResult,
    RepairVerificationStatus,
    ReviewReelEntry,
    ReviewReelManifest,
    UnexpectedChangeInterval,
    VerificationReport,
)

TIMESTAMP_TOLERANCE_SECONDS = 1.0
DURATION_TOLERANCE_SECONDS = 0.35
REGRESSION_SAMPLE_FPS = 2.0
REGRESSION_MAXIMUM_SAMPLES = 1200
REGRESSION_WIDTH = 64
REGRESSION_HEIGHT = 36
REGRESSION_MEAN_DIFFERENCE_THRESHOLD = 18.0
REGRESSION_PIXEL_DIFFERENCE_THRESHOLD = 24
REGRESSION_CHANGED_PIXEL_FRACTION = 0.20
EDIT_BOUNDARY_TOLERANCE_SECONDS = 0.75
REVIEW_CONTEXT_SECONDS = 3.0
REVIEW_REEL_MAXIMUM_SEGMENTS = 12
REVIEW_REEL_MAXIMUM_DURATION_SECONDS = 180.0


@dataclass(frozen=True)
class TimelineSegment:
    original_start: float
    original_end: float
    repaired_start: float
    repaired_end: float


class TimelineTransform:
    """Map timestamps between the original and ripple-shortened timelines."""

    def __init__(self, original_duration: float, operations: list[RepairOperation]):
        self.original_duration = original_duration
        if not math.isfinite(original_duration) or original_duration <= 0:
            raise RepairError("verification_media_invalid", "Timeline mapping requires a usable original duration.")
        self.operations = validate_repair_operations(operations, original_duration) if operations else []
        self.segments: list[TimelineSegment] = []
        original_cursor = 0.0
        repaired_cursor = 0.0
        for operation in self.operations:
            if operation.start_seconds > original_cursor:
                length = operation.start_seconds - original_cursor
                self.segments.append(TimelineSegment(original_cursor, operation.start_seconds, repaired_cursor, repaired_cursor + length))
                repaired_cursor += length
            original_cursor = operation.end_seconds
        if original_cursor < original_duration:
            length = original_duration - original_cursor
            self.segments.append(TimelineSegment(original_cursor, original_duration, repaired_cursor, repaired_cursor + length))
        self.expected_duration = repaired_cursor + max(0.0, original_duration - original_cursor)

    def original_to_repaired(self, timestamp: float) -> float | None:
        if not math.isfinite(timestamp) or timestamp < 0 or timestamp > self.original_duration:
            return None
        for segment in self.segments:
            if segment.original_start <= timestamp < segment.original_end:
                return segment.repaired_start + timestamp - segment.original_start
        if timestamp == self.original_duration:
            return self.expected_duration
        return None

    def repaired_to_original(self, timestamp: float) -> float | None:
        if not math.isfinite(timestamp) or timestamp < 0 or timestamp > self.expected_duration:
            return None
        for segment in self.segments:
            if segment.repaired_start <= timestamp < segment.repaired_end:
                return segment.original_start + timestamp - segment.repaired_start
        if timestamp == self.expected_duration:
            return self.original_duration
        return None

    def interval_to_repaired(self, start: float, end: float) -> tuple[float, float] | None:
        if end <= start:
            return None
        pieces: list[tuple[float, float]] = []
        for segment in self.segments:
            left, right = max(start, segment.original_start), min(end, segment.original_end)
            if right > left:
                mapped_start = segment.repaired_start + left - segment.original_start
                pieces.append((mapped_start, mapped_start + right - left))
        if not pieces:
            return None
        return pieces[0][0], pieces[-1][1]

    def interval_removed(self, start: float, end: float) -> bool:
        return end > start and self.interval_to_repaired(start, end) is None

    @property
    def repaired_cut_boundaries(self) -> list[float]:
        return [operation.start_seconds - sum(max(0.0, min(operation.start_seconds, prior.end_seconds) - prior.start_seconds) for prior in self.operations if prior.end_seconds <= operation.start_seconds) for operation in self.operations]


def transform_caption_cues(cues: list[CaptionCue], transform: TimelineTransform) -> list[CaptionCue]:
    """Map surviving caption text onto the repaired timeline."""

    transformed: list[CaptionCue] = []
    for cue in cues:
        if (
            not math.isfinite(cue.start_seconds)
            or not math.isfinite(cue.end_seconds)
            or cue.start_seconds < 0
            or cue.end_seconds <= cue.start_seconds
            or cue.end_seconds > transform.original_duration
        ):
            raise RepairError("verification_captions_invalid", "Captions could not be mapped onto the repaired timeline.")
        interval = transform.interval_to_repaired(cue.start_seconds, cue.end_seconds)
        if interval is None:
            continue
        start, end = interval
        end = min(end, transform.expected_duration)
        if start < 0 or end <= start or end > transform.expected_duration:
            raise RepairError("verification_captions_invalid", "Captions could not be mapped onto the repaired timeline.")
        transformed.append(CaptionCue(
            start_seconds=start,
            end_seconds=end,
            text=cue.text,
            identifier=cue.identifier,
            source_format=cue.source_format,
            line_number=cue.line_number,
        ))
    return sorted(transformed, key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.identifier or ""))


def transform_caption_file(
    source_path: str | Path,
    destination_path: str | Path,
    *,
    original_duration: float,
    operations: list[RepairOperation],
) -> Path:
    """Create a non-destructive repaired-timeline caption file for verification."""

    source = Path(source_path)
    try:
        parsed = parse_caption_text(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError) as exc:
        raise RepairError("verification_captions_invalid", "Captions could not be prepared for repair verification.") from exc
    if parsed.issues or parsed.source_format not in {"srt", "vtt"}:
        # Preserve existing parser diagnostics when valid cues cannot be transformed safely.
        return source
    transform = TimelineTransform(original_duration, operations)
    cues = transform_caption_cues(parsed.cues, transform)
    destination = Path(destination_path)
    try:
        destination.write_text(
            serialize_caption_cues(cues, source_format=parsed.source_format),
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        raise RepairError("verification_captions_invalid", "Captions could not be prepared for repair verification.") from exc
    return destination


def verify_repair(
    original_path: str | Path,
    repaired_path: str | Path,
    operations: list[RepairOperation],
    original_report: PreflightReport,
    repaired_report: PreflightReport,
    settings: VerificationConfig | None = None,
) -> VerificationReport:
    settings = settings or VerificationConfig()
    original_media = MediaInspector().inspect(original_path)
    repaired_media = MediaInspector().inspect(repaired_path)
    if original_media.duration_seconds is None or repaired_media.duration_seconds is None:
        raise RepairError("verification_media_invalid", "Repair verification requires readable media durations.")
    validated = validate_repair_operations(operations, original_media.duration_seconds)
    transform = TimelineTransform(original_media.duration_seconds, validated)
    integrity = _verify_integrity(original_media, repaired_media, transform, validated, original_report.repair_plan.proposals)
    resolved, remaining, new = compare_findings(original_report, repaired_report, transform, validated)
    unexpected = detect_unexpected_visual_changes(original_path, repaired_path, transform, settings=settings)
    manifest = build_review_reel_manifest(repaired_media.duration_seconds, validated, transform, remaining, new, unexpected, settings=settings)
    incomplete = repaired_report.scan_completeness is not ScanCompleteness.COMPLETE
    status = (
        RepairVerificationStatus.INCOMPLETE if incomplete
        else RepairVerificationStatus.NEEDS_REVIEW if (not integrity.passed or remaining or new or unexpected)
        else RepairVerificationStatus.VERIFIED
    )
    return VerificationReport(
        status=status,
        approved_repair_count=len(validated),
        resolved=resolved,
        remaining=remaining,
        new=new,
        unexpected_changes=unexpected,
        original_duration_seconds=original_media.duration_seconds,
        repaired_duration_seconds=repaired_media.duration_seconds,
        expected_duration_seconds=transform.expected_duration,
        integrity=integrity,
        repaired_preflight_report=repaired_report,
        regression_analysis_completeness=ScanCompleteness.COMPLETE,
        review_reel_manifest=manifest,
        review_reel_available=bool(manifest.entries),
        limitations=["Unexpected-change analysis compares bounded low-resolution visual samples; audio verification covers readability, stream presence, and duration rather than waveform identity."],
    )


def compare_findings(original: PreflightReport, repaired: PreflightReport, transform: TimelineTransform, operations: list[RepairOperation]) -> tuple[list[FindingComparison], list[FindingComparison], list[FindingComparison]]:
    unused = list(repaired.findings)
    resolved: list[FindingComparison] = []
    remaining: list[FindingComparison] = []
    targeted = {(proposal.finding_code, proposal.start_seconds, proposal.end_seconds): proposal for proposal in original.repair_plan.proposals if proposal.operation in operations}
    for finding in original.findings:
        mapped = _mapped_finding_interval(finding, transform)
        proposal = targeted.get((finding.code, finding.timestamp_start_seconds, finding.timestamp_end_seconds))
        if proposal is not None and finding.timestamp_start_seconds is not None and finding.timestamp_end_seconds is not None and transform.interval_removed(finding.timestamp_start_seconds, finding.timestamp_end_seconds):
            resolved.append(_comparison(FindingComparisonStatus.RESOLVED, finding, None, mapped, True, "The approved operation removed the complete targeted interval."))
            continue
        match = _take_matching_finding(finding, mapped, unused)
        if match is not None:
            remaining.append(_comparison(FindingComparisonStatus.REMAINING, finding, match, mapped, False, "The same finding remains at its expected repaired-timeline location."))
        elif finding.source.startswith("ai."):
            remaining.append(_comparison(FindingComparisonStatus.REMAINING, finding, None, mapped, False, "The repaired AI review did not repeat this observation; absence alone is not deterministic proof that it was resolved."))
        else:
            resolved.append(_comparison(FindingComparisonStatus.RESOLVED, finding, None, mapped, False, "The repaired scan no longer reports this deterministic finding."))
    new = [
        _comparison(
            FindingComparisonStatus.NEW,
            None,
            finding,
            _finding_interval(finding),
            False,
            "This finding was newly detected during the repaired scan; that alone does not show the repair caused it.",
        )
        for finding in unused
    ]
    return resolved, remaining, new


def detect_unexpected_visual_changes(original_path: str | Path, repaired_path: str | Path, transform: TimelineTransform, *, settings: VerificationConfig | None = None) -> list[UnexpectedChangeInterval]:
    settings = settings or VerificationConfig()
    fps = min(settings.visual_sample_fps, max(0.1, settings.maximum_visual_samples / max(transform.original_duration, 0.1)))
    # Sample the original through the same virtual ripple edit used to render
    # the repair. Sampling the uncut original on its own fixed grid introduces
    # a phase offset whenever a removed duration is not an exact sample period;
    # one side of an ordinary hard cut can then be compared with the other.
    original_frames = _sample_frames(
        original_path,
        fps,
        settings.maximum_visual_samples,
        timeline_segments=transform.segments if transform.operations else None,
    )
    repaired_frames = _sample_frames(repaired_path, fps, settings.maximum_visual_samples)
    changed: list[tuple[float, float]] = []
    boundaries = transform.repaired_cut_boundaries
    for index, repaired_frame in enumerate(repaired_frames):
        repaired_time = index / fps
        if any(abs(repaired_time - boundary) <= settings.edit_boundary_tolerance_seconds for boundary in boundaries):
            continue
        # original_frames already represents the original media after applying
        # the approved ripple transform, so both sampled lists share one grid.
        original_index = min(index, len(original_frames) - 1)
        if original_index < 0 or not original_frames:
            continue
        mean, fraction = _frame_difference(original_frames[original_index], repaired_frame, settings.changed_pixel_difference_threshold)
        if mean >= settings.visual_mean_difference_threshold and fraction >= settings.changed_pixel_fraction_threshold:
            changed.append((repaired_time, mean))
    return _merge_changed_samples(changed, fps)


def build_review_reel_manifest(repaired_duration: float, operations: list[RepairOperation], transform: TimelineTransform, remaining: list[FindingComparison], new: list[FindingComparison], unexpected: list[UnexpectedChangeInterval], *, settings: VerificationConfig | None = None) -> ReviewReelManifest:
    settings = settings or VerificationConfig()
    candidates: list[tuple[int, float, float, str, str, str | None]] = []
    for change in unexpected:
        candidates.append((0, change.start_seconds, change.end_seconds, "Unexpected visual change", "unexpected", None))
    for item in [*remaining, *new]:
        finding = item.repaired_finding
        if finding and finding.timestamp_start_seconds is not None:
            end = finding.timestamp_end_seconds or finding.timestamp_start_seconds + 0.5
            label = "Detected on repaired scan" if item.status is FindingComparisonStatus.NEW else "Still needs attention"
            candidates.append((1, finding.timestamp_start_seconds, end, f"{label}: {finding.message}", "finding", finding.code))
    for index, operation in enumerate(operations):
        boundary = transform.original_to_repaired(operation.end_seconds)
        if boundary is None:
            boundary = operation.start_seconds - sum(prior.end_seconds - prior.start_seconds for prior in operations[:index])
        candidates.append((2, boundary, boundary + 0.25, "Approved range removed", "repair", f"repair-{index + 1}"))
    windows = [(priority, max(0.0, start - settings.review_reel_context_seconds), min(repaired_duration, end + settings.review_reel_context_seconds), reason, category, source_id) for priority, start, end, reason, category, source_id in candidates]
    windows.sort(key=lambda item: (item[0], item[1], item[2]))
    selected: list[tuple[float, float, list[str], str, str | None]] = []
    total = 0.0
    for _, start, end, reason, category, source_id in windows:
        if end <= start:
            continue
        overlap = next((item for item in selected if start <= item[1] and end >= item[0]), None)
        if overlap:
            old_duration = overlap[1] - overlap[0]
            overlap_index = selected.index(overlap)
            merged = (min(overlap[0], start), max(overlap[1], end), [*overlap[2], reason], overlap[3], overlap[4])
            if total - old_duration + merged[1] - merged[0] <= settings.review_reel_maximum_duration_seconds:
                selected[overlap_index] = merged
                total = total - old_duration + merged[1] - merged[0]
            continue
        duration = end - start
        if len(selected) >= settings.review_reel_maximum_segments or total + duration > settings.review_reel_maximum_duration_seconds:
            continue
        selected.append((start, end, [reason], category, source_id)); total += duration
    selected.sort(key=lambda item: item[0])
    entries: list[ReviewReelEntry] = []
    reel_cursor = 0.0
    for start, end, reasons, category, source_id in selected:
        entries.append(ReviewReelEntry(reel_start_seconds=reel_cursor, reel_end_seconds=reel_cursor + end - start, source_start_seconds=start, source_end_seconds=end, reason="; ".join(dict.fromkeys(reasons)), category=category, source_id=source_id))
        reel_cursor += end - start
    return ReviewReelManifest(entries=entries, total_duration_seconds=reel_cursor)


def _verify_integrity(original: MediaInspection, repaired: MediaInspection, transform: TimelineTransform, operations: list[RepairOperation], proposals: list[RepairProposal]) -> RepairIntegrityResult:
    duration_matches = repaired.duration_seconds is not None and abs(repaired.duration_seconds - transform.expected_duration) <= DURATION_TOLERANCE_SECONDS
    streams_match = repaired.has_video and repaired.has_audio == original.has_audio
    resolution_matches = repaired.width == original.width and repaired.height == original.height
    references_survive = True
    for proposal in proposals:
        if proposal.operation in operations and proposal.original_start_seconds is not None and proposal.original_end_seconds is not None:
            references_survive = references_survive and transform.interval_to_repaired(proposal.original_start_seconds, proposal.original_end_seconds) is not None
    passed = duration_matches and streams_match and resolution_matches and references_survive
    return RepairIntegrityResult(passed=passed, duration_matches=duration_matches, streams_match=streams_match, resolution_matches=resolution_matches, operations_verified=len(operations), reference_intervals_survived=references_survive, explanation="Rendered duration, stream presence, resolution, and surviving reference intervals match the approved operation plan." if passed else "The rendered export differs from one or more deterministic repair expectations.")


def _sample_frames(
    path: str | Path,
    fps: float,
    maximum_samples: int,
    *,
    timeline_segments: list[TimelineSegment] | None = None,
) -> list[bytes]:
    executable = require_media_tool("ffmpeg")
    sampling_filter = (
        f"fps={fps:.6f},scale={REGRESSION_WIDTH}:{REGRESSION_HEIGHT}:flags=area,format=gray"
    )
    command = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(Path(path).resolve()),
    ]
    if timeline_segments:
        parts: list[str] = []
        inputs: list[str] = []
        for index, segment in enumerate(timeline_segments):
            parts.append(
                f"[0:v:0]trim=start={segment.original_start:.6f}:end={segment.original_end:.6f},"
                f"setpts=PTS-STARTPTS[v{index}]"
            )
            inputs.append(f"[v{index}]")
        parts.append(
            "".join(inputs)
            + f"concat=n={len(inputs)}:v=1:a=0,{sampling_filter}[sampled]"
        )
        command.extend(["-filter_complex", ";".join(parts), "-map", "[sampled]"])
    else:
        command.extend(["-vf", sampling_filter])
    command.extend(["-frames:v", str(maximum_samples), "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"])
    try:
        completed = subprocess.run(command, capture_output=True, check=False, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RepairError("verification_regression_failed", "Visual regression sampling could not complete.") from exc
    if completed.returncode != 0:
        raise RepairError("verification_regression_failed", "Visual regression sampling could not complete.")
    size = REGRESSION_WIDTH * REGRESSION_HEIGHT
    return [completed.stdout[index:index + size] for index in range(0, len(completed.stdout) - size + 1, size)]


def _frame_difference(left: bytes, right: bytes, pixel_threshold: int) -> tuple[float, float]:
    differences = [abs(a - b) for a, b in zip(left, right)]
    if not differences:
        return 255.0, 1.0
    return sum(differences) / len(differences), sum(value >= pixel_threshold for value in differences) / len(differences)


def _merge_changed_samples(changed: list[tuple[float, float]], fps: float) -> list[UnexpectedChangeInterval]:
    if not changed:
        return []
    groups: list[list[tuple[float, float]]] = [[changed[0]]]
    for sample in changed[1:]:
        if sample[0] - groups[-1][-1][0] <= 1.5 / fps:
            groups[-1].append(sample)
        else:
            groups.append([sample])
    return [UnexpectedChangeInterval(start_seconds=group[0][0], end_seconds=group[-1][0] + 1 / fps, maximum_mean_difference=max(item[1] for item in group), sample_count=len(group)) for group in groups]


def _mapped_finding_interval(finding: Finding, transform: TimelineTransform) -> tuple[float, float] | None:
    if finding.timestamp_start_seconds is None:
        return None
    end = finding.timestamp_end_seconds or finding.timestamp_start_seconds + 0.001
    return transform.interval_to_repaired(finding.timestamp_start_seconds, end)


def _finding_interval(finding: Finding) -> tuple[float, float] | None:
    if finding.timestamp_start_seconds is None:
        return None
    return finding.timestamp_start_seconds, finding.timestamp_end_seconds or finding.timestamp_start_seconds


def _take_matching_finding(original: Finding, mapped: tuple[float, float] | None, candidates: list[Finding]) -> Finding | None:
    for candidate in candidates:
        if candidate.code != original.code:
            continue
        if original.timestamp_start_seconds is None and candidate.timestamp_start_seconds is None:
            candidates.remove(candidate); return candidate
        if mapped is None or candidate.timestamp_start_seconds is None:
            continue
        candidate_end = candidate.timestamp_end_seconds or candidate.timestamp_start_seconds
        if candidate.timestamp_start_seconds <= mapped[1] + TIMESTAMP_TOLERANCE_SECONDS and candidate_end >= mapped[0] - TIMESTAMP_TOLERANCE_SECONDS:
            candidates.remove(candidate); return candidate
    return None


def _comparison(status: FindingComparisonStatus, original: Finding | None, repaired: Finding | None, mapped: tuple[float, float] | None, deterministic: bool, explanation: str) -> FindingComparison:
    return FindingComparison(status=status, original_finding=original, repaired_finding=repaired, expected_repaired_start_seconds=mapped[0] if mapped else None, expected_repaired_end_seconds=mapped[1] if mapped else None, deterministically_verified=deterministic, explanation=explanation)
