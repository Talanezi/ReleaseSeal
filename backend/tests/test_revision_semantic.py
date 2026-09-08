from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from releaseseal.ai_review import AIReviewError
from releaseseal.config import RevisionSemanticReviewConfig
from releaseseal.media import MediaInspector
from releaseseal.revision_check import RevisionCheckService
from releaseseal.revision_fixture import generate_revision_source, insert_revision_section, replace_revision_picture
from releaseseal.revision_models import RevisionMap, RevisionSamplingPolicy, RevisionSegment, RevisionSegmentKind, RevisionStreamSummary
from releaseseal.ai_review import GeminiVideoReviewer
from releaseseal.config import AIReviewConfig
from releaseseal.revision_semantic import GeminiRevisionSemanticReviewer, RevisionSemanticProviderResult, RevisionSemanticReviewError, RevisionSemanticReviewService
from releaseseal.revision_semantic_models import RevisionSemanticProviderOutput, RevisionSemanticStatus
from releaseseal.revision_evidence import plan_revision_evidence, render_revision_evidence


def _segment(number: int, kind: RevisionSegmentKind, previous, revised) -> RevisionSegment:
    return RevisionSegment(
        segment_id=f"segment-{number:04d}", kind=kind,
        previous_start_seconds=previous[0] if previous else None, previous_end_seconds=previous[1] if previous else None,
        revised_start_seconds=revised[0] if revised else None, revised_end_seconds=revised[1] if revised else None,
        visual_distance=.5, audio_distance=.5, visual_changed=kind is not RevisionSegmentKind.UNCHANGED,
        audio_changed=kind in (RevisionSegmentKind.REMOVED, RevisionSegmentKind.INSERTED), match_confidence=.9,
        boundary_confidence="high",
    )


def _map(previous_hash="a" * 64, revised_hash="b" * 64) -> RevisionMap:
    streams = RevisionStreamSummary(width=320, height=180, video_codec="h264", has_audio=True, audio_codec="aac")
    return RevisionMap(
        previous_sha256=previous_hash, revised_sha256=revised_hash, previous_duration_seconds=30, revised_duration_seconds=30,
        previous_streams=streams, revised_streams=streams,
        sampling_policy=RevisionSamplingPolicy(visual_samples_per_second=2, maximum_visual_samples=1200, descriptor_width=17, descriptor_height=9, audio_sample_rate=8000, refinement_samples_per_second=6, maximum_refinement_samples=240),
        previous_sample_count=60, revised_sample_count=60, estimated_unchanged_duration_seconds=18, unchanged_ratio=.6,
        segments=[
            _segment(1, RevisionSegmentKind.UNCHANGED, (0, 6), (0, 6)),
            _segment(2, RevisionSegmentKind.REMOVED, (6, 10), None),
            _segment(3, RevisionSegmentKind.UNCHANGED, (10, 16), (6, 12)),
            _segment(4, RevisionSegmentKind.INSERTED, None, (12, 16)),
            _segment(5, RevisionSegmentKind.UNCHANGED, (16, 20), (16, 20)),
            _segment(6, RevisionSegmentKind.CHANGED, (20, 24), (20, 24)),
            _segment(7, RevisionSegmentKind.UNCHANGED, (24, 30), (24, 30)),
        ], analysis_runtime_seconds=.1,
    )


def _report(revision_map=None, notes="00:08 Remove old logo\n00:16 Add card\n00:22 Replace 2024 with 2025\n00:02 No change\nUntimed note"):
    return RevisionCheckService().from_map(revision_map or _map(), notes)


@dataclass
class FakeReviewer:
    outputs: list[object]
    provider: str = "gemini"
    model: str = "fake-flash"

    def __post_init__(self):
        self.calls: list[tuple[Path, Path, str]] = []

    def review(self, previous_clip: Path, revised_clip: Path, *, prompt: str):
        assert previous_clip.name == "previous-evidence.mp4"
        assert revised_clip.name == "revised-evidence.mp4"
        self.calls.append((previous_clip, revised_clip, prompt))
        value = self.outputs[len(self.calls) - 1]
        if isinstance(value, Exception):
            raise value
        return RevisionSemanticProviderResult(value, .2, 2, 1, 2)


