"""Deterministic SRT/WebVTT parsing, caption QA, and interval comparison."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from creator_preflight.config import CaptionRuleConfig, TranscriptionConfig
from creator_preflight.models import (
    CaptionSummary,
    CheckResult,
    Finding,
    FindingSeverity,
    FindingStatus,
)

_SRT_TIMESTAMP = re.compile(
    r"^(?P<hours>\d+):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d),(?P<millis>\d{3})$"
)
_VTT_TIMESTAMP = re.compile(
    r"^(?:(?P<hours>\d+):)?(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d)\.(?P<millis>\d{3})$"
)
_SRT_TIMING = re.compile(r"^\s*(?P<start>\S+)\s*-->\s*(?P<end>\S+)\s*$")
_VTT_TIMING = re.compile(
    r"^\s*(?P<start>\S+)\s*-->\s*(?P<end>\S+)(?:\s+.*)?$"
)


@dataclass(frozen=True)
class CaptionCue:
    start_seconds: float
    end_seconds: float
    text: str
    identifier: str | None = None
    source_format: str = "unknown"
    line_number: int | None = None


@dataclass(frozen=True)
class SpeechSegment:
    start_seconds: float
    end_seconds: float
    text: str = ""


@dataclass(frozen=True)
class CaptionParseIssue:
    kind: str
    message: str
    line_number: int | None = None
    identifier: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None


@dataclass(frozen=True)
class CaptionParseResult:
    source_format: str
    cues: list[CaptionCue]
    issues: list[CaptionParseIssue]


@dataclass(frozen=True)
class CaptionEvaluation:
    cues: list[CaptionCue]
    findings: list[Finding]
    checks: list[CheckResult]
    summary: CaptionSummary


def parse_caption_text(text: str) -> CaptionParseResult:
    """Parse caption content by syntax, not filename extension."""

    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return CaptionParseResult(source_format="unknown", cues=[], issues=[])
    first_nonempty = next(
        (line.strip() for line in normalized.splitlines() if line.strip()), ""
    )
    if first_nonempty == "WEBVTT" or first_nonempty.startswith("WEBVTT "):
        return _parse_webvtt(normalized)
    if "-->" in normalized:
        return _parse_srt(normalized)
    return CaptionParseResult(
        source_format="unknown",
        cues=[],
        issues=[CaptionParseIssue("parse", "No supported SRT or WebVTT cue timing was found.")],
    )


def serialize_caption_cues(cues: list[CaptionCue], *, source_format: str) -> str:
    """Serialize validated cues without retaining parser-specific state or raw blobs."""

    if source_format not in {"srt", "vtt"}:
        raise ValueError("caption serialization requires SRT or WebVTT input")
    ordered = sorted(cues, key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.identifier or ""))
    blocks: list[str] = []
    for index, cue in enumerate(ordered, start=1):
        if (
            not math.isfinite(cue.start_seconds)
            or not math.isfinite(cue.end_seconds)
            or cue.start_seconds < 0
            or cue.end_seconds <= cue.start_seconds
        ):
            raise ValueError("caption cues must contain finite positive intervals")
        if source_format == "srt":
            timing = f"{_serialize_timestamp(cue.start_seconds, ',')} --> {_serialize_timestamp(cue.end_seconds, ',')}"
            blocks.append(f"{index}\n{timing}\n{cue.text}")
        else:
            identifier = f"{cue.identifier}\n" if cue.identifier else ""
            timing = f"{_serialize_timestamp(cue.start_seconds, '.')} --> {_serialize_timestamp(cue.end_seconds, '.')}"
            blocks.append(f"{identifier}{timing}\n{cue.text}")
    prefix = "WEBVTT\n\n" if source_format == "vtt" else ""
    return prefix + "\n\n".join(blocks) + ("\n" if blocks else "")


def _serialize_timestamp(seconds: float, separator: str) -> str:
    total_milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"


def inspect_caption_file(
    path: str | Path,
    *,
    media_duration_seconds: float | None,
    config: CaptionRuleConfig,
) -> CaptionEvaluation:
    """Read, parse, validate, and summarize one supplied caption file."""

    caption_path = Path(path)
    try:
        size = caption_path.stat().st_size
        if size > config.maximum_file_size_bytes:
            result = CaptionParseResult(
                source_format="unknown",
                cues=[],
                issues=[CaptionParseIssue("parse", "Caption file exceeds the configured size limit.")],
            )
        else:
            result = parse_caption_text(caption_path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError:
        result = CaptionParseResult(
            source_format="unknown",
            cues=[],
            issues=[CaptionParseIssue("parse", "Caption file is not valid UTF-8 text.")],
        )
    except OSError:
        result = CaptionParseResult(
            source_format="unknown",
            cues=[],
            issues=[CaptionParseIssue("parse", "Caption file could not be read.")],
        )
    return evaluate_captions(result, media_duration_seconds=media_duration_seconds, config=config)


def evaluate_captions(
    result: CaptionParseResult,
    *,
    media_duration_seconds: float | None,
    config: CaptionRuleConfig,
) -> CaptionEvaluation:
    findings: list[Finding] = []
    parse_findings: list[Finding] = []
    parse_issues = [issue for issue in result.issues if issue.kind == "parse"]
    timing_issues = [issue for issue in result.issues if issue.kind == "timing"]
    if parse_issues:
        parse_findings.append(
            _caption_finding(
                "CAPTION_PARSE_ERROR",
                _invalid_caption_severity(config),
                "The supplied caption file contains malformed or unsupported cue syntax.",
                "Caption file could not be parsed cleanly",
                "Correct the caption syntax and export the file as UTF-8 SRT or WebVTT.",
                details={
                    "issue_count": len(parse_issues),
                    "issues": [_compact_issue(issue) for issue in parse_issues[:10]],
                },
            )
        )
    if not result.cues and not result.issues:
        parse_findings.append(
            _caption_finding(
                "CAPTION_EMPTY",
                _invalid_caption_severity(config),
                "The supplied caption file contains no usable caption cues.",
                "Caption file contains no usable cues",
                "Add timed caption cues or supply a different caption file.",
                details={"source_format": result.source_format},
            )
        )
    findings.extend(parse_findings)
    checks = [_check("captions.parse", parse_findings)]

    summary = caption_summary(
        result.cues,
        source_format=result.source_format,
        media_duration_seconds=media_duration_seconds,
    )
    timing_findings = [
        _caption_finding(
            "CAPTION_TIMING_INVALID",
            FindingSeverity.ERROR if config.require else FindingSeverity.WARNING,
            "A caption cue begins after its declared end time.",
            "Invalid caption cue timing",
            "Correct the cue so its end timestamp is not earlier than its start.",
            start=issue.start_seconds,
            details={
                "declared_end_seconds": issue.end_seconds,
                "line_number": issue.line_number,
            },
        )
        for issue in timing_issues
    ]
    if not result.cues:
        if timing_findings:
            findings.extend(timing_findings)
            checks.append(_check("captions.timing", timing_findings))
        return CaptionEvaluation([], findings, checks, summary)

    for previous, current in zip(result.cues, result.cues[1:]):
        if current.start_seconds < previous.start_seconds:
            timing_findings.append(
                _caption_finding(
                    "CAPTION_TIMING_NOT_MONOTONIC",
                    FindingSeverity.WARNING,
                    "Caption cues are not ordered by increasing start time.",
                    "Caption cues are out of order",
                    "Sort cues by their start timestamps.",
                    start=current.start_seconds,
                    end=current.end_seconds,
                    details={
                        "previous_start_seconds": previous.start_seconds,
                        "current_start_seconds": current.start_seconds,
                    },
                )
            )
    findings.extend(timing_findings)
    checks.append(_check("captions.timing", timing_findings))

    range_findings: list[Finding] = []
    if media_duration_seconds is not None:
        for cue in result.cues:
            if cue.start_seconds > media_duration_seconds or cue.end_seconds > media_duration_seconds:
                range_findings.append(
                    _caption_finding(
                        "CAPTION_CUE_OUT_OF_RANGE",
                        FindingSeverity.WARNING,
                        "A caption cue extends beyond the media duration.",
                        "Caption cue exceeds video duration",
                        "Move or remove this cue so it falls within the video timeline.",
                        start=cue.start_seconds,
                        end=cue.end_seconds,
                        details={"media_duration_seconds": media_duration_seconds},
                    )
                )
    findings.extend(range_findings)
    checks.append(_check("captions.within_duration", range_findings))

    overlap_findings: list[Finding] = []
    ordered = sorted(result.cues, key=lambda cue: (cue.start_seconds, cue.end_seconds))
    for previous, current in zip(ordered, ordered[1:]):
        overlap = previous.end_seconds - current.start_seconds
        if overlap >= config.overlap_warning_threshold_seconds:
            overlap_findings.append(
                _caption_finding(
                    "CAPTION_CUE_OVERLAP",
                    FindingSeverity.WARNING,
                    "Caption cues overlap for longer than the configured review threshold.",
                    "Overlapping caption cues",
                    "Confirm that the overlapping cues are intentional and readable.",
                    start=current.start_seconds,
                    end=min(previous.end_seconds, current.end_seconds),
                    details={
                        "overlap_seconds": overlap,
                        "warning_threshold_seconds": config.overlap_warning_threshold_seconds,
                    },
                )
            )
    findings.extend(overlap_findings)
    checks.append(_check("captions.overlap", overlap_findings))

    text_findings: list[Finding] = []
    if config.warn_on_empty_cues:
        for cue in result.cues:
            if not cue.text.strip():
                text_findings.append(
                    _caption_finding(
                        "CAPTION_CUE_EMPTY_TEXT",
                        FindingSeverity.WARNING,
                        "A timed caption cue contains no readable text.",
                        "Empty caption cue",
                        "Add caption text or remove the empty cue.",
                        start=cue.start_seconds,
                        end=cue.end_seconds,
                    )
                )
    findings.extend(text_findings)
    checks.append(_check("captions.text", text_findings))

    gap_findings = [
        _caption_finding(
            "CAPTION_LARGE_GAP",
            FindingSeverity.WARNING,
            "A long interval between caption cues may need review.",
            "Long gap between captions",
            "Review this interval and confirm that captions are not needed.",
            start=start,
            end=end,
            details={
                "duration_seconds": end - start,
                "maximum_uncovered_gap_seconds": config.maximum_uncovered_gap_seconds,
            },
        )
        for start, end in caption_gaps(result.cues)
        if end - start >= config.maximum_uncovered_gap_seconds
    ]
    findings.extend(gap_findings)
    checks.append(_check("captions.gaps", gap_findings))
    return CaptionEvaluation(result.cues, findings, checks, summary)


def caption_summary(
    cues: list[CaptionCue],
    *,
    source_format: str,
    media_duration_seconds: float | None,
) -> CaptionSummary:
    intervals = [(cue.start_seconds, cue.end_seconds) for cue in cues]
    if media_duration_seconds is not None:
        intervals = [
            (max(0.0, min(start, media_duration_seconds)), max(0.0, min(end, media_duration_seconds)))
            for start, end in intervals
        ]
    merged = merge_intervals(intervals)
    covered = sum(end - start for start, end in merged)
    percentage = None
    if media_duration_seconds is not None and media_duration_seconds > 0:
        percentage = min(100.0, covered / media_duration_seconds * 100)
    return CaptionSummary(
        source_format=source_format,
        cue_count=len(cues),
        first_caption_seconds=min((cue.start_seconds for cue in cues), default=None),
        last_caption_seconds=max((cue.end_seconds for cue in cues), default=None),
        covered_duration_seconds=covered,
        timeline_coverage_percent=percentage,
    )


def caption_gaps(cues: list[CaptionCue]) -> list[tuple[float, float]]:
    merged = merge_intervals((cue.start_seconds, cue.end_seconds) for cue in cues)
    return [(left[1], right[0]) for left, right in zip(merged, merged[1:]) if right[0] > left[1]]


def find_uncovered_speech(
    speech_segments: list[SpeechSegment],
    caption_cues: list[CaptionCue],
    config: TranscriptionConfig,
) -> list[tuple[float, float]]:
    """Subtract tolerance-expanded caption coverage from speech and merge gaps."""

    caption_intervals = merge_intervals(
        (
            max(0.0, cue.start_seconds - config.boundary_tolerance_seconds),
            cue.end_seconds + config.boundary_tolerance_seconds,
        )
        for cue in caption_cues
    )
    uncovered: list[tuple[float, float]] = []
    for speech in speech_segments:
        if speech.end_seconds <= speech.start_seconds:
            continue
        pieces = [(speech.start_seconds, speech.end_seconds)]
        for caption_start, caption_end in caption_intervals:
            next_pieces: list[tuple[float, float]] = []
            for start, end in pieces:
                if caption_end <= start or caption_start >= end:
                    next_pieces.append((start, end))
                    continue
                if caption_start > start:
                    next_pieces.append((start, min(caption_start, end)))
                if caption_end < end:
                    next_pieces.append((max(caption_end, start), end))
            pieces = next_pieces
        uncovered.extend(pieces)
    merged = merge_intervals(uncovered, max_gap=config.adjacent_gap_merge_seconds)
    return [
        (start, end)
        for start, end in merged
        if end - start >= config.speech_gap_minimum_seconds
    ]


def speech_gap_findings(
    speech_segments: list[SpeechSegment],
    caption_cues: list[CaptionCue],
    config: TranscriptionConfig,
) -> list[Finding]:
    return [
        _caption_finding(
            "CAPTION_SPEECH_GAP",
            FindingSeverity.WARNING,
            "Speech was detected here with little or no caption coverage.",
            "Possible caption gap",
            "Review this section and confirm that spoken content is captioned.",
            start=start,
            end=end,
            details={
                "duration_seconds": end - start,
                "minimum_gap_seconds": config.speech_gap_minimum_seconds,
                "boundary_tolerance_seconds": config.boundary_tolerance_seconds,
            },
        )
        for start, end in find_uncovered_speech(speech_segments, caption_cues, config)
    ]


def merge_intervals(
    intervals,
    *,
    max_gap: float = 0.0,
) -> list[tuple[float, float]]:
    valid = sorted((float(start), float(end)) for start, end in intervals if end >= start)
    merged: list[tuple[float, float]] = []
    for start, end in valid:
        if not merged or start > merged[-1][1] + max_gap:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _parse_srt(text: str) -> CaptionParseResult:
    cues: list[CaptionCue] = []
    issues: list[CaptionParseIssue] = []
    blocks = _blocks_with_lines(text)
    for lines, first_line in blocks:
        identifier = None
        timing_index = 0
        if "-->" not in lines[0]:
            identifier = lines[0].strip() or None
            timing_index = 1
        if timing_index >= len(lines):
            issues.append(CaptionParseIssue("parse", "SRT cue is missing a timing line.", first_line, identifier))
            continue
        timing = _SRT_TIMING.match(lines[timing_index])
        if not timing:
            issues.append(CaptionParseIssue("parse", "SRT cue timing is malformed.", first_line + timing_index, identifier))
            continue
        start = _timestamp_seconds(timing.group("start"), _SRT_TIMESTAMP)
        end = _timestamp_seconds(timing.group("end"), _SRT_TIMESTAMP)
        if start is None or end is None:
            issues.append(CaptionParseIssue("parse", "SRT timestamp is invalid.", first_line + timing_index, identifier))
            continue
        if end < start:
            issues.append(CaptionParseIssue("timing", "SRT cue ends before it starts.", first_line + timing_index, identifier, start, end))
            continue
        cues.append(CaptionCue(start, end, "\n".join(lines[timing_index + 1 :]).strip(), identifier, "srt", first_line))
    return CaptionParseResult("srt", cues, issues)


def _parse_webvtt(text: str) -> CaptionParseResult:
    lines = text.splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.strip()), 0)
    body = "\n".join(lines[header_index + 1 :])
    cues: list[CaptionCue] = []
    issues: list[CaptionParseIssue] = []
    for block_lines, first_line in _blocks_with_lines(body, line_offset=header_index + 1):
        if block_lines[0].lstrip().startswith(("NOTE", "STYLE", "REGION")):
            continue
        identifier = None
        timing_index = 0
        if "-->" not in block_lines[0]:
            identifier = block_lines[0].strip() or None
            timing_index = 1
        if timing_index >= len(block_lines):
            issues.append(CaptionParseIssue("parse", "WebVTT cue is missing a timing line.", first_line, identifier))
            continue
        timing = _VTT_TIMING.match(block_lines[timing_index])
        if not timing:
            issues.append(CaptionParseIssue("parse", "WebVTT cue timing is malformed.", first_line + timing_index, identifier))
            continue
        start = _timestamp_seconds(timing.group("start"), _VTT_TIMESTAMP)
        end = _timestamp_seconds(timing.group("end"), _VTT_TIMESTAMP)
        if start is None or end is None:
            issues.append(CaptionParseIssue("parse", "WebVTT timestamp is invalid.", first_line + timing_index, identifier))
            continue
        if end < start:
            issues.append(CaptionParseIssue("timing", "WebVTT cue ends before it starts.", first_line + timing_index, identifier, start, end))
            continue
        cues.append(CaptionCue(start, end, "\n".join(block_lines[timing_index + 1 :]).strip(), identifier, "vtt", first_line))
    return CaptionParseResult("vtt", cues, issues)


def _blocks_with_lines(text: str, *, line_offset: int = 0) -> list[tuple[list[str], int]]:
    blocks: list[tuple[list[str], int]] = []
    current: list[str] = []
    start = 1 + line_offset
    for index, line in enumerate(text.splitlines(), start=1 + line_offset):
        if not line.strip():
            if current:
                blocks.append((current, start))
                current = []
            start = index + 1
        else:
            if not current:
                start = index
            current.append(line)
    if current:
        blocks.append((current, start))
    return blocks


def _timestamp_seconds(value: str, pattern: re.Pattern[str]) -> float | None:
    match = pattern.match(value)
    if not match:
        return None
    hours = int(match.groupdict().get("hours") or 0)
    return hours * 3600 + int(match.group("minutes")) * 60 + int(match.group("seconds")) + int(match.group("millis")) / 1000


def _invalid_caption_severity(config: CaptionRuleConfig) -> FindingSeverity:
    return FindingSeverity.ERROR if config.require else FindingSeverity.WARNING


def _compact_issue(issue: CaptionParseIssue) -> dict[str, int | str]:
    compact: dict[str, int | str] = {"message": issue.message}
    if issue.line_number is not None:
        compact["line_number"] = issue.line_number
    if issue.identifier:
        compact["identifier"] = issue.identifier[:80]
    return compact


def _check(check_id: str, findings: list[Finding]) -> CheckResult:
    return CheckResult(check_id=check_id, passed=not findings, finding_codes=[finding.code for finding in findings])


def _caption_finding(
    code: str,
    severity: FindingSeverity,
    message: str,
    title: str,
    suggestion: str,
    *,
    start: float | None = None,
    end: float | None = None,
    details: dict | None = None,
) -> Finding:
    status = FindingStatus.BLOCKED if severity is FindingSeverity.ERROR else FindingStatus.NEEDS_REVIEW
    evidence = {"category": "captions", "title": title}
    if details:
        evidence.update({key: value for key, value in details.items() if value is not None})
    return Finding(
        code=code,
        severity=severity,
        status=status,
        message=message,
        source="captions.validation" if code != "CAPTION_SPEECH_GAP" else "captions.speech",
        timestamp_start_seconds=start,
        timestamp_end_seconds=end if start is not None and end is not None and end >= start else None,
        details=evidence,
        suggestion=suggestion,
    )
