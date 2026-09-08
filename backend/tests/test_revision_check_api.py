from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory as RealTemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from releaseseal import api as api_module
from releaseseal.api import app
from releaseseal.config import PreflightConfig
from releaseseal.media import MediaInspector
from releaseseal.revision_check import RevisionCheckService
from releaseseal.revision_fixture import generate_revision_source, replace_revision_picture
from releaseseal.revision_semantic import RevisionSemanticProviderResult
from releaseseal.revision_semantic_models import RevisionSemanticProviderOutput


client = TestClient(app)


def test_revision_api_accepts_two_real_uploads_and_never_uses_ai(video_with_audio: Path, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with video_with_audio.open("rb") as previous, video_with_audio.open("rb") as revised:
        response = client.post(
            "/api/v1/revisions/check",
            files={
                "previous_file": ("previous cut.mp4", previous, "video/mp4"),
                "revised_file": ("revised cut.mp4", revised, "video/mp4"),
            },
            data={"notes": "00:00 Check opening\nUntimed request"},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert payload["previous_filename"] == "previous cut.mp4"
    assert payload["revised_filename"] == "revised cut.mp4"
    assert payload["revision_map"]["identical_file_fast_path"] is True
    assert payload["requested_changes_not_detected_count"] == 1
    assert payload["requests_needing_location_count"] == 1
    assert payload["additional_change_count"] == 0


def test_revision_receipt_route_binds_previous_and_revised_roles(video_with_audio: Path) -> None:
    report = RevisionCheckService().check(video_with_audio, video_with_audio, "00:00 Check opening")
    with video_with_audio.open("rb") as previous, video_with_audio.open("rb") as revised:
        response = client.post(
            "/api/v1/release-receipts/revision",
            files={"previous_file": ("previous.mp4", previous), "revised_file": ("revised.mp4", revised)},
            data={"revision_check_json": report.model_dump_json(), "notes": "00:00 Check opening"},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["receipt_kind"] == "REVISION"
    assert payload["previous_video"]["sha256"] == report.revision_map.previous_sha256
    assert payload["revised_video"]["sha256"] == report.revision_map.revised_sha256
    assert payload["deterministic_results"]["requested_results"][0]["status"] == "NO_CHANGE_DETECTED"


@pytest.mark.parametrize("oversized_field", ["previous_file", "revised_file"])
def test_revision_api_bounds_each_upload(oversized_field: str, monkeypatch) -> None:
    config = PreflightConfig()
    config.api.maximum_video_upload_size_bytes = 3
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "test"))
    files = {
        "previous_file": ("previous.mp4", b"one", "video/mp4"),
        "revised_file": ("revised.mp4", b"two", "video/mp4"),
    }
    files[oversized_field] = (f"{oversized_field}.mp4", b"four", "video/mp4")
    response = client.post("/api/v1/revisions/check", files=files)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "video_upload_too_large"


@pytest.mark.parametrize("invalid_field", ["previous_file", "revised_file"])
def test_revision_api_handles_either_invalid_media_safely(
    invalid_field: str, video_with_audio: Path
) -> None:
    valid_bytes = video_with_audio.read_bytes()
    files = {
        "previous_file": ("previous.mp4", valid_bytes, "video/mp4"),
        "revised_file": ("revised.mp4", valid_bytes, "video/mp4"),
    }
    files[invalid_field] = (f"{invalid_field}.mp4", b"not media", "video/mp4")
    response = client.post("/api/v1/revisions/check", files=files)
    assert response.status_code == 400
    expected_code = "revision_previous_unreadable" if invalid_field == "previous_file" else "revision_revised_unreadable"
    assert response.json()["error"]["code"] == expected_code
    assert "stderr" not in response.text.lower()


def test_revision_api_origin_capacity_and_temp_cleanup(video_with_audio: Path, tmp_path: Path, monkeypatch) -> None:
    with video_with_audio.open("rb") as previous, video_with_audio.open("rb") as revised:
        denied = client.post(
            "/api/v1/revisions/check",
            headers={"Origin": "https://malicious.example"},
            files={
                "previous_file": ("previous.mp4", previous, "video/mp4"),
                "revised_file": ("revised.mp4", revised, "video/mp4"),
            },
        )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "request_origin_not_allowed"

    config = PreflightConfig()
    config.api.maximum_concurrent_scans = 1
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "test"))
    assert api_module._scan_capacity.acquire(1)
    try:
        with video_with_audio.open("rb") as previous, video_with_audio.open("rb") as revised:
            busy = client.post(
                "/api/v1/revisions/check",
                files={
                    "previous_file": ("previous.mp4", previous, "video/mp4"),
                    "revised_file": ("revised.mp4", revised, "video/mp4"),
                },
            )
    finally:
        api_module._scan_capacity.release()
    assert busy.status_code == 503
    assert busy.json()["error"]["code"] == "scan_capacity_reached"

    created: list[Path] = []

    def recording_directory(*args, **kwargs):
        temporary = RealTemporaryDirectory(*args, dir=tmp_path, **kwargs)
        created.append(Path(temporary.name))
        return temporary

    monkeypatch.setattr(api_module, "TemporaryDirectory", recording_directory)
    with video_with_audio.open("rb") as previous, video_with_audio.open("rb") as revised:
        response = client.post(
            "/api/v1/revisions/check",
            files={
                "previous_file": ("previous.mp4", previous, "video/mp4"),
                "revised_file": ("revised.mp4", revised, "video/mp4"),
            },
        )
    assert response.status_code == 200
    assert created and all(not path.exists() for path in created)


