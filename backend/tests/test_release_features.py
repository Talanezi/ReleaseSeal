import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from creator_preflight import api as api_module
from creator_preflight.ai_review import GeminiVideoReviewer
from creator_preflight.ai_review import AIReviewError
from creator_preflight.config import PreflightConfig
from creator_preflight.metadata_assist import GeminiMetadataAssistant, MetadataAssistResult
from creator_preflight.content_sketch import sketch_windows
from creator_preflight.content_sketch import build_content_sketch
from creator_preflight.models import (
    ClaimReviewStatus,
    ClaimReviewSummary,
    Finding,
    FindingSeverity,
    FindingStatus,
    PromiseCheckStatus,
    PromiseCheckSummary,
    ScanCompleteness,
    ViewerPassStatus,
    ViewerPassSummary,
)
from creator_preflight.media import MediaInspector
from creator_preflight.release_brief import ai_release_brief, deterministic_release_brief
from creator_preflight.presentation import format_timecode
from creator_preflight.repairs import build_repair_plan
from creator_preflight.models import PublishingPackage, ReviewMode
from creator_preflight.engine import PreflightScanner


def test_deterministic_release_brief_uses_trusted_findings() -> None:
    finding = Finding(
        code="VIDEO_BLACK_SEGMENT", severity=FindingSeverity.WARNING,
        status=FindingStatus.NEEDS_REVIEW, message="A black section was detected.",
        source="video.black", timestamp_start_seconds=2,
        details={"title": "Black section"},
    )
    brief = deterministic_release_brief(
        verdict=FindingStatus.NEEDS_REVIEW,
        completeness=ScanCompleteness.COMPLETE,
        findings=[finding],
    )
    assert brief.headline == "1 item needs attention"
    assert brief.top_actions == ["Black section at 00:02.00"]


def test_release_brief_prioritizes_repair_and_audio_and_groups_static_findings() -> None:
    findings = [
        Finding(code="VIDEO_BLACK_SEGMENT", severity="warning", status="NEEDS_REVIEW", message="Black.", source="video.black", timestamp_start_seconds=24, timestamp_end_seconds=27, details={"title": "Sustained near-black section"}),
        Finding(code="AUDIO_LONG_SILENCE", severity="warning", status="NEEDS_REVIEW", message="Silent.", source="audio.silence", timestamp_start_seconds=54.02, timestamp_end_seconds=59, details={"title": "Long silent section"}),
        *[
            Finding(code="VIDEO_FREEZE_SEGMENT", severity="warning", status="NEEDS_REVIEW", message="Static.", source="video.freeze", timestamp_start_seconds=start, timestamp_end_seconds=start + 2.5, details={"title": "Sustained static-frame section"})
            for start in (96.17, 105.83, 111.54)
        ],
    ]
    brief = deterministic_release_brief(
        verdict=FindingStatus.NEEDS_REVIEW,
        completeness=ScanCompleteness.COMPLETE,
        findings=findings,
        repair_plan=build_repair_plan(findings),
        promise_check=PromiseCheckSummary(status=PromiseCheckStatus.ALIGNED),
        viewer_pass=ViewerPassSummary(status=ViewerPassStatus.CLEAN),
        claim_review=ClaimReviewSummary(status=ClaimReviewStatus.NO_CLAIMS),
    )

    assert brief.top_actions[0] == "Preview the repair for sustained near-black section at 00:24.00"
    assert brief.top_actions[1] == "Confirm whether long silent section at 00:54.02 is intentional"
    assert brief.top_actions[2] == "Review 3 related sustained static-frame findings together, starting at 01:36.17"
    assert "3 related sustained static-frame findings" in brief.summary
    assert "Opening, continuity, and factual review" in brief.summary
    assert len(brief.summary) <= 500


def test_release_brief_does_not_invent_clean_remote_review() -> None:
    finding = Finding(code="AUDIO_LONG_SILENCE", severity="warning", status="NEEDS_REVIEW", message="Silent.", source="audio.silence", timestamp_start_seconds=4, details={"title": "Long silent section"})
    brief = deterministic_release_brief(
        verdict=FindingStatus.NEEDS_REVIEW,
        completeness=ScanCompleteness.COMPLETE,
        findings=[finding],
        repair_plan=build_repair_plan([finding]),
    )
    assert "Opening" not in brief.summary
    assert "continuity" not in brief.summary
    assert "factual" not in brief.summary


def test_canonical_creator_timecodes_round_to_hundredths() -> None:
    assert format_timecode(78.041667) == "01:18.04"
    assert format_timecode(46.208333) == "00:46.21"
    assert format_timecode(126.034625) == "02:06.03"
    assert format_timecode(3723.5) == "1:02:03.50"