def _output(status, confidence=.95):
    return RevisionSemanticProviderOutput(status=status, confidence=confidence, rationale="The requested result is visible in the bounded evidence.", observed_previous="Previous evidence", observed_revised="Revised evidence")


def test_evidence_mapping_covers_changed_removed_inserted_and_bounds() -> None:
    report = _report()
    plans = [plan_revision_evidence(request, report, RevisionSemanticReviewConfig()) for request in report.revision_requests[:3]]
    assert plans[0].change_kinds == ("REMOVED",)
    assert plans[0].previous_range.start_seconds <= 6 and plans[0].revised_range.start_seconds <= 6
    assert plans[1].change_kinds == ("INSERTED",)
    assert plans[1].previous_range.start_seconds <= 16 and plans[1].revised_range.end_seconds >= 16
    assert plans[2].change_kinds == ("CHANGED",)
    assert all(item.previous_range.end_seconds - item.previous_range.start_seconds <= 12 for item in plans)
    assert all(item.revised_range.end_seconds - item.revised_range.start_seconds <= 12 for item in plans)


def test_long_change_is_representative_and_marked_partial() -> None:
    revision_map = _map().model_copy(update={"segments": [_segment(1, RevisionSegmentKind.CHANGED, (0, 20), (0, 20)), _segment(2, RevisionSegmentKind.UNCHANGED, (20, 30), (20, 30))]})
    request = _report(revision_map, "00:10 Replace sequence").revision_requests[0]
    plan = plan_revision_evidence(request, _report(revision_map, "00:10 Replace sequence"), RevisionSemanticReviewConfig())
    assert plan.partial is True
    assert plan.previous_range.end_seconds - plan.previous_range.start_seconds == pytest.approx(12)


def test_real_evidence_clips_are_bounded_playable_and_preserve_audio(tmp_path: Path) -> None:
    previous = generate_revision_source(tmp_path / "previous.mp4", duration_seconds=8)
    revised = replace_revision_picture(previous, tmp_path / "revised.mp4", start_seconds=2, end_seconds=5)
    previous_hash = hashlib.sha256(previous.read_bytes()).hexdigest()
    revised_hash = hashlib.sha256(revised.read_bytes()).hexdigest()
    revision_map = _map(previous_hash, revised_hash).model_copy(update={"previous_duration_seconds": 8, "revised_duration_seconds": 8, "estimated_unchanged_duration_seconds": 5, "segments": [_segment(1, RevisionSegmentKind.CHANGED, (2, 5), (2, 5)), _segment(2, RevisionSegmentKind.UNCHANGED, (5, 8), (5, 8))]})
    report = _report(revision_map, "00:03 Replace graphic")
    plan = plan_revision_evidence(report.revision_requests[0], report, RevisionSemanticReviewConfig(maximum_clip_duration_seconds=6))
    rendered = render_revision_evidence(previous, revised, tmp_path / "clips", plan, report, RevisionSemanticReviewConfig(maximum_clip_duration_seconds=6)) if (tmp_path / "clips").mkdir() is None else None
    assert rendered is not None
    for path in (rendered.previous_path, rendered.revised_path):
        media = MediaInspector().inspect(path)
        assert media.duration_seconds <= 6.1
        assert media.width == 320 and media.height == 180 and media.has_audio
        assert path != previous and path != revised


