from pathlib import Path

import pytest

from releaseseal.captions import SpeechSegment, parse_caption_text
from releaseseal.generated_captions import (
    GeneratedCaptionStatus,
    build_generated_caption_draft,
    generated_caption_filename,
    verified_reusable_segments,
)


def test_generated_srt_is_ordered_sanitized_and_non_overlapping(tmp_path: Path) -> None:
    media = tmp_path / "My final.mov"
    media.write_bytes(b"exact-artifact")
    source = [
        SpeechSegment(2.0, 3.0, " second\nline "),
        SpeechSegment(-1.0, 1.0, " first\x00 cue "),
        SpeechSegment(.9, 2.2, " overlapping cue "),
        SpeechSegment(float("nan"), 5, "invalid"),
    ]
    draft = build_generated_caption_draft(
        artifact_path=media, original_filename=media.name, segments=source,
        model="tiny.en", maximum_cues=100, maximum_characters=1000,
    )
    assert draft.status is GeneratedCaptionStatus.COMPLETED
    assert draft.download_filename == "My-final.generated.srt"
    assert draft.cue_count == 3
    assert draft.cues[0].start_seconds == 0
    assert draft.cues[1].start_seconds == draft.cues[0].end_seconds
    assert draft.cues[2].start_seconds == draft.cues[1].end_seconds
    assert "00:00:00,000 --> 00:00:01,000" in draft.srt_text
    assert "\x00" not in draft.srt_text
    parsed = parse_caption_text(draft.srt_text)
    assert parsed.issues == []
    assert len(parsed.cues) == 3
    assert source[1].start_seconds == -1.0


def test_generated_caption_reuse_is_artifact_bound(tmp_path: Path) -> None:
    media = tmp_path / "release.mp4"
    media.write_bytes(b"same-artifact")
    draft = build_generated_caption_draft(
        artifact_path=media, original_filename=media.name,
        segments=[SpeechSegment(1.25, 2.5, "SAVE25")], model="tiny.en",
        maximum_cues=10, maximum_characters=100,
    )
    reused = verified_reusable_segments(
        draft, artifact_sha256=draft.artifact_sha256, expected_model="tiny.en"
    )
    assert reused == [SpeechSegment(1.25, 2.5, "SAVE25")]
    with pytest.raises(ValueError, match="does not match"):
        verified_reusable_segments(draft, artifact_sha256="0" * 64, expected_model="tiny.en")
    changed = draft.model_copy(update={"cues": [draft.cues[0].model_copy(update={"text": "SAVE20"})]})
    with pytest.raises(ValueError, match="identity is invalid"):
        verified_reusable_segments(changed, artifact_sha256=draft.artifact_sha256, expected_model="tiny.en")


def test_safe_generated_caption_filename() -> None:
    assert generated_caption_filename("../../final release.mp4") == "final-release.generated.srt"