def test_release_brief_uses_direct_delivery_time_not_opening_interval_start() -> None:
    finding = Finding(
        code="AI_PROMISE_DELAY", severity="warning", status="NEEDS_REVIEW",
        message="Unrelated opening.", source="ai.gemini.promise",
        timestamp_start_seconds=22,
        details={"title": "Opening may delay the promised subject", "opening_interval_start_seconds": 0, "direct_delivery_seconds": 22},
    )
    brief = deterministic_release_brief(
        verdict=FindingStatus.NEEDS_REVIEW,
        completeness=ScanCompleteness.COMPLETE,
        findings=[finding],
    )
    assert brief.top_actions == ["Opening may delay the promised subject at 00:22.00"]
    assert "00:00" not in " ".join(brief.top_actions)


def test_ai_release_brief_rejects_unknown_action_and_falls_back() -> None:
    finding = Finding(
        code="KNOWN", severity="warning", status="NEEDS_REVIEW", message="Review.", source="test"
    )
    session = SimpleNamespace(generate_text_structured=lambda **kwargs: SimpleNamespace(output=SimpleNamespace(
        headline="Invented", summary="Invented", top_action_codes=["UNKNOWN"], positive_note=None
    )))
    brief = ai_release_brief(
        session, verdict=FindingStatus.NEEDS_REVIEW,
        completeness=ScanCompleteness.COMPLETE, findings=[finding], repair_plan=build_repair_plan([finding]),
    )
    assert brief.source.value == "fallback"
    assert brief.top_actions == ["KNOWN"]


def test_ai_review_prompt_is_about_findings_not_a_video_synopsis() -> None:
    captured = {}
    session = SimpleNamespace(generate_text_structured=lambda **kwargs: (
        captured.update(kwargs) or SimpleNamespace(output=SimpleNamespace(
            headline="One issue to review", summary="Start with the repairable black section.",
            top_action_codes=["VIDEO_BLACK_SEGMENT"], positive_note=None,
        ))
    ))
    finding = Finding(
        code="VIDEO_BLACK_SEGMENT", severity="warning", status="NEEDS_REVIEW",
        message="Black section.", source="video.black", timestamp_start_seconds=78.041667,
        timestamp_end_seconds=82.041667, details={"title": "Black section"},
    )
    brief = ai_release_brief(
        session, verdict=FindingStatus.NEEDS_REVIEW,
        completeness=ScanCompleteness.COMPLETE, findings=[finding],
        repair_plan=build_repair_plan([finding]), inconclusive_claim_count=1,
    )
    assert brief.source.value == "ai"
    assert "Do not summarize what the creator's video is about" in captured["prompt"]
    assert "PREVIEW_REQUIRED" in captured["prompt"]
    assert "inconclusive_factual_claims" in captured["prompt"]
    assert "01:18.04–01:22.04" in captured["prompt"]
    assert "78.041667" not in captured["prompt"]
    assert brief.positive_note == "1 factual claim could not be verified with enough evidence."


def test_ai_release_brief_rejects_raw_float_second_copy() -> None:
    session = SimpleNamespace(generate_text_structured=lambda **kwargs: SimpleNamespace(output=SimpleNamespace(
        headline="Review this", summary="The issue appears at 78.041667 seconds.",
        top_action_codes=[], positive_note=None,
    )))
    brief = ai_release_brief(
        session, verdict=FindingStatus.READY, completeness=ScanCompleteness.COMPLETE,
        findings=[], repair_plan=build_repair_plan([]),
    )
    assert brief.source.value == "fallback"
    assert "78.041667 seconds" not in " ".join(filter(None, [brief.headline, brief.summary, brief.positive_note]))


def test_ai_release_brief_failure_is_a_deterministic_presentation_fallback() -> None:
    session = SimpleNamespace(generate_text_structured=lambda **kwargs: (_ for _ in ()).throw(
        AIReviewError("ai_provider_unavailable", "Provider unavailable.")
    ))
    brief = ai_release_brief(
        session, verdict=FindingStatus.READY,
        completeness=ScanCompleteness.COMPLETE, findings=[], repair_plan=build_repair_plan([]),
    )
    assert brief.source.value == "fallback"
    assert brief.headline == "No release issues found"
    assert brief.top_actions == []


def test_ready_brief_discloses_inconclusive_fact_without_implying_verification() -> None:
    brief = deterministic_release_brief(
        verdict=FindingStatus.READY,
        completeness=ScanCompleteness.COMPLETE,
        findings=[],
        inconclusive_claim_count=1,
    )
    visible = " ".join(filter(None, [brief.headline, brief.summary, brief.positive_note])).lower()
    assert "could not be verified with enough evidence" in visible
    assert "everything verified" not in visible
    assert "all claims supported" not in visible
    assert brief.headline == "No release issues found"


def test_metadata_assist_rejects_fabricated_links() -> None:
    with pytest.raises(ValidationError):
        MetadataAssistResult(
            title_suggestions=["One", "Two", "Three", "Four", "Five"],
            description_draft="Read more at https://example.invalid.",
            cleanup_succeeded=True,
        )


