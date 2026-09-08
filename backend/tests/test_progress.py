from pathlib import Path

from fastapi.testclient import TestClient

from releaseseal import api as api_module
from releaseseal.config import PreflightConfig
from releaseseal.engine import PreflightScanner
from releaseseal.models import PublishingPackage, ReviewMode
from releaseseal.progress import ScanProgressStage, ScanProgressState, ScanProgressStore


def test_progress_is_monotonic_and_never_finishes_early() -> None:
    store = ScanProgressStore()
    record = store.create("full")
    stages = [
        (ScanProgressStage.PREPARING_MEDIA, 8),
        (ScanProgressStage.TECHNICAL_CHECKS, 12),
        (ScanProgressStage.PREPARING_AI_MEDIA, 38),
        (ScanProgressStage.OPENING_REVIEW, 43),
        (ScanProgressStage.CONTINUITY_REVIEW, 58),
        (ScanProgressStage.FACTUAL_REVIEW, 73),
        (ScanProgressStage.PREPARING_REVIEW, 89),
        (ScanProgressStage.FINAL_REPORT, 97),
    ]
    seen = [record.percent]
    for stage, percent in stages:
        store.update(record.progress_id, stage, percent, "Working")
        seen.append(store.get(record.progress_id).percent)  # type: ignore[union-attr]
    store.update(record.progress_id, ScanProgressStage.FINAL_REPORT, 100, "Not done")
    assert store.get(record.progress_id).percent == 99  # type: ignore[union-attr]
    assert seen == sorted(seen)
    assert max(seen) < 100

    store.finish(record.progress_id)
    complete = store.get(record.progress_id)
    assert complete is not None
    assert complete.percent == 100
    assert complete.state is ScanProgressState.COMPLETE
    assert [task.status for task in complete.tasks] == ["Done"] * 5


def test_progress_partial_and_failure_are_terminal_without_fake_content_results() -> None:
    store = ScanProgressStore()
    partial_id = store.create("full").progress_id
    store.update(partial_id, ScanProgressStage.OPENING_REVIEW, 43, "Reviewing the opening")
    store.finish(partial_id, partial=True)
    partial = store.get(partial_id)
    assert partial is not None and partial.state is ScanProgressState.PARTIAL
    assert partial.percent == 100
    assert partial.tasks[0].status == "Done"
    assert all(task.status == "Unavailable" for task in partial.tasks[1:])

    failed_id = store.create("local").progress_id
    store.update(failed_id, ScanProgressStage.TECHNICAL_CHECKS, 12, "Checking")
    store.fail(failed_id)
    failed = store.get(failed_id)
    assert failed is not None and failed.state is ScanProgressState.FAILED
    assert failed.percent < 100


def test_scanner_reports_real_local_boundaries(video_with_audio: Path) -> None:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    config.rules.video.allowed_aspect_ratios = ["16:9"]
    events: list[tuple[str, int]] = []
    report = PreflightScanner(config=config).scan(
        video_with_audio,
        PublishingPackage(title="Title", description="Description"),
        review_mode=ReviewMode.LOCAL,
        progress=lambda stage, percent, message: events.append((stage, percent)),
    )
    assert report.verdict.value == "READY"
    assert events == [("technical_checks", 12), ("technical_checks", 78), ("final_report", 97)]
    assert all(percent < 100 for _, percent in events)


def test_progress_api_wraps_real_multipart_scan(video_with_audio: Path, monkeypatch) -> None:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    config.rules.video.allowed_aspect_ratios = ["16:9"]
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "test"))
    client = TestClient(api_module.app)
    created = client.post(
        "/api/v1/preflight/progress",
        data={"review_mode": "local"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    progress_id = created.json()["progress_id"]
    with video_with_audio.open("rb") as media:
        response = client.post(
            "/api/v1/preflight/scan",
            files={"file": ("progress.mp4", media, "video/mp4")},
            data={"title": "Title", "description": "Description", "review_mode": "local", "progress_id": progress_id},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
    assert response.status_code == 200
    terminal = client.get(f"/api/v1/preflight/progress/{progress_id}").json()
    assert terminal["state"] == "COMPLETE"
    assert terminal["percent"] == 100
