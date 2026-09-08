"""Deterministic correlation of previous-cut revision notes to a RevisionMap."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from releaseseal.config import RevisionCheckConfig
from releaseseal.revision import RevisionMapper
from releaseseal.revision_check_models import (
    AdditionalRevisionChange,
    RevisionCheckReport,
    RevisionRequest,
    RevisionRequestStatus,
)
from releaseseal.revision_models import RevisionMap, RevisionSegment, RevisionSegmentKind

_TIMESTAMP = r"(?:\d+:)?\d{1,3}:\d{2}(?:\.\d{1,3})?"
_TIMED_NOTE = re.compile(
    rf"^\s*(?P<start>{_TIMESTAMP})(?:\s*[-–—]\s*(?P<end>{_TIMESTAMP}))?\s+(?P<text>.+?)\s*$"
)
_LOOKS_LIKE_TIME = re.compile(
    r"^\s*(?:[-+]\d[^\s]*|(?:nan|inf(?:inity)?)(?:\s|$)|\d[^\s]*:)",
    re.IGNORECASE,
)


class RevisionCheckError(Exception):
    """Safe error raised for an invalid revision-note/check request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ParsedRevisionNote:
    source_line: int
    text: str
    start_seconds: float | None
    end_seconds: float | None
    explicit_range: bool


class RevisionCheckService:
    """Map two files, parse optional notes, and correlate physical changes."""

    def __init__(
        self,
        *,
        mapper: RevisionMapper | None = None,
        config: RevisionCheckConfig | None = None,
    ) -> None:
        self.mapper = mapper or RevisionMapper()
        self.config = config or RevisionCheckConfig()

    def check(
        self,
        previous_path: str | Path,
        revised_path: str | Path,
        notes: str = "",
        *,
        previous_filename: str | None = None,
        revised_filename: str | None = None,
    ) -> RevisionCheckReport:
        started = perf_counter()
        revision_map = self.mapper.map(previous_path, revised_path)
        return self.from_map(
            revision_map,
            notes,
            previous_filename=previous_filename or Path(previous_path).name,
            revised_filename=revised_filename or Path(revised_path).name,
            analysis_runtime_seconds=perf_counter() - started,
        )

    def from_map(
        self,
        revision_map: RevisionMap,
        notes: str = "",
        *,
        previous_filename: str = "previous video",
        revised_filename: str = "revised video",
        analysis_runtime_seconds: float | None = None,
    ) -> RevisionCheckReport:
        parsed = parse_revision_notes(notes, revision_map.previous_duration_seconds, self.config)
        changes = [segment for segment in revision_map.segments if segment.kind is not RevisionSegmentKind.UNCHANGED]
        accounted_segment_ids: set[str] = set()
        requests: list[RevisionRequest] = []
        for index, note in enumerate(parsed, 1):
            if note.start_seconds is None:
                requests.append(
                    RevisionRequest(
                        request_id=f"request-{index:04d}",
                        source_line=note.source_line,
                        text=note.text,
                        status=RevisionRequestStatus.NEEDS_LOCATION,
                        evidence="Add a previous-cut timecode to check this request automatically.",
                    )
                )
                continue
            candidates = _matching_segments(note, changes, revision_map, self.config)
            matched_ids = [segment.segment_id for segment in candidates]
            accounted_segment_ids.update(matched_ids)
            detected = bool(candidates)
            evidence = (
                "Media changed near this request: "
                + ", ".join(_kind_label(segment.kind) for segment in candidates)
                + "."
                if detected
                else "No physical media change was detected near this request."
            )
            requests.append(
                RevisionRequest(
                    request_id=f"request-{index:04d}",
                    source_line=note.source_line,
                    text=note.text,
                    previous_start_seconds=note.start_seconds,
                    previous_end_seconds=note.end_seconds,
                    explicit_range=note.explicit_range,
                    status=(
                        RevisionRequestStatus.CHANGE_DETECTED
                        if detected
                        else RevisionRequestStatus.NO_CHANGE_DETECTED
                    ),
                    matched_segment_ids=matched_ids,
                    evidence=evidence,
                )
            )
        additional = [
            _additional_change(segment)
            for segment in changes
            if segment.segment_id not in accounted_segment_ids
        ]
        return RevisionCheckReport(
            previous_filename=Path(previous_filename).name or "previous video",
            revised_filename=Path(revised_filename).name or "revised video",
            revision_map=revision_map,
            revision_requests=requests,
            requested_change_count=len(requests),
            requested_changes_detected_count=sum(
                request.status is RevisionRequestStatus.CHANGE_DETECTED for request in requests
            ),
            requested_changes_not_detected_count=sum(
                request.status is RevisionRequestStatus.NO_CHANGE_DETECTED for request in requests
            ),
            requests_needing_location_count=sum(
                request.status is RevisionRequestStatus.NEEDS_LOCATION for request in requests
            ),
            additional_changes=additional,
            additional_change_count=len(additional),
            analysis_runtime_seconds=(
                revision_map.analysis_runtime_seconds
                if analysis_runtime_seconds is None
                else analysis_runtime_seconds
            ),
        )


