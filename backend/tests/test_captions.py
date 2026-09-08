from pathlib import Path

import pytest

from releaseseal.captions import (
    CaptionCue,
    SpeechSegment,
    caption_summary,
    evaluate_captions,
    find_uncovered_speech,
    inspect_caption_file,
    parse_caption_text,
    speech_gap_findings,
)
from releaseseal.config import CaptionRuleConfig, TranscriptionConfig


def test_parse_valid_srt_with_bom_crlf_and_multiline_text() -> None:
    result = parse_caption_text(
        "\ufeff1\r\n00:00:01,000 --> 00:00:03,500\r\nFirst line\r\nSecond line\r\n\r\n"
        "2\r\n00:00:04,000 --> 00:00:05,250\r\nNext cue\r\n"
    )

    assert result.source_format == "srt"
    assert result.issues == []
    assert [(cue.start_seconds, cue.end_seconds) for cue in result.cues] == [
        (1.0, 3.5),
        (4.0, 5.25),
    ]
    assert result.cues[0].text == "First line\nSecond line"


def test_parse_valid_webvtt_with_identifier_settings_and_hour_timestamp() -> None:
    result = parse_caption_text(
        "WEBVTT - ReleaseSeal\n\n"
        "intro\n00:00:01.000 --> 00:00:03.500 align:start\nHello\n\n"
        "01:02:03.000 --> 01:02:04.250\nHour cue\n"
    )

    assert result.source_format == "vtt"
    assert result.issues == []
    assert result.cues[0].identifier == "intro"
    assert result.cues[1].start_seconds == 3723.0


@pytest.mark.parametrize(
    "text",
    [
        "1\n00:00:not-time --> 00:00:02,000\nBad\n",
        "WEBVTT\n\n00:00:AA.000 --> 00:00:02.000\nBad\n",
        "plain text without caption timing",
    ],
)
def test_malformed_caption_syntax_is_reported(text: str) -> None:
    result = parse_caption_text(text)
    evaluation = evaluate_captions(
        result, media_duration_seconds=10, config=CaptionRuleConfig()
    )

    assert not result.cues
    assert any(issue.kind == "parse" for issue in result.issues)
    assert [finding.code for finding in evaluation.findings] == ["CAPTION_PARSE_ERROR"]


def test_invalid_start_end_timing_produces_timing_finding() -> None:
    result = parse_caption_text("1\n00:00:05,000 --> 00:00:02,000\nBackwards\n")
    evaluation = evaluate_captions(
        result, media_duration_seconds=10, config=CaptionRuleConfig()
    )

    assert "CAPTION_TIMING_INVALID" in [finding.code for finding in evaluation.findings]


def test_timeline_validation_reports_range_order_overlap_empty_text_and_gap() -> None:
    result = parse_caption_text(
        "1\n00:00:02,000 --> 00:00:04,000\nFirst\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\nOverlap\n\n"
        "3\n00:00:01,000 --> 00:00:01,500\nEarlier\n\n"
        "4\n00:00:16,000 --> 00:00:18,000\nBeyond\n\n"
        "5\n00:00:18,500 --> 00:00:19,000\n\n"
    )
    config = CaptionRuleConfig(
        maximum_uncovered_gap_seconds=5,
        overlap_warning_threshold_seconds=0.5,
    )
    evaluation = evaluate_captions(result, media_duration_seconds=12, config=config)
    codes = {finding.code for finding in evaluation.findings}

    assert "CAPTION_TIMING_NOT_MONOTONIC" in codes
    assert "CAPTION_CUE_OVERLAP" in codes
    assert "CAPTION_CUE_OUT_OF_RANGE" in codes
    assert "CAPTION_CUE_EMPTY_TEXT" in codes
    assert "CAPTION_LARGE_GAP" in codes