def test_metadata_assist_uses_one_upload_generation_and_cleanup(video_with_audio: Path) -> None:
    files = SimpleNamespace(
        upload=lambda **kwargs: SimpleNamespace(name="files/assist", uri="https://provider.invalid/assist", mime_type="video/mp4", state=SimpleNamespace(name="ACTIVE")),
        get=lambda **kwargs: None,
        delete=lambda **kwargs: None,
    )
    calls = []
    def generate_content(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=json.dumps({
            "title_suggestions": ["One", "Two", "Three", "Four", "Five"],
            "description_draft": "A concise description grounded in the finished video.",
        }))
    client = SimpleNamespace(files=files, models=SimpleNamespace(generate_content=generate_content), close=lambda: None)
    adapter = GeminiVideoReviewer(client_factory=lambda key, timeout: client, environ={"GEMINI_API_KEY": "test"})
    result = GeminiMetadataAssistant(adapter).assist(video_with_audio, config=PreflightConfig().ai_review, media_mime_type="video/mp4")
    assert result.title_suggestions == ["One", "Two", "Three", "Four", "Five"]
    assert len(calls) == 1
    assert result.cleanup_succeeded is True


def test_metadata_assist_api_reuses_upload_safety(video_with_audio: Path, monkeypatch) -> None:
    config = PreflightConfig()
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "test"))
    seen = {}
    class FakeAssistant:
        def assist(self, media_path, *, config, media_mime_type, transcript_text=None):
            proxy = MediaInspector().inspect(media_path)
            seen.update(path=Path(media_path), mime=media_mime_type, duration=proxy.duration_seconds, size=proxy.file_size_bytes, transcript=transcript_text)
            return MetadataAssistResult(
                title_suggestions=["One", "Two", "Three", "Four", "Five"],
                description_draft="A useful description.", cleanup_succeeded=True,
            )
    monkeypatch.setattr(api_module, "GeminiMetadataAssistant", FakeAssistant)
    with video_with_audio.open("rb") as media:
        response = TestClient(api_module.app).post(
            "/api/v1/metadata/assist",
            files={
                "file": ("creator video.mp4", media, "video/mp4"),
                "captions": ("captions.srt", b"1\n00:00:00,000 --> 00:00:01,000\nOpening context\n", "text/plain"),
            },
            headers={"Origin": "http://127.0.0.1:5173"},
        )
    assert response.status_code == 200
    assert response.json()["title_suggestions"] == ["One", "Two", "Three", "Four", "Five"]
    assert seen["mime"] == "video/mp4"
    assert seen["path"].name == "content-sketch.mp4"
    assert seen["duration"] == pytest.approx(MediaInspector().inspect(video_with_audio).duration_seconds, abs=0.2)
    assert seen["transcript"] == "Opening context"
    assert not seen["path"].exists()


def test_long_metadata_sketch_is_bounded_and_spans_the_timeline() -> None:
    windows = sketch_windows(590, sample_count=8, segment_seconds=4)
    assert len(windows) == 8
    assert windows[0] == (0, 4)
    assert windows[-1] == (586, 4)
    assert sum(duration for _, duration in windows) == 32


def test_long_metadata_sketch_renders_a_small_32_second_proxy(tmp_path: Path) -> None:
    source = tmp_path / "long-source.mp4"
    completed = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=90",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=90",
        "-c:v", "mpeg4", "-q:v", "8", "-c:a", "aac", "-shortest", str(source),
    ], capture_output=True, check=False, timeout=60)
    assert completed.returncode == 0
    media = MediaInspector().inspect(source)
    output = build_content_sketch(
        source, tmp_path / "content-sketch.mp4", media,
        PreflightConfig().ai_review.metadata_assist,
    )
    proxy = MediaInspector().inspect(output)
    assert proxy.duration_seconds == pytest.approx(32, abs=0.5)
    assert proxy.width == 320
    assert proxy.height == 180
    assert proxy.file_size_bytes < media.file_size_bytes


def test_tracked_official_demo_contains_small_deterministic_repair_story() -> None:
    root = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo"
    video = root / "creator-preflight-official-demo.mp4"
    assert video.stat().st_size < 5_000_000
    config = PreflightConfig()
    config.rules.video.minimum_width = 640
    config.rules.video.minimum_height = 360
    report = PreflightScanner(config=config).scan(
        video,
        PublishingPackage(
            title=(root / "creator-preflight-official-title.txt").read_text(encoding="utf-8").strip(),
            description=(root / "creator-preflight-official-description.txt").read_text(encoding="utf-8"),
            captions_path=root / "creator-preflight-official-captions.srt",
        ),
        review_mode=ReviewMode.LOCAL,
    )
    timed = {finding.code: (finding.timestamp_start_seconds, finding.timestamp_end_seconds) for finding in report.findings}
    assert timed["VIDEO_SHORT_BLACK_FLASH"] == pytest.approx((46.0, 46.21), abs=0.08)
    assert timed["VIDEO_BLACK_SEGMENT"] == pytest.approx((78.04, 82.04), abs=0.1)
    assert timed["AUDIO_LONG_SILENCE"] == pytest.approx((126.03, 132.01), abs=0.1)
    assert report.repair_plan.preview_required_count == 1
