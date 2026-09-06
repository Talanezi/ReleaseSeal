from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory as RealTemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from creator_preflight import api as api_module
from creator_preflight.api import app
from creator_preflight.config import PreflightConfig


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
    assert payload["gemini_api_key_configured"] is False
