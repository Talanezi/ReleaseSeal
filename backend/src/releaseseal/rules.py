"""Deterministic creator publishing-package rules and chapter parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from releaseseal.config import CreatorRuleConfig, aspect_ratio_value
from releaseseal.models import (
    CheckResult,
    Finding,
    FindingSeverity,
    FindingStatus,
    MediaInspection,
    PublishingPackage,
)

_CHAPTER_CANDIDATE = re.compile(
    r"^\s*(?P<timestamp>\d{1,3}:\d{1,2}(?::\d{1,2})?)\s+(?P<title>\S.*)\s*$"
)
_TWO_PART_TIMESTAMP = re.compile(r"^(?P<minutes>\d{1,3}):(?P<seconds>[0-5]\d)$")
_THREE_PART_TIMESTAMP = re.compile(
    r"^(?P<hours>\d{1,3}):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d)$"
)
_URL_CANDIDATE = re.compile(r"(?i)^(?:https?:|www\.)")
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")


@dataclass(frozen=True)
class Chapter:
    timestamp_seconds: int
    title: str
    line_number: int


@dataclass(frozen=True)
class ChapterParseResult:
    chapters: list[Chapter]
    invalid_entries: list[dict[str, int | str]]


@dataclass(frozen=True)
class RuleEvaluation:
    findings: list[Finding]
    checks: list[CheckResult]


def parse_chapters(description: str) -> ChapterParseResult:
    """Parse timestamp-led lines only; ordinary inline numbers are ignored."""

    chapters: list[Chapter] = []
    invalid_entries: list[dict[str, int | str]] = []
    for line_number, line in enumerate(description.splitlines(), start=1):
        match = _CHAPTER_CANDIDATE.match(line)
        if not match:
            continue
        timestamp = match.group("timestamp")
        seconds = _parse_timestamp(timestamp)
        if seconds is None:
            invalid_entries.append(
                {"line_number": line_number, "timestamp": timestamp[:24]}
            )
            continue
        chapters.append(
            Chapter(
                timestamp_seconds=seconds,
                title=match.group("title").strip(),
                line_number=line_number,
            )
        )
    return ChapterParseResult(chapters=chapters, invalid_entries=invalid_entries)


def evaluate_package_rules(
    package: PublishingPackage,
    media: MediaInspection,
    config: CreatorRuleConfig,
) -> RuleEvaluation:
    findings: list[Finding] = []
    checks: list[CheckResult] = []

    if media.has_video:
        _evaluate_dimensions(media, config, findings, checks)

    title = package.title.strip()
    if config.title.require:
        finding = None
        if not title:
            finding = _finding(
                "TITLE_REQUIRED",
                FindingSeverity.ERROR,
                "A title is required for this publishing package.",
                "package.title",
                "Add a title before publishing.",
                title="Missing required title",
            )
            findings.append(finding)
        checks.append(_check("title.required", [finding] if finding else []))

    length_finding = None
    if len(package.title) > config.title.maximum_recommended_length:
        length_finding = _finding(
            "TITLE_LENGTH_RECOMMENDATION",
            FindingSeverity.WARNING,
            "The title exceeds the configured recommended length.",
            "package.title",
            "Consider shortening the title while preserving its meaning.",
            title="Title exceeds recommended length",
            details={
                "character_count": len(package.title),
                "maximum_recommended_length": config.title.maximum_recommended_length,
            },
        )
        findings.append(length_finding)
    checks.append(_check("title.recommended_length", [length_finding] if length_finding else []))

    description = package.description.strip()
    if config.description.require:
        finding = None
        if not description:
            finding = _finding(
                "DESCRIPTION_REQUIRED",
                FindingSeverity.WARNING,
                "The publishing package does not include a description.",
                "package.description",
                "Add a description so viewers have the intended context before publishing.",
                title="Description missing",
            )
            findings.append(finding)
        checks.append(_check("description.required", [finding] if finding else []))

    if config.description.required_phrases:
        missing = [
            phrase
            for phrase in config.description.required_phrases
            if phrase.casefold() not in package.description.casefold()
        ]
        finding = None
        if missing:
            finding = _finding(
                "DESCRIPTION_REQUIRED_PHRASE_MISSING",
                FindingSeverity.ERROR,
                "The description is missing configured required text.",
                "package.description",
                "Add the missing required text to the description.",
                title="Required description text missing",
                details={"missing_phrases": missing},
            )
            findings.append(finding)
        checks.append(_check("description.required_phrases", [finding] if finding else []))

    if config.description.validate_urls:
        malformed_urls = _malformed_url_tokens(package.description)
        finding = None
        if malformed_urls:
            finding = _finding(
                "DESCRIPTION_URL_MALFORMED",
                FindingSeverity.WARNING,
                "The description contains URL text with obviously malformed syntax.",
                "package.description",
                "Correct the URL syntax; this check does not test whether links resolve or are safe.",
                title="Malformed URL syntax",
                details={"malformed_tokens": malformed_urls[:10]},
            )
            findings.append(finding)
        checks.append(_check("description.url_syntax", [finding] if finding else []))

    chapter_result = parse_chapters(package.description)
    syntax_finding = None
    if chapter_result.invalid_entries:
        syntax_finding = _finding(
            "CHAPTER_TIMESTAMP_INVALID",
            FindingSeverity.ERROR,
            "One or more chapter-like timestamp lines are malformed.",
            "package.chapters",
            "Use MM:SS or H:MM:SS with seconds and hour-form minutes between 00 and 59.",
            title="Invalid chapter timestamp",
            details={"invalid_entries": chapter_result.invalid_entries[:10]},
        )
        findings.append(syntax_finding)
    checks.append(_check("chapters.syntax", [syntax_finding] if syntax_finding else []))

    chapters = chapter_result.chapters
    if config.chapters.require:
        finding = None
        if not chapters:
            finding = _finding(
                "CHAPTERS_REQUIRED",
                FindingSeverity.ERROR,
                "At least one chapter timestamp is required.",
                "package.chapters",
                "Add timestamp-led chapter lines to the description.",
                title="Required chapters missing",
            )
            findings.append(finding)
        checks.append(_check("chapters.present", [finding] if finding else []))

    if chapters:
        order_issues = [
            {
                "previous_seconds": previous.timestamp_seconds,
                "current_seconds": current.timestamp_seconds,
                "line_number": current.line_number,
            }
            for previous, current in zip(chapters, chapters[1:])
            if current.timestamp_seconds <= previous.timestamp_seconds
        ]
        finding = None
        if order_issues:
            finding = _finding(
                "CHAPTER_TIMESTAMPS_NOT_INCREASING",
                FindingSeverity.ERROR,
                "Chapter timestamps must be strictly increasing without duplicates.",
                "package.chapters",
                "Reorder or correct the listed chapter timestamps.",
                title="Chapter timestamps out of order",
                details={"issues": order_issues[:10]},
            )
            findings.append(finding)
        checks.append(_check("chapters.order", [finding] if finding else []))

        duration_issues = []
        if media.duration_seconds is not None:
            duration_issues = [
                {
                    "timestamp_seconds": chapter.timestamp_seconds,
                    "line_number": chapter.line_number,
                }
                for chapter in chapters
                if chapter.timestamp_seconds > media.duration_seconds
            ]
        finding = None
        if duration_issues:
            finding = _finding(
                "CHAPTER_BEYOND_MEDIA_DURATION",
                FindingSeverity.ERROR,
                "A chapter timestamp exceeds the media duration.",
                "package.chapters",
                "Correct or remove chapter timestamps beyond the end of the video.",
                title="Chapter exceeds video duration",
                details={
                    "media_duration_seconds": media.duration_seconds,
                    "issues": duration_issues[:10],
                },
            )
            findings.append(finding)
        checks.append(_check("chapters.within_duration", [finding] if finding else []))

        if config.chapters.require_first_at_zero:
            finding = None
            if chapters[0].timestamp_seconds != 0:
                finding = _finding(
                    "CHAPTER_FIRST_NOT_ZERO",
                    FindingSeverity.ERROR,
                    "The first chapter must begin at 00:00.",
                    "package.chapters",
                    "Add or change the first chapter timestamp to 00:00.",
                    title="First chapter does not begin at 00:00",
                    details={"first_timestamp_seconds": chapters[0].timestamp_seconds},
                )
                findings.append(finding)
            checks.append(_check("chapters.first_at_zero", [finding] if finding else []))

    if config.captions.require:
        finding = None
        if package.captions_path is None:
            finding = _finding(
                "CAPTIONS_REQUIRED",
                FindingSeverity.ERROR,
                "A captions input is required for this publishing package.",
                "package.captions",
                "Supply a UTF-8 SRT or WebVTT captions file.",
                title="Required captions missing",
            )
            findings.append(finding)
        checks.append(_check("captions.present", [finding] if finding else []))

    return RuleEvaluation(findings=findings, checks=checks)


def _evaluate_dimensions(
    media: MediaInspection,
    config: CreatorRuleConfig,
    findings: list[Finding],
    checks: list[CheckResult],
) -> None:
    width_finding = None
    if media.width is None or media.width < config.video.minimum_width:
        width_finding = _finding(
            "VIDEO_WIDTH_BELOW_MINIMUM",
            FindingSeverity.ERROR,
            "The video width is below the configured minimum.",
            "package.video",
            "Export the video at or above the configured minimum width.",
            title="Video width below minimum",
            details={
                "actual_width": media.width,
                "minimum_width": config.video.minimum_width,
            },
        )
        findings.append(width_finding)
    checks.append(_check("video.minimum_width", [width_finding] if width_finding else []))

    height_finding = None
    if media.height is None or media.height < config.video.minimum_height:
        height_finding = _finding(
            "VIDEO_HEIGHT_BELOW_MINIMUM",
            FindingSeverity.ERROR,
            "The video height is below the configured minimum.",
            "package.video",
            "Export the video at or above the configured minimum height.",
            title="Video height below minimum",
            details={
                "actual_height": media.height,
                "minimum_height": config.video.minimum_height,
            },
        )
        findings.append(height_finding)
    checks.append(_check("video.minimum_height", [height_finding] if height_finding else []))

    aspect_finding = None
    actual_ratio = None
    if media.display_aspect_ratio:
        try:
            actual_ratio = aspect_ratio_value(media.display_aspect_ratio)
        except ValueError:
            actual_ratio = None
    if actual_ratio is None and media.width is not None and media.height not in (None, 0):
        actual_ratio = media.width / media.height
    allowed_values = [aspect_ratio_value(value) for value in config.video.allowed_aspect_ratios]
    allowed = actual_ratio is not None and any(
        abs(actual_ratio - expected) / expected <= config.video.aspect_ratio_tolerance
        for expected in allowed_values
    )
    if not allowed:
        aspect_finding = _finding(
            "VIDEO_ASPECT_RATIO_NOT_ALLOWED",
            FindingSeverity.ERROR,
            "The video aspect ratio is not in the configured allowed set.",
            "package.video",
            "Export using one of the configured allowed aspect ratios.",
            title="Video aspect ratio not allowed",
            details={
                "actual_aspect_ratio": actual_ratio,
                "allowed_aspect_ratios": config.video.allowed_aspect_ratios,
                "tolerance": config.video.aspect_ratio_tolerance,
            },
        )
        findings.append(aspect_finding)
    checks.append(_check("video.aspect_ratio", [aspect_finding] if aspect_finding else []))


def _parse_timestamp(value: str) -> int | None:
    match = _TWO_PART_TIMESTAMP.match(value)
    if match:
        return int(match.group("minutes")) * 60 + int(match.group("seconds"))
    match = _THREE_PART_TIMESTAMP.match(value)
    if match:
        return (
            int(match.group("hours")) * 3600
            + int(match.group("minutes")) * 60
            + int(match.group("seconds"))
        )
    return None


def _malformed_url_tokens(description: str) -> list[str]:
    malformed: list[str] = []
    for raw_token in description.split():
        token = raw_token.strip("<>()[]{}\"'")
        token = token.rstrip(".,;!?")
        if not _URL_CANDIDATE.match(token):
            continue
        candidate = f"http://{token}" if token.lower().startswith("www.") else token
        try:
            parsed = urlsplit(candidate)
            hostname = parsed.hostname
            valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc and hostname)
            if valid and hostname != "localhost":
                valid = all(_HOST_LABEL.match(label) for label in hostname.split("."))
        except ValueError:
            valid = False
        if not valid:
            malformed.append(token[:160])
    return malformed


def _check(check_id: str, findings: list[Finding]) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        passed=not findings,
        finding_codes=[finding.code for finding in findings],
    )


def _finding(
    code: str,
    severity: FindingSeverity,
    message: str,
    source: str,
    suggestion: str,
    *,
    title: str,
    details: dict | None = None,
) -> Finding:
    status = {
        FindingSeverity.INFO: FindingStatus.READY,
        FindingSeverity.WARNING: FindingStatus.NEEDS_REVIEW,
        FindingSeverity.ERROR: FindingStatus.BLOCKED,
    }[severity]
    evidence = {"category": "package", "title": title}
    if details:
        evidence.update(details)
    return Finding(
        code=code,
        severity=severity,
        status=status,
        message=message,
        source=source,
        details=evidence,
        suggestion=suggestion,
    )