def test_capabilities_exposes_revision_independently_of_gemini(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["revision_check_available"] is True
    assert payload["revision_semantic_review_available"] is False
    assert payload["gemini_api_key_configured"] is False


def test_semantic_route_uses_real_multipart_scanner_evidence_boundary(tmp_path: Path, monkeypatch) -> None:
    previous = generate_revision_source(tmp_path / "previous.mp4", duration_seconds=8)
    revised = replace_revision_picture(previous, tmp_path / "revised.mp4", start_seconds=2, end_seconds=5)
    report = RevisionCheckService().check(previous, revised, "00:03 Replace 2024 with 2025")
    captured: list[tuple[Path, Path]] = []

    class FakeReviewer:
        provider = "gemini"
        model = "fake-flash"

        def review(self, previous_clip: Path, revised_clip: Path, *, prompt: str):
            assert "Replace 2024 with 2025" in prompt
            assert previous_clip not in (previous, revised) and revised_clip not in (previous, revised)
            assert MediaInspector().inspect(previous_clip).duration_seconds <= 12.1
            assert MediaInspector().inspect(revised_clip).duration_seconds <= 12.1
            captured.append((previous_clip, revised_clip))
            return RevisionSemanticProviderResult(
                RevisionSemanticProviderOutput(
                    status="APPEARS_SATISFIED", confidence=.95, rationale="The revised bounded clip shows 2025.",
                    observed_previous="The previous clip shows 2024.", observed_revised="The revised clip shows 2025.",
                ), .01, 2, 1, 2,
            )

    monkeypatch.setattr(api_module, "GeminiRevisionSemanticReviewer", lambda config: FakeReviewer())
    with previous.open("rb") as previous_handle, revised.open("rb") as revised_handle:
        response = client.post(
            "/api/v1/revisions/semantic-review",
            files={
                "previous_file": ("previous.mp4", previous_handle, "video/mp4"),
                "revised_file": ("revised.mp4", revised_handle, "video/mp4"),
            },
            data={"revision_check_json": report.model_dump_json()},
        )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] == "APPEARS_SATISFIED"
    assert response.json()["upload_count"] == response.json()["delete_count"] == 2
    assert captured and all(not path.exists() for pair in captured for path in pair)


def test_semantic_route_rejects_origin_and_stale_source(video_with_audio: Path, monkeypatch) -> None:
    report = RevisionCheckService().check(video_with_audio, video_with_audio, "00:00 Opening")
    with video_with_audio.open("rb") as previous, video_with_audio.open("rb") as revised:
        denied = client.post(
            "/api/v1/revisions/semantic-review",
            headers={"Origin": "https://malicious.example"},
            files={"previous_file": ("p.mp4", previous), "revised_file": ("r.mp4", revised)},
            data={"revision_check_json": report.model_dump_json()},
        )
    assert denied.status_code == 403

    stale = report.model_copy(update={"revision_map": report.revision_map.model_copy(update={"previous_sha256": "0" * 64})})
    class NeverReviewer:
        provider = "gemini"; model = "fake"
        def review(self, *args, **kwargs):
            raise AssertionError("provider must not be invoked")
    monkeypatch.setattr(api_module, "GeminiRevisionSemanticReviewer", lambda config: NeverReviewer())
    with video_with_audio.open("rb") as previous, video_with_audio.open("rb") as revised:
        mismatch = client.post(
            "/api/v1/revisions/semantic-review",
            files={"previous_file": ("p.mp4", previous), "revised_file": ("r.mp4", revised)},
            data={"revision_check_json": stale.model_dump_json()},
        )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "revision_source_mismatch"
