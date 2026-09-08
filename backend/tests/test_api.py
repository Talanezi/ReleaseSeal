from pathlib import Path
import json
import struct
import zlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from tempfile import TemporaryDirectory as RealTemporaryDirectory

from releaseseal.api import app
from releaseseal import api as api_module
from releaseseal.detectors import DetectorExecutionError
from releaseseal.config import PreflightConfig
from releaseseal.ai_review import GeminiVideoReviewer
from releaseseal.captions import SpeechSegment
from releaseseal.engine import PreflightScanner
from releaseseal.models import PublishingPackage
from releaseseal.repair_models import RepairOperation
from releaseseal.repairs import FFmpegRepairEngine
from releaseseal.release_contract import MaxDuration, ReleaseContract, RequiredExactToken
from releaseseal.transcription import TranscriptionUnavailableError

client = TestClient(app)


def _tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )


def test_api_upload_success(video_with_audio: Path) -> None:
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/media/inspect",
            files={"file": ("uploaded video.mp4", media_file, "video/mp4")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["width"] == 160
    assert payload["height"] == 90
    assert payload["has_video"] is True
    assert payload["video_codec"] == "mpeg4"
    assert payload["has_audio"] is True
    assert payload["audio_codec"] == "aac"
    assert 0.9 <= payload["duration_seconds"] <= 1.2


def test_api_invalid_media_error_is_structured() -> None:
    response = client.post(
        "/api/v1/media/inspect",
        files={"file": ("invalid.mp4", b"not a media file", "video/mp4")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "invalid_media",
            "message": "FFprobe could not parse the supplied media file.",
            "details": {"ffprobe_exit_code": 1},
        }
    }


def test_api_zero_byte_upload_error_is_structured() -> None:
    response = client.post(
        "/api/v1/media/inspect",
        files={"file": ("empty.mp4", b"", "video/mp4")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_file"


def test_unified_api_scan_returns_preflight_report(video_with_audio: Path) -> None:
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={"file": ("uploaded video.mp4", media_file, "video/mp4")},
            data={"title": "A title", "description": "A description"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.12"
    assert payload["review_mode"] == "local"
    assert payload["scan_completeness"] == "COMPLETE"
    assert payload["ai_review"]["status"] == "disabled"
    assert payload["verdict"] == "BLOCKED"
    assert payload["media"]["width"] == 160
    assert payload["checks_run_count"] == len(payload["checks"])
    assert payload["critical_count"] == 2


def test_scan_accepts_typed_contract_and_blocks_on_real_requirement(video_with_audio: Path) -> None:
    contract = ReleaseContract(requirements=[MaxDuration(
        id="duration", type="MAX_DURATION", instruction="Keep this under half a second", maximum_seconds=.5,
    )])
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={"file": ("video.mp4", media_file, "video/mp4")},
            data={"title": "A title", "description": "A description", "release_contract_json": contract.model_dump_json()},
        )
    assert response.status_code == 200
    assert response.json()["release_contract"]["failed_count"] == 1
    assert response.json()["verdict"] == "BLOCKED"


def test_scan_rejects_untyped_release_contract(video_with_audio: Path) -> None:
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={"file": ("video.mp4", media_file, "video/mp4")},
            data={"release_contract_json": '{"requirements":[{"type":"SHELL","id":"bad","instruction":"bad"}]}'},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "release_contract_invalid"


def test_extract_contract_route_returns_validated_contract(monkeypatch) -> None:
    contract = ReleaseContract(requirements=[RequiredExactToken(
        id="promo", type="REQUIRED_EXACT_TOKEN", instruction="Use SAVE25", value="SAVE25",
        provenance="extracted", source_excerpt="Use SAVE25",
    )])
    monkeypatch.setattr(api_module, "GeminiReleaseContractExtractor", lambda: SimpleNamespace(extract=lambda brief, config: contract))
    response = client.post("/api/v1/release-contracts/extract", data={"brief": "Use SAVE25"})
    assert response.status_code == 200
    assert response.json()["requirements"][0]["value"] == "SAVE25"


def test_audio_evidence_recovery_and_confirmation_use_real_multipart_boundary(
    monkeypatch, video_with_audio: Path,
) -> None:
    contract = ReleaseContract(requirements=[RequiredExactToken(
        id="promo", type="REQUIRED_EXACT_TOKEN", instruction="Say SAVE25", value="SAVE25",
    )])
    with video_with_audio.open("rb") as media_file:
        scan = client.post(
            "/api/v1/preflight/scan",
            files={"file": ("release.mp4", media_file, "video/mp4")},
            data={"title": "Release", "release_contract_json": contract.model_dump_json()},
        )
    assert scan.status_code == 200
    assert scan.json()["release_contract"]["results"][0]["status"] == "NOT_EVALUATED"

    class FakeTranscriber:
        def transcribe(self, media_path, config):
            assert Path(media_path).suffix == ".mp4"
            assert config.local_files_only is True
            return [SpeechSegment(.25, .75, "Use SAVE25 today")]

    monkeypatch.setattr(api_module, "WhisperTranscriber", FakeTranscriber)
    with video_with_audio.open("rb") as media_file:
        recovered = client.post(
            "/api/v1/release-contracts/recover-audio-evidence",
            files={"file": ("release.mp4", media_file, "video/mp4")},
            data={"report_json": json.dumps(scan.json())},
        )
    assert recovered.status_code == 200
    recovered_json = recovered.json()
    assert recovered_json["release_contract"]["results"][0]["status"] == "NEEDS_REVIEW"
    assert recovered_json["release_contract"]["results"][0]["evidence_source"] == "LOCAL_MACHINE_TRANSCRIPT"
    assert recovered_json["critical_count"] == scan.json()["critical_count"]
    assert recovered_json["release_contract"]["failed_count"] == 0
    candidate = recovered_json["audio_evidence"]["candidates"][0]
    assert candidate["artifact_sha256"] == recovered_json["audio_evidence"]["artifact_sha256"]
    assert recovered_json["release_plan"]["confirm_evidence_count"] == 1

    with video_with_audio.open("rb") as media_file:
        confirmed = client.post(
            "/api/v1/release-contracts/confirm-audio-evidence",
            files={"file": ("release.mp4", media_file, "video/mp4")},
            data={"report_json": json.dumps(recovered_json), "candidate_id": candidate["candidate_id"]},
        )
    assert confirmed.status_code == 200
    confirmed_json = confirmed.json()
    result = confirmed_json["release_contract"]["results"][0]
    assert result["status"] == "PASS"
    assert result["evidence_source"] == "HUMAN_CONFIRMED_AUDIO_EVIDENCE"
    assert result["audio_evidence"]["artifact_sha256"] == candidate["artifact_sha256"]
    assert confirmed_json["audio_evidence"]["confirmations"][0]["confirmed_value"] == "SAVE25"
    assert confirmed_json["release_plan"]["confirm_evidence_count"] == 0


def test_local_caption_generation_reuses_machine_draft_for_advisory_evidence(
    monkeypatch, video_with_audio: Path,
) -> None:
    calls = 0

    class FakeTranscriber:
        def transcribe(self, media_path, config):
            nonlocal calls
            calls += 1
            assert config.local_files_only is True
            return [SpeechSegment(.25, .75, "Use SAVE25 today")]

    monkeypatch.setattr(api_module, "WhisperTranscriber", FakeTranscriber)
    with video_with_audio.open("rb") as media_file:
        generated = client.post(
            "/api/v1/captions/generate",
            files={"file": ("release.mp4", media_file, "video/mp4")},
        )
    assert generated.status_code == 200
    draft = generated.json()
    assert draft["status"] == "COMPLETED"
    assert draft["source"] == "LOCAL_MACHINE_TRANSCRIPT"
    assert draft["download_filename"] == "release.generated.srt"
    assert "00:00:00,250 --> 00:00:00,750" in draft["srt_text"]

    contract = ReleaseContract(requirements=[RequiredExactToken(
        id="promo", type="REQUIRED_EXACT_TOKEN", instruction="Say SAVE25", value="SAVE25",
    )])
    report = PreflightScanner(config=PreflightConfig()).scan(
        video_with_audio, PublishingPackage(title="Release", release_contract=contract)
    )
    with video_with_audio.open("rb") as media_file:
        recovered = client.post(
            "/api/v1/release-contracts/recover-audio-evidence",
            files={"file": ("release.mp4", media_file, "video/mp4")},
            data={"report_json": report.model_dump_json(), "generated_captions_json": json.dumps(draft)},
        )
    assert recovered.status_code == 200
    assert calls == 1
    result = recovered.json()["release_contract"]["results"][0]
    assert result["status"] == "NEEDS_REVIEW"
    assert result["evidence_source"] == "LOCAL_MACHINE_TRANSCRIPT"


def test_local_caption_model_unavailable_is_controlled(monkeypatch, video_with_audio: Path) -> None:
    class UnavailableTranscriber:
        def transcribe(self, media_path, config):
            raise TranscriptionUnavailableError("transcription_model_unavailable", "not installed")

    monkeypatch.setattr(api_module, "WhisperTranscriber", UnavailableTranscriber)
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/captions/generate",
            files={"file": ("release.mp4", media_file, "video/mp4")},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "UNAVAILABLE"
    assert response.json()["reason"] == "Local caption model unavailable."


def test_local_caption_generation_handles_no_audio_and_origin(
    monkeypatch, video_without_audio: Path, video_with_audio: Path,
) -> None:
    class MustNotTranscribe:
        def transcribe(self, media_path, config):
            raise AssertionError("video without audio must not invoke transcription")

    monkeypatch.setattr(api_module, "WhisperTranscriber", MustNotTranscribe)
    with video_without_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/captions/generate",
            files={"file": ("silent.mp4", media_file, "video/mp4")},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "UNAVAILABLE"
    assert "no audio track" in response.json()["reason"]
    with video_with_audio.open("rb") as media_file:
        denied = client.post(
            "/api/v1/captions/generate",
            files={"file": ("release.mp4", media_file, "video/mp4")},
            headers={"Origin": "https://evil.example"},
        )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "request_origin_not_allowed"


def test_audio_confirmation_rejects_changed_artifact(monkeypatch, video_with_audio: Path) -> None:
    contract = ReleaseContract(requirements=[RequiredExactToken(
        id="promo", type="REQUIRED_EXACT_TOKEN", instruction="Say SAVE25", value="SAVE25",
    )])
    report = PreflightScanner(config=PreflightConfig()).scan(
        video_with_audio, PublishingPackage(title="Release", release_contract=contract)
    )

    class FakeTranscriber:
        def transcribe(self, media_path, config):
            return [SpeechSegment(.25, .75, "SAVE25")]

    monkeypatch.setattr(api_module, "WhisperTranscriber", FakeTranscriber)
    with video_with_audio.open("rb") as media_file:
        recovered = client.post(
            "/api/v1/release-contracts/recover-audio-evidence",
            files={"file": ("release.mp4", media_file, "video/mp4")},
            data={"report_json": report.model_dump_json()},
        ).json()
    changed = bytearray(video_with_audio.read_bytes())
    changed[-1] ^= 1
    response = client.post(
        "/api/v1/release-contracts/confirm-audio-evidence",
        files={"file": ("release.mp4", bytes(changed), "video/mp4")},
        data={"report_json": json.dumps(recovered), "candidate_id": recovered["audio_evidence"]["candidates"][0]["candidate_id"]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "audio_evidence_invalid"


def test_audio_evidence_model_unavailable_is_not_a_content_failure(monkeypatch, video_with_audio: Path) -> None:
    contract = ReleaseContract(requirements=[RequiredExactToken(
        id="promo", type="REQUIRED_EXACT_TOKEN", instruction="Say SAVE25", value="SAVE25",
    )])
    report = PreflightScanner(config=PreflightConfig()).scan(
        video_with_audio, PublishingPackage(title="Release", release_contract=contract)
    )

    class UnavailableTranscriber:
        def transcribe(self, media_path, config):
            raise TranscriptionUnavailableError("transcription_model_unavailable", "No local model is installed.")

    monkeypatch.setattr(api_module, "WhisperTranscriber", UnavailableTranscriber)
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/release-contracts/recover-audio-evidence",
            files={"file": ("release.mp4", media_file, "video/mp4")},
            data={"report_json": report.model_dump_json()},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["audio_evidence"]["status"] == "UNAVAILABLE"
    assert payload["release_contract"]["results"][0]["status"] == "NOT_EVALUATED"
    assert payload["critical_count"] == report.critical_count


def test_final_export_receipt_route_hashes_exact_uploaded_package(video_with_audio: Path) -> None:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    config.rules.video.allowed_aspect_ratios = ["16:9"]
    report = PreflightScanner(config=config).scan(
        video_with_audio,
        PublishingPackage(title="Exact title", description="Exact description"),
    )
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/release-receipts/final-export",
            files={"file": ("final.mp4", media_file, "video/mp4")},
            data={"report_json": report.model_dump_json(), "title": "Exact title", "description": "Exact description"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["receipt_kind"] == "FINAL_EXPORT"
    assert payload["package"]["shipping_video"]["size_bytes"] == video_with_audio.stat().st_size
    assert len(payload["package"]["shipping_video"]["sha256"]) == 64
    assert payload["verdict"] == report.verdict.value


def test_unified_api_anomaly_report_matches_real_frontend_contract(
    api_anomaly_video: Path,
) -> None:
    with api_anomaly_video.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={"file": ("api-known-anomalies.mp4", media_file, "video/mp4")},
            data={
                "title": "T" * 108,
                "description": "A real end-to-end ReleaseSeal scan.",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.12"
    assert payload["ai_review"]["status"] == "disabled"
    assert payload["verdict"] == "NEEDS_REVIEW"
    assert payload["media"]["width"] == 1280
    assert payload["media"]["height"] == 720
    assert payload["checks_run_count"] == 14
    assert payload["passed_check_count"] == 9
    assert payload["warning_count"] == 5
    assert payload["critical_count"] == 0

    findings = {finding["code"]: finding for finding in payload["findings"]}
    assert set(findings) == {
        "VIDEO_BLACK_SEGMENT",
        "AUDIO_LONG_SILENCE",
        "VIDEO_FREEZE_SEGMENT",
        "AUDIO_PEAK_WARNING",
        "TITLE_LENGTH_RECOMMENDATION",
    }
    assert findings["VIDEO_BLACK_SEGMENT"]["timestamp_start_seconds"] == pytest.approx(2.0, abs=0.2)
    assert findings["VIDEO_BLACK_SEGMENT"]["timestamp_end_seconds"] == pytest.approx(5.0, abs=0.2)
    assert findings["AUDIO_LONG_SILENCE"]["timestamp_start_seconds"] == pytest.approx(3.0, abs=0.2)
    assert findings["AUDIO_LONG_SILENCE"]["timestamp_end_seconds"] == pytest.approx(6.0, abs=0.2)
    assert findings["VIDEO_FREEZE_SEGMENT"]["timestamp_start_seconds"] == pytest.approx(7.0, abs=0.2)
    assert findings["VIDEO_FREEZE_SEGMENT"]["timestamp_end_seconds"] == pytest.approx(10.0, abs=0.2)


def test_capabilities_are_non_secret_and_report_full_review_availability(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ffmpeg_available"] is True
    assert payload["ffprobe_available"] is True
    assert payload["gemini_dependency_available"] is True
    assert payload["gemini_api_key_configured"] is True
    assert payload["full_review_available"] is True
    assert payload["supported_review_modes"] == ["full", "local"]
    assert payload["maximum_video_upload_size_bytes"] == 2_147_483_648
    assert "GEMINI_API_KEY" not in response.text
    assert "test-only-key" not in response.text


def test_browser_origin_is_required_to_match_allowlist(video_with_audio: Path) -> None:
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            headers={"Origin": "https://malicious.example"},
            files={"file": ("video.mp4", media_file, "video/mp4")},
            data={"review_mode": "local"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "request_origin_not_allowed"


def test_streaming_video_upload_limit_is_enforced(monkeypatch) -> None:
    config = PreflightConfig()
    config.api.maximum_video_upload_size_bytes = 3
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "test"))
    response = client.post(
        "/api/v1/preflight/scan",
        files={"file": ("video.mp4", b"four", "video/mp4")},
        data={"review_mode": "local"},
    )
    assert response.status_code == 413
    assert response.json()["error"] == {
        "code": "video_upload_too_large",
        "message": "Video exceeds the configured 3-byte upload limit.",
        "details": {"maximum_bytes": 3},
    }


def test_process_local_scan_capacity_returns_structured_busy(video_with_audio: Path, monkeypatch) -> None:
    config = PreflightConfig()
    config.api.maximum_concurrent_scans = 1
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "test"))
    assert api_module._scan_capacity.acquire(1) is True
    try:
        with video_with_audio.open("rb") as media_file:
            response = client.post(
                "/api/v1/preflight/scan",
                files={"file": ("video.mp4", media_file, "video/mp4")},
                data={"review_mode": "local"},
            )
    finally:
        api_module._scan_capacity.release()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "scan_capacity_reached"


def test_repair_preview_and_apply_return_playable_mp4_and_cleanup(
    api_anomaly_video: Path, tmp_path: Path, monkeypatch
) -> None:
    created: list[Path] = []

    def temporary_repair_directory(*, prefix: str) -> str:
        path = tmp_path / f"{prefix}{len(created)}"
        path.mkdir()
        created.append(path)
        return str(path)

    monkeypatch.setattr(api_module, "mkdtemp", temporary_repair_directory)
    operation = {"operation_type": "REMOVE_RANGE", "start_seconds": 2, "end_seconds": 5}
    with api_anomaly_video.open("rb") as media_file:
        preview = client.post(
            "/api/v1/repairs/preview",
            files={"file": ("source video.mp4", media_file, "video/mp4")},
            data={"operation_json": json.dumps(operation)},
        )
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"].startswith("video/mp4")
    assert preview.headers["content-disposition"].endswith('filename="source-video.repair-preview.mp4"')
    preview_path = tmp_path / "returned-preview.mp4"
    preview_path.write_bytes(preview.content)
    preview_media = api_module.MediaInspector().inspect(preview_path)
    assert preview_media.has_video is True
    assert preview_media.has_audio is True

    with api_anomaly_video.open("rb") as media_file:
        applied = client.post(
            "/api/v1/repairs/apply",
            files={"file": ("source video.mp4", media_file, "video/mp4")},
            data={"operations_json": json.dumps({"operations": [operation]})},
        )
    assert applied.status_code == 200, applied.text
    assert float(applied.headers["x-repair-removed-duration"]) == pytest.approx(3)
    assert float(applied.headers["x-repair-output-duration"]) == pytest.approx(9, abs=0.3)
    assert applied.headers["content-disposition"].endswith('filename="source-video.repaired.mp4"')
    output_path = tmp_path / "returned-repair.mp4"
    output_path.write_bytes(applied.content)
    output_media = api_module.MediaInspector().inspect(output_path)
    assert output_media.has_video is True
    assert output_media.has_audio is True
    assert created and all(not path.exists() for path in created)


def test_repair_api_reuses_upload_limit_origin_and_capacity(
    video_with_audio: Path, monkeypatch
) -> None:
    operation = json.dumps({"operation_type": "REMOVE_RANGE", "start_seconds": 0.2, "end_seconds": 0.4})
    with video_with_audio.open("rb") as media_file:
        denied = client.post(
            "/api/v1/repairs/preview",
            headers={"Origin": "https://malicious.example"},
            files={"file": ("video.mp4", media_file, "video/mp4")},
            data={"operation_json": operation},
        )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "request_origin_not_allowed"

    config = PreflightConfig()
    config.api.maximum_video_upload_size_bytes = 3
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "test"))
    too_large = client.post(
        "/api/v1/repairs/preview",
        files={"file": ("video.mp4", b"four", "video/mp4")},
        data={"operation_json": operation},
    )
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "video_upload_too_large"

    config.api.maximum_video_upload_size_bytes = 1_000_000
    config.api.maximum_concurrent_scans = 1
    assert api_module._scan_capacity.acquire(1) is True
    try:
        with video_with_audio.open("rb") as media_file:
            busy = client.post(
                "/api/v1/repairs/preview",
                files={"file": ("video.mp4", media_file, "video/mp4")},
                data={"operation_json": operation},
            )
    finally:
        api_module._scan_capacity.release()
    assert busy.status_code == 503
    assert busy.json()["error"]["code"] == "scan_capacity_reached"


def test_repair_api_rejects_overlapping_and_entire_video_operations(
    video_with_audio: Path,
) -> None:
    overlapping = {
        "operations": [
            {"operation_type": "REMOVE_RANGE", "start_seconds": 0.1, "end_seconds": 0.5},
            {"operation_type": "REMOVE_RANGE", "start_seconds": 0.4, "end_seconds": 0.8},
        ]
    }
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/repairs/apply",
            files={"file": ("video.mp4", media_file, "video/mp4")},
            data={"operations_json": json.dumps(overlapping)},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "repair_ranges_overlap"

    entire = {
        "operations": [
            {"operation_type": "REMOVE_RANGE", "start_seconds": 0, "end_seconds": 1},
        ]
    }
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/repairs/apply",
            files={"file": ("video.mp4", media_file, "video/mp4")},
            data={"operations_json": json.dumps(entire)},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "repair_would_remove_entire_video"


def test_browser_mp4_full_review_preserves_provider_media_identity(
    video_with_audio: Path, monkeypatch
) -> None:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    config.rules.video.allowed_aspect_ratios = ["16:9"]
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "typed defaults"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")

    class FakeFiles:
        upload_count = 0
        delete_count = 0

        def upload(self, *, file, config):
            path = Path(file)
            assert path.is_file()
            assert path.suffix == ".mp4"
            assert config["mime_type"] == "video/mp4"
            assert config["display_name"] == "upload.mp4"
            self.upload_count += 1
            return SimpleNamespace(
                name="files/test", uri="https://provider.invalid/test",
                mime_type="video/mp4", state=SimpleNamespace(name="ACTIVE"),
            )

        def get(self, *, name):
            raise AssertionError(f"active upload should not be polled: {name}")

        def delete(self, *, name):
            assert name == "files/test"
            self.delete_count += 1

    class FakeModels:
        calls = 0

        def generate_content(self, **kwargs):
            self.calls += 1
            schema = kwargs["config"]["response_json_schema"]["title"]
            payloads = {
                "PromiseReviewResult": {
                    "inferred_promise": "Explain the test subject.",
                    "first_substantive_address_seconds": 0.0,
                    "first_substantive_address_evidence": "The explanation begins.",
                    "overall_delivery": "aligned",
                    "overall_delivery_explanation": "The video delivers the title.",
                    "confidence": 0.95,
                    "thumbnail_alignment": None,
                    "thumbnail_alignment_explanation": None,
                    "issues": [],
                },
                "ViewerPassResult": {
                    "overall_status": "clean", "summary": "No issues.", "issues": [],
                },
                "ClaimExtractionResult": {"claims": []},
                "ReleaseBriefDraft": {
                    "headline": "Ready for release",
                    "summary": "The completed checks found no release issue.",
                    "top_action_codes": [],
                    "positive_note": "Technical and editorial checks completed.",
                },
            }
            return SimpleNamespace(text=json.dumps(payloads[schema]), candidates=[])

    fake_client = SimpleNamespace(files=FakeFiles(), models=FakeModels(), close=lambda: None)
    monkeypatch.setattr(
        GeminiVideoReviewer,
        "_create_client",
        lambda self, api_key, timeout_seconds: fake_client,
    )
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            headers={"Origin": "http://127.0.0.1:5173"},
            files={"file": ("browser selected video.mp4", media_file, "video/mp4")},
            data={"title": "Test title", "description": "Test description", "review_mode": "full"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["review_mode"] == "full"
    assert payload["scan_completeness"] == "COMPLETE"
    assert payload["promise_check"]["status"] == "aligned"
    assert payload["viewer_pass"]["status"] == "clean"
    assert payload["claim_review"]["status"] == "no_claims"
    assert fake_client.files.upload_count == 1
    assert fake_client.models.calls == 4
    assert fake_client.files.delete_count == 1


def test_local_review_mode_forcibly_disables_gemini(video_with_audio: Path, monkeypatch) -> None:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    config.rules.video.allowed_aspect_ratios = ["16:9"]
    config.ai_review.enabled = True
    config.ai_review.claim_review.enabled = True
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "ai-enabled base"))
    real_run_sync = api_module.anyio.to_thread.run_sync
    thread_calls = []

    async def recording_run_sync(function, *args, **kwargs):
        thread_calls.append(function)
        return await real_run_sync(function, *args, **kwargs)

    monkeypatch.setattr(api_module.anyio.to_thread, "run_sync", recording_run_sync)
    monkeypatch.setattr(
        GeminiVideoReviewer,
        "_create_client",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Gemini must not run")),
    )
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={"file": ("video.mp4", media_file, "video/mp4")},
            data={"title": "Title", "description": "Description", "review_mode": "local"},
        )
    assert response.status_code == 200
    assert response.json()["review_mode"] == "local"
    assert response.json()["ai_review"]["status"] == "disabled"
    assert len(thread_calls) == 1


def test_full_review_provider_failure_is_partial_but_content_ready(
    video_with_audio: Path, monkeypatch
) -> None:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    config.rules.video.allowed_aspect_ratios = ["16:9"]
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "typed defaults"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={"file": ("video.mp4", media_file, "video/mp4")},
            data={"title": "Title", "description": "Description", "review_mode": "full"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "READY"
    assert payload["scan_completeness"] == "PARTIAL"
    assert payload["warning_count"] == 0
    assert payload["findings"] == []
    assert payload["execution_issues"][0]["reason_code"] == "ai_api_key_missing"


def test_real_caption_upload_reaches_parser(video_with_audio: Path) -> None:
    captions = b"WEBVTT\n\n00:00:00.000 --> 00:00:00.800\nHello\n"
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={
                "file": ("video.mp4", media_file, "video/mp4"),
                "captions": ("captions.vtt", captions, "text/vtt"),
            },
            data={"title": "Title", "description": "Description"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["caption_summary"]["source_format"] == "vtt"
    assert payload["caption_summary"]["cue_count"] == 1
    assert "captions.parse" in [check["check_id"] for check in payload["checks"]]
    assert "CAPTION_PARSE_ERROR" not in [finding["code"] for finding in payload["findings"]]


def test_malformed_caption_upload_returns_report_and_cleans_temp_files(
    video_with_audio: Path, monkeypatch
) -> None:
    created_paths: list[Path] = []

    def recording_temporary_directory(*args, **kwargs):
        temporary = RealTemporaryDirectory(*args, **kwargs)
        created_paths.append(Path(temporary.name))
        return temporary

    monkeypatch.setattr(api_module, "TemporaryDirectory", recording_temporary_directory)
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={
                "file": ("video.mp4", media_file, "video/mp4"),
                "captions": ("broken.srt", b"not caption syntax", "text/plain"),
            },
            data={"title": "Title", "description": "Description"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "CAPTION_PARSE_ERROR" in [finding["code"] for finding in payload["findings"]]
    assert "CAPTION_EMPTY" not in [finding["code"] for finding in payload["findings"]]
    assert created_paths and all(not path.exists() for path in created_paths)


def test_caption_upload_size_limit_matches_scanner_report_behavior(
    video_with_audio: Path,
) -> None:
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={
                "file": ("video.mp4", media_file, "video/mp4"),
                "captions": ("too-large.srt", b"x" * 5_000_001, "text/plain"),
            },
            data={"title": "Title", "description": "Description"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "BLOCKED"
    assert "CAPTION_PARSE_ERROR" in [finding["code"] for finding in payload["findings"]]
    parse_finding = next(
        finding
        for finding in payload["findings"]
        if finding["code"] == "CAPTION_PARSE_ERROR"
    )
    assert parse_finding["details"]["issues"][0]["message"] == (
        "Caption file exceeds the configured size limit."
    )


def test_api_accepts_png_thumbnail_and_cleans_temporary_file(
    video_with_audio: Path, monkeypatch
) -> None:
    created_paths: list[Path] = []

    def recording_temporary_directory(*args, **kwargs):
        temporary = RealTemporaryDirectory(*args, **kwargs)
        created_paths.append(Path(temporary.name))
        return temporary

    monkeypatch.setattr(api_module, "TemporaryDirectory", recording_temporary_directory)
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={
                "file": ("video.mp4", media_file, "video/mp4"),
                "thumbnail": ("thumbnail.png", _tiny_png(), "image/png"),
            },
            data={"title": "Title", "description": "Description"},
        )
    assert response.status_code == 200
    assert response.json()["promise_check"]["status"] == "disabled"
    assert response.json()["release_package"]["thumbnail_assurance"]["status"] == "NOT_EVALUATED"
    assert created_paths and all(not path.exists() for path in created_paths)


def test_api_reports_corrupt_thumbnail_as_invalid_package_content(video_with_audio: Path) -> None:
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={
                "file": ("video.mp4", media_file, "video/mp4"),
                "thumbnail": ("thumbnail.png", b"not an image", "image/png"),
            },
            data={"title": "Title", "description": "Description"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "BLOCKED"
    assert payload["release_package"]["thumbnail"]["state"] == "PRESENT_INVALID"
    assert payload["release_package"]["thumbnail_assurance"] is None
    assert "THUMBNAIL_INVALID" in [item["code"] for item in payload["findings"]]


def test_api_reports_thumbnail_above_configured_limit(
    video_with_audio: Path, monkeypatch
) -> None:
    from releaseseal.config import PreflightConfig

    config = PreflightConfig()
    config.ai_review.promise_check.maximum_thumbnail_file_size_bytes = 4
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "test config"))
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={
                "file": ("video.mp4", media_file, "video/mp4"),
                "thumbnail": ("thumbnail.png", _tiny_png(), "image/png"),
            },
            data={"title": "Title", "description": "Description"},
        )
    assert response.status_code == 200
    assert response.json()["release_package"]["thumbnail"]["state"] == "PRESENT_INVALID"
    assert response.json()["verdict"] == "BLOCKED"


def test_detector_timeout_uses_gateway_timeout_response(
    video_with_audio: Path, monkeypatch
) -> None:
    def timed_out(*args, **kwargs):
        del args, kwargs
        raise DetectorExecutionError(
            "detector_timeout",
            "The black-frame detector timed out.",
            details={"detector": "black", "timeout_seconds": 1},
        )

    monkeypatch.setattr(api_module.PreflightScanner, "scan", timed_out)
    with video_with_audio.open("rb") as media_file:
        response = client.post(
            "/api/v1/preflight/scan",
            files={"file": ("video.mp4", media_file, "video/mp4")},
            data={"title": "Title", "description": "Description"},
        )

    assert response.status_code == 504
    assert response.json() == {
        "error": {
            "code": "detector_timeout",
            "message": "The black-frame detector timed out.",
            "details": {"detector": "black", "timeout_seconds": 1},
        }
    }


def test_verify_repair_rescans_and_returns_typed_report(api_anomaly_video: Path, tmp_path: Path) -> None:
    operation = RepairOperation(operation_type="REMOVE_RANGE", start_seconds=2, end_seconds=5)
    contract = ReleaseContract(requirements=[MaxDuration(id="duration", type="MAX_DURATION", instruction="Keep under twenty seconds", maximum_seconds=20)])
    package = PublishingPackage(title="Repair verification", description="A valid package", release_contract=contract)
    original_report = PreflightScanner().scan(api_anomaly_video, package)
    repaired = tmp_path / "repaired.mp4"
    FFmpegRepairEngine().render(api_anomaly_video, repaired, [operation])
    with api_anomaly_video.open("rb") as original, repaired.open("rb") as rendered:
        response = client.post(
            "/api/v1/repairs/verify",
            files={"original_file": ("original.mp4", original, "video/mp4"), "repaired_file": ("repaired.mp4", rendered, "video/mp4")},
            data={"operations_json": json.dumps({"operations": [operation.model_dump(mode="json")]}), "original_report_json": original_report.model_dump_json(), "title": package.title, "description": package.description, "review_mode": "local"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["approved_repair_count"] == 1
    assert payload["integrity"]["passed"] is True
    assert payload["repaired_preflight_report"]["review_mode"] == "local"
    assert payload["repaired_preflight_report"]["release_contract"]["passed_count"] == 1
    assert payload["repaired_preflight_report"]["audio_evidence"]["confirmations"] == []
    assert payload["repaired_preflight_report"]["audio_evidence"]["artifact_sha256"] is None
    assert any(item["original_finding"]["code"] == "VIDEO_BLACK_SEGMENT" for item in payload["resolved"])
    assert payload["unexpected_changes"] == []
    assert payload["review_reel_available"] is True


def test_verify_repair_rescans_with_repaired_timeline_captions(api_anomaly_video: Path, tmp_path: Path) -> None:
    operation = RepairOperation(operation_type="REMOVE_RANGE", start_seconds=2, end_seconds=5)
    caption_text = "1\n00:00:01,000 --> 00:00:06,000\nAcross the cut\n\n2\n00:00:10,000 --> 00:00:12,000\nEnding\n"
    captions_path = tmp_path / "source.srt"
    captions_path.write_text(caption_text, encoding="utf-8")
    package = PublishingPackage(title="Repair verification", description="A valid package", captions_path=captions_path)
    original_report = PreflightScanner().scan(api_anomaly_video, package)
    repaired = tmp_path / "repaired-with-captions.mp4"
    FFmpegRepairEngine().render(api_anomaly_video, repaired, [operation])

    with api_anomaly_video.open("rb") as original, repaired.open("rb") as rendered:
        response = client.post(
            "/api/v1/repairs/verify",
            files={
                "original_file": ("original.mp4", original, "video/mp4"),
                "repaired_file": ("repaired.mp4", rendered, "video/mp4"),
                "captions": ("captions.srt", caption_text.encode(), "application/x-subrip"),
            },
            data={
                "operations_json": json.dumps({"operations": [operation.model_dump(mode="json")]}),
                "original_report_json": original_report.model_dump_json(),
                "title": package.title,
                "description": package.description,
                "review_mode": "local",
            },
        )

    assert response.status_code == 200
    repaired_report = response.json()["repaired_preflight_report"]
    assert repaired_report["caption_summary"]["cue_count"] == 2
    assert repaired_report["caption_summary"]["last_caption_seconds"] == pytest.approx(9)
    assert "CAPTION_CUE_OUT_OF_RANGE" not in [finding["code"] for finding in repaired_report["findings"]]
    assert captions_path.read_text(encoding="utf-8") == caption_text


def test_review_reel_api_returns_playable_mp4(api_anomaly_video: Path) -> None:
    manifest = {"entries": [{"reel_start_seconds": 0, "reel_end_seconds": 2, "source_start_seconds": 0, "source_end_seconds": 2, "reason": "Approved range removed", "category": "repair", "source_id": "repair-1"}], "total_duration_seconds": 2}
    with api_anomaly_video.open("rb") as rendered:
        response = client.post("/api/v1/repairs/review-reel", files={"repaired_file": ("repaired.mp4", rendered, "video/mp4")}, data={"manifest_json": json.dumps(manifest)})
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert "review-reel.mp4" in response.headers["content-disposition"]
    assert len(response.content) > 1000


def test_verify_repair_reuses_origin_and_upload_limits(api_anomaly_video: Path, monkeypatch) -> None:
    config = PreflightConfig()
    config.api.maximum_video_upload_size_bytes = 100
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "test"))
    operation = {"operation_type": "REMOVE_RANGE", "start_seconds": 2, "end_seconds": 5}
    original_report = PreflightScanner().scan(api_anomaly_video, PublishingPackage(title="Title", description="Description"))
    with api_anomaly_video.open("rb") as original, api_anomaly_video.open("rb") as repaired:
        response = client.post("/api/v1/repairs/verify", files={"original_file": ("original.mp4", original, "video/mp4"), "repaired_file": ("repaired.mp4", repaired, "video/mp4")}, data={"operations_json": json.dumps({"operations": [operation]}), "original_report_json": original_report.model_dump_json()}, headers={"Origin": "http://127.0.0.1:5173"})
    assert response.status_code == 413
    with api_anomaly_video.open("rb") as original, api_anomaly_video.open("rb") as repaired:
        blocked = client.post("/api/v1/repairs/verify", files={"original_file": ("original.mp4", original, "video/mp4"), "repaired_file": ("repaired.mp4", repaired, "video/mp4")}, data={"operations_json": json.dumps({"operations": [operation]}), "original_report_json": original_report.model_dump_json()}, headers={"Origin": "https://evil.example"})
    assert blocked.status_code == 403


def test_full_review_repaired_scan_uses_existing_fake_provider_session(video_with_audio: Path, tmp_path: Path, monkeypatch) -> None:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    config.rules.video.allowed_aspect_ratios = ["16:9"]
    monkeypatch.setattr(api_module, "_api_config", lambda: (config, "test"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    operation = RepairOperation(operation_type="REMOVE_RANGE", start_seconds=0.2, end_seconds=0.4)
    package = PublishingPackage(title="Title", description="Description")
    original_report = PreflightScanner(config=config).scan(video_with_audio, package)
    repaired = tmp_path / "repaired.mp4"
    FFmpegRepairEngine().render(video_with_audio, repaired, [operation])

    class FakeFiles:
        upload_count = 0
        delete_count = 0
        def upload(self, **kwargs):
            self.upload_count += 1
            return SimpleNamespace(name="files/repaired", uri="https://provider.invalid/repaired", mime_type="video/mp4", state=SimpleNamespace(name="ACTIVE"))
        def get(self, **kwargs):
            raise AssertionError("active file must not poll")
        def delete(self, **kwargs):
            self.delete_count += 1

    class FakeModels:
        calls = 0
        def generate_content(self, **kwargs):
            self.calls += 1
            title = kwargs["config"]["response_json_schema"]["title"]
            payload = {
                "PromiseReviewResult": {"inferred_promise": "Explain a test.", "first_substantive_address_seconds": 0, "first_substantive_address_evidence": "It starts.", "overall_delivery": "aligned", "overall_delivery_explanation": "Aligned.", "confidence": 0.9, "thumbnail_alignment": None, "thumbnail_alignment_explanation": None, "issues": []},
                "ViewerPassResult": {"overall_status": "clean", "summary": "Clean.", "issues": []},
                "ClaimExtractionResult": {"claims": []},
                "ReleaseBriefDraft": {"headline": "Ready", "summary": "No release issue was found.", "top_action_codes": [], "positive_note": "Checks completed."},
            }[title]
            return SimpleNamespace(text=json.dumps(payload), candidates=[])

    fake_client = SimpleNamespace(files=FakeFiles(), models=FakeModels(), close=lambda: None)
    monkeypatch.setattr(GeminiVideoReviewer, "_create_client", lambda *args, **kwargs: fake_client)
    with video_with_audio.open("rb") as original, repaired.open("rb") as rendered:
        response = client.post("/api/v1/repairs/verify", files={"original_file": ("original.mp4", original, "video/mp4"), "repaired_file": ("repaired.mp4", rendered, "video/mp4")}, data={"operations_json": json.dumps({"operations": [operation.model_dump(mode="json")]}), "original_report_json": original_report.model_dump_json(), "title": "Title", "description": "Description", "review_mode": "full"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["repaired_preflight_report"]["scan_completeness"] == "COMPLETE"
    assert payload["repaired_preflight_report"]["promise_check"]["status"] == "aligned"
    assert payload["repaired_preflight_report"]["viewer_pass"]["status"] == "clean"
    assert fake_client.files.upload_count == 1
    assert fake_client.models.calls == 4
    assert fake_client.files.delete_count == 1