def test_empty_caption_file_has_one_real_failed_check(tmp_path: Path) -> None:
    path = tmp_path / "empty.vtt"
    path.write_text("\ufeff\r\n", encoding="utf-8")

    evaluation = inspect_caption_file(
        path, media_duration_seconds=10, config=CaptionRuleConfig()
    )

    assert [finding.code for finding in evaluation.findings] == ["CAPTION_EMPTY"]
    assert [check.check_id for check in evaluation.checks] == ["captions.parse"]
    assert evaluation.checks[0].passed is False


def test_coverage_merges_overlaps_and_never_exceeds_one_hundred_percent() -> None:
    cues = [
        CaptionCue(0, 8, "One"),
        CaptionCue(2, 12, "Two"),
    ]
    summary = caption_summary(cues, source_format="srt", media_duration_seconds=10)

    assert summary.covered_duration_seconds == 10
    assert summary.timeline_coverage_percent == 100
    assert summary.cue_count == 2
    assert summary.first_caption_seconds == 0
    assert summary.last_caption_seconds == 12


def test_large_gap_finding_has_deterministic_interval() -> None:
    result = parse_caption_text(
        "1\n00:00:00,000 --> 00:00:02,000\nOne\n\n"
        "2\n00:00:09,000 --> 00:00:11,000\nTwo\n"
    )
    evaluation = evaluate_captions(
        result,
        media_duration_seconds=12,
        config=CaptionRuleConfig(maximum_uncovered_gap_seconds=5),
    )
    gap = next(finding for finding in evaluation.findings if finding.code == "CAPTION_LARGE_GAP")

    assert gap.timestamp_start_seconds == 2
    assert gap.timestamp_end_seconds == 9


def test_speech_comparison_fully_covered_or_no_speech_has_no_warning() -> None:
    config = TranscriptionConfig(enabled=True)
    captions = [CaptionCue(1.8, 5.2, "Covered")]

    assert find_uncovered_speech([SpeechSegment(2, 5)], captions, config) == []
    assert find_uncovered_speech([], captions, config) == []


def test_speech_comparison_finds_uncovered_and_partially_covered_regions() -> None:
    config = TranscriptionConfig(
        enabled=True,
        speech_gap_minimum_seconds=1.0,
        boundary_tolerance_seconds=0,
    )
    speech = [SpeechSegment(2, 5), SpeechSegment(7, 10)]
    covered_first = [CaptionCue(2, 5, "Covered")]

    assert find_uncovered_speech(speech, covered_first, config) == [(7.0, 10.0)]

    captions = [*covered_first, CaptionCue(7, 8, "Partial")]

    assert find_uncovered_speech(speech, captions, config) == [(8.0, 10.0)]


def test_speech_boundary_tolerance_avoids_small_false_positive() -> None:
    config = TranscriptionConfig(
        enabled=True,
        speech_gap_minimum_seconds=0.1,
        boundary_tolerance_seconds=0.3,
    )

    assert find_uncovered_speech(
        [SpeechSegment(2, 5)], [CaptionCue(2.2, 4.8, "Near")], config
    ) == []


def test_adjacent_uncovered_speech_segments_merge() -> None:
    config = TranscriptionConfig(
        enabled=True,
        speech_gap_minimum_seconds=2,
        adjacent_gap_merge_seconds=0.5,
    )
    speech = [SpeechSegment(2, 3.2), SpeechSegment(3.4, 5)]

    assert find_uncovered_speech(speech, [], config) == [(2.0, 5.0)]


def test_no_captions_produces_conservative_speech_gap_finding() -> None:
    config = TranscriptionConfig(enabled=True, speech_gap_minimum_seconds=2)
    findings = speech_gap_findings([SpeechSegment(7, 10, "spoken")], [], config)

    assert len(findings) == 1
    assert findings[0].code == "CAPTION_SPEECH_GAP"
    assert findings[0].timestamp_start_seconds == 7
    assert findings[0].timestamp_end_seconds == 10