def parse_revision_notes(
    notes: str,
    previous_duration_seconds: float,
    config: RevisionCheckConfig | None = None,
) -> list[ParsedRevisionNote]:
    policy = config or RevisionCheckConfig()
    if len(notes) > policy.maximum_notes_characters:
        raise RevisionCheckError("revision_notes_too_large", "The revision notes exceed the configured size limit.")
    parsed: list[ParsedRevisionNote] = []
    for line_number, raw_line in enumerate(notes.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        if len(parsed) >= policy.maximum_notes:
            raise RevisionCheckError("revision_notes_too_many", "The revision notes contain too many requests.")
        if len(line) > policy.maximum_note_characters:
            raise RevisionCheckError("revision_note_too_long", f"Revision note line {line_number} is too long.")
        match = _TIMED_NOTE.match(line)
        if match is None:
            if _LOOKS_LIKE_TIME.match(line):
                raise RevisionCheckError("revision_note_timestamp_invalid", f"Revision note line {line_number} has an invalid timecode.")
            parsed.append(ParsedRevisionNote(line_number, line, None, None, False))
            continue
        start = _parse_timecode(match.group("start"), line_number)
        raw_end = match.group("end")
        end = _parse_timecode(raw_end, line_number) if raw_end else start
        if end < start:
            raise RevisionCheckError("revision_note_range_invalid", f"Revision note line {line_number} has a reversed time range.")
        if start > previous_duration_seconds or end > previous_duration_seconds:
            raise RevisionCheckError("revision_note_out_of_range", f"Revision note line {line_number} is outside the previous cut.")
        parsed.append(
            ParsedRevisionNote(line_number, match.group("text").strip(), start, end, raw_end is not None)
        )
    return parsed


def insertion_previous_anchor(segment_id: str, revision_map: RevisionMap) -> float | None:
    for index, segment in enumerate(revision_map.segments):
        if segment.segment_id != segment_id or segment.kind is not RevisionSegmentKind.INSERTED:
            continue
        before = next(
            (
                item.previous_end_seconds
                for item in reversed(revision_map.segments[:index])
                if item.previous_end_seconds is not None
            ),
            None,
        )
        after = next(
            (
                item.previous_start_seconds
                for item in revision_map.segments[index + 1 :]
                if item.previous_start_seconds is not None
            ),
            None,
        )
        if before is not None and after is not None:
            return (before + after) / 2
        return before if before is not None else after
    return None


def _parse_timecode(value: str, line_number: int) -> float:
    parts = value.split(":")
    try:
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            hours = 0
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
        else:
            raise ValueError
    except ValueError as exc:
        raise RevisionCheckError("revision_note_timestamp_invalid", f"Revision note line {line_number} has an invalid timecode.") from exc
    if hours < 0 or minutes < 0 or (len(parts) == 3 and minutes >= 60) or not math.isfinite(seconds) or seconds < 0 or seconds >= 60:
        raise RevisionCheckError("revision_note_timestamp_invalid", f"Revision note line {line_number} has an invalid timecode.")
    return hours * 3600 + minutes * 60 + seconds


def _matching_segments(
    note: ParsedRevisionNote,
    changes: list[RevisionSegment],
    revision_map: RevisionMap,
    config: RevisionCheckConfig,
) -> list[RevisionSegment]:
    assert note.start_seconds is not None and note.end_seconds is not None
    tolerance = config.explicit_range_tolerance_seconds if note.explicit_range else config.point_neighborhood_seconds
    window_start = max(0.0, note.start_seconds - tolerance)
    window_end = min(revision_map.previous_duration_seconds, note.end_seconds + tolerance)
    matches: list[tuple[float, float, str, RevisionSegment]] = []
    for segment in changes:
        if segment.kind is RevisionSegmentKind.INSERTED:
            anchor = insertion_previous_anchor(segment.segment_id, revision_map)
            if anchor is None or anchor < window_start or anchor > window_end:
                continue
            overlap = 0.0
            distance = 0.0 if window_start <= anchor <= window_end else min(abs(anchor - window_start), abs(anchor - window_end))
        else:
            assert segment.previous_start_seconds is not None and segment.previous_end_seconds is not None
            overlap = max(
                0.0,
                min(window_end, segment.previous_end_seconds)
                - max(window_start, segment.previous_start_seconds),
            )
            if overlap <= 0 and not (
                window_start <= segment.previous_start_seconds <= window_end
                or window_start <= segment.previous_end_seconds <= window_end
            ):
                continue
            distance = _interval_distance(
                note.start_seconds,
                note.end_seconds,
                segment.previous_start_seconds,
                segment.previous_end_seconds,
            )
        matches.append((-overlap, distance, segment.segment_id, segment))
    matches.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in matches]


def _interval_distance(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    if left_end >= right_start and right_end >= left_start:
        return 0.0
    return min(abs(left_start - right_end), abs(right_start - left_end))


def _kind_label(kind: RevisionSegmentKind) -> str:
    return {
        RevisionSegmentKind.REMOVED: "removed",
        RevisionSegmentKind.INSERTED: "inserted",
        RevisionSegmentKind.CHANGED: "changed",
        RevisionSegmentKind.UNCHANGED: "unchanged",
    }[kind]


def _additional_change(segment: RevisionSegment) -> AdditionalRevisionChange:
    return AdditionalRevisionChange(
        segment_id=segment.segment_id,
        kind=segment.kind,
        previous_start_seconds=segment.previous_start_seconds,
        previous_end_seconds=segment.previous_end_seconds,
        revised_start_seconds=segment.revised_start_seconds,
        revised_end_seconds=segment.revised_end_seconds,
        visual_changed=segment.visual_changed,
        audio_changed=segment.audio_changed,
        boundary_confidence=segment.boundary_confidence,
    )