def test_service_statuses_confidence_isolation_order_limit_hash_and_zero_ineligible(tmp_path: Path, monkeypatch) -> None:
    previous, revised = tmp_path / "p.mp4", tmp_path / "r.mp4"
    previous.write_bytes(b"previous")
    revised.write_bytes(b"revised")
    revision_map = _map(hashlib.sha256(b"previous").hexdigest(), hashlib.sha256(b"revised").hexdigest())
    report = _report(revision_map, "00:08 Remove old logo\n00:16 Add card\n00:22 Replace 2024 with 2025\n00:23 Correct the label\n00:02 No change\nUntimed note")

    class Evidence:
        previous_path = tmp_path / "previous-evidence.mp4"
        revised_path = tmp_path / "revised-evidence.mp4"
        render_seconds = .1
        plan = None
    Evidence.previous_path.write_bytes(b"bounded previous")
    Evidence.revised_path.write_bytes(b"bounded revised")
    monkeypatch.setattr("releaseseal.revision_semantic.render_revision_evidence", lambda *args, **kwargs: Evidence())
    reviewer = FakeReviewer([_output("APPEARS_SATISFIED"), _output("APPEARS_UNRESOLVED"), _output("APPEARS_SATISFIED", .7), AIReviewError("ai_provider_timeout", "Timed out")])
    result = RevisionSemanticReviewService(config=RevisionSemanticReviewConfig(maximum_requests=4, maximum_parallel_requests=1), reviewer=reviewer).review(previous, revised, report)
    assert [item.request_id for item in result.results] == ["request-0001", "request-0002", "request-0003", "request-0004"]
    assert [item.status for item in result.results] == [RevisionSemanticStatus.APPEARS_SATISFIED, RevisionSemanticStatus.APPEARS_UNRESOLVED, RevisionSemanticStatus.INCONCLUSIVE, RevisionSemanticStatus.NOT_REVIEWED]
    assert len(reviewer.calls) == 4
    assert all(call[0] != previous and call[1] != revised for call in reviewer.calls)
    assert result.upload_count == result.delete_count == 6
    no_eligible = _report(revision_map, "00:02 No change\nUntimed")
    reviewer2 = FakeReviewer([])
    empty = RevisionSemanticReviewService(config=RevisionSemanticReviewConfig(), reviewer=reviewer2).review(previous, revised, no_eligible)
    assert empty.results == [] and reviewer2.calls == []
    with pytest.raises(RevisionSemanticReviewError, match="no longer match"):
        RevisionSemanticReviewService(config=RevisionSemanticReviewConfig(), reviewer=reviewer2).review(previous, revised, report.model_copy(update={"revision_map": revision_map.model_copy(update={"previous_sha256": "0" * 64})}))


def test_maximum_requests_marks_overflow_not_reviewed(tmp_path: Path, monkeypatch) -> None:
    previous, revised = tmp_path / "p.mp4", tmp_path / "r.mp4"
    previous.write_bytes(b"p"); revised.write_bytes(b"r")
    revision_map = _map(hashlib.sha256(b"p").hexdigest(), hashlib.sha256(b"r").hexdigest())
    report = _report(revision_map)
    class Evidence:
        previous_path = tmp_path / "previous-evidence.mp4"; revised_path = tmp_path / "revised-evidence.mp4"; render_seconds = 0
    Evidence.previous_path.write_bytes(b"p clip"); Evidence.revised_path.write_bytes(b"r clip")
    monkeypatch.setattr("releaseseal.revision_semantic.render_revision_evidence", lambda *args, **kwargs: Evidence())
    reviewer = FakeReviewer([_output("INCONCLUSIVE")])
    result = RevisionSemanticReviewService(config=RevisionSemanticReviewConfig(maximum_requests=1), reviewer=reviewer).review(previous, revised, report)
    assert len(reviewer.calls) == 1
    assert result.results[1].status is RevisionSemanticStatus.NOT_REVIEWED
    assert result.results[1].reason_code == "revision_semantic_limit_reached"


def test_semantic_copy_never_exposes_evidence_clip_relative_timecodes(tmp_path: Path, monkeypatch) -> None:
    previous, revised = tmp_path / "p.mp4", tmp_path / "r.mp4"
    previous.write_bytes(b"previous")
    revised.write_bytes(b"revised")
    revision_map = _map(hashlib.sha256(b"previous").hexdigest(), hashlib.sha256(b"revised").hexdigest())
    report = _report(revision_map, "00:08 Restore the missing picture")

    class Evidence:
        previous_path = tmp_path / "previous-evidence.mp4"
        revised_path = tmp_path / "revised-evidence.mp4"
        render_seconds = 0

    Evidence.previous_path.write_bytes(b"bounded previous")
    Evidence.revised_path.write_bytes(b"bounded revised")
    monkeypatch.setattr("releaseseal.revision_semantic.render_revision_evidence", lambda *args, **kwargs: Evidence())
    output = RevisionSemanticProviderOutput(
        status="APPEARS_SATISFIED",
        confidence=.95,
        rationale="The previous clip was black from approximately 00:02 to 00:04. The revised clip restores picture at 00:03.",
        observed_previous="Black picture around 00:02.",
        observed_revised="Scenic footage at 00:03.",
    )
    reviewer = FakeReviewer([output])

    result = RevisionSemanticReviewService(
        config=RevisionSemanticReviewConfig(maximum_parallel_requests=1),
        reviewer=reviewer,
    ).review(previous, revised, report).results[0]

    assert "00:02" not in result.rationale
    assert "00:04" not in result.rationale
    assert "00:03" not in result.rationale
    assert "requested region" in result.rationale
    assert "00:" not in f"{result.observed_previous} {result.observed_revised}"
    assert "Do not mention clip-relative timecodes" in reviewer.calls[0][2]


def test_provider_model_rejects_not_reviewed_and_unknown_or_malformed() -> None:
    with pytest.raises(ValueError):
        _output("NOT_REVIEWED")
    with pytest.raises(ValueError):
        _output("VERIFIED")


def test_gemini_pair_provider_uploads_generates_and_deletes_both_clips(tmp_path: Path) -> None:
    previous = tmp_path / "previous.mp4"; revised = tmp_path / "revised.mp4"
    previous.write_bytes(b"bounded previous"); revised.write_bytes(b"bounded revised")
    uploads: list[str] = []; deletes: list[str] = []

    class Remote:
        def __init__(self, name): self.name = name; self.uri = f"uri:{name}"; self.mime_type = "video/mp4"; self.state = type("State", (), {"name": "ACTIVE"})()
    class Files:
        def upload(self, *, file, config): uploads.append(file); return Remote(f"file-{len(uploads)}")
        def delete(self, *, name): deletes.append(name)
        def get(self, *, name): return Remote(name)
    class Models:
        def generate_content(self, **kwargs):
            assert len(kwargs["contents"]) == 3
            return type("Response", (), {"text": _output("APPEARS_SATISFIED").model_dump_json()})()
    class Client:
        files = Files(); models = Models()
        def close(self): pass

    adapter = GeminiVideoReviewer(client_factory=lambda key, timeout: Client(), environ={"GEMINI_API_KEY": "not-a-real-key"})
    result = GeminiRevisionSemanticReviewer(AIReviewConfig(), adapter=adapter).review(previous, revised, prompt="Compare bounded evidence")
    assert result.upload_count == result.delete_count == 2
    assert result.generation_count == 1
    assert uploads == [str(previous), str(revised)]
    assert deletes == ["file-1", "file-2"]


def test_gemini_pair_provider_cleans_uploads_when_generation_fails(tmp_path: Path) -> None:
    previous = tmp_path / "previous.mp4"; revised = tmp_path / "revised.mp4"
    previous.write_bytes(b"p"); revised.write_bytes(b"r")
    deletes: list[str] = []
    class Remote:
        def __init__(self, name): self.name = name; self.uri = name; self.mime_type = "video/mp4"; self.state = type("State", (), {"name": "ACTIVE"})()
    class Files:
        count = 0
        def upload(self, **kwargs): self.count += 1; return Remote(f"file-{self.count}")
        def delete(self, *, name): deletes.append(name)
    class Models:
        def generate_content(self, **kwargs): raise TimeoutError("provider timeout")
    class Client:
        files = Files(); models = Models()
        def close(self): pass
    adapter = GeminiVideoReviewer(client_factory=lambda key, timeout: Client(), environ={"GEMINI_API_KEY": "not-a-real-key"})
    with pytest.raises(AIReviewError) as raised:
        GeminiRevisionSemanticReviewer(AIReviewConfig(), adapter=adapter).review(previous, revised, prompt="Compare")
    assert raised.value.code == "ai_provider_timeout"
    assert deletes == ["file-1", "file-2"]
