"""Focused release-freeze attacks not already explicit in subsystem suites."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from pydantic import ValidationError

from releaseseal.api import UploadLimitError, _copy_upload, _media_temp_path, app
from releaseseal.captions import CaptionCue
from releaseseal.config import PreflightConfig
from releaseseal.engine import PreflightScanner
from releaseseal.media import MediaInspector
from releaseseal.models import CaptionSummary, MediaInspection, PublishingPackage
from releaseseal.release_contract import (
    ContractStatus,
    DescriptionUrl,
    ReleaseContract,
    RequiredBeforeTime,
    RequiredTalkingPoint,
    evaluate_release_contract,
)
from releaseseal.repairs import RepairOperation


client = TestClient(app)


def test_unusual_valid_frame_rate_and_odd_dimensions_remain_truthful(tmp_path: Path) -> None:
    media_path = tmp_path / "odd-rate-and-size.mkv"
    completed = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=322x182:rate=17:duration=1.2",
        "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=1.2",
        "-c:v", "ffv1", "-c:a", "pcm_s16le", "-shortest", str(media_path),
    ], capture_output=True, check=False, timeout=30)
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")

    inspected = MediaInspector().inspect(media_path)
    assert (inspected.width, inspected.height) == (322, 182)
    assert inspected.frame_rate == pytest.approx(17)
    config = PreflightConfig()
    config.rules.video.minimum_width = 300
    config.rules.video.minimum_height = 180
    report = PreflightScanner(config=config).scan(
        media_path,
        PublishingPackage(title="Odd but valid media", description="A valid unusual export."),
    )
    assert report.scan_completeness.value == "COMPLETE"
    assert report.media.width == 322 and report.media.frame_rate == pytest.approx(17)


def test_contract_deadline_boundary_is_inclusive_and_just_after_fails() -> None:
    contract = ReleaseContract(requirements=[
        RequiredBeforeTime(id="boundary", type="REQUIRED_BEFORE_TIME", instruction="Mention by thirty seconds", value="Acme", before_seconds=30),
    ])
    inspected = MediaInspection(duration_seconds=60, format_name="mp4", file_size_bytes=1, has_video=True, video_stream_count=1, video_codec="h264", width=1920, height=1080, has_audio=True, audio_stream_count=1, audio_codec="aac")
    package = PublishingPackage(title="Title", description="Description")
    def result(at: float):
        cue = CaptionCue(at, at + .5, "Acme")
        return evaluate_release_contract(contract, package=package, media=inspected, caption_cues=[cue], caption_summary=CaptionSummary(source_format="srt", cue_count=1, first_caption_seconds=at, last_caption_seconds=at + .5, covered_duration_seconds=.5, timeline_coverage_percent=.01), caption_findings=[])
    assert result(30).results[0].status is ContractStatus.PASS
    assert result(30.001).results[0].status is ContractStatus.FAIL


def test_empty_contract_and_semantic_requirement_without_provider_do_not_invent_success(video_with_audio: Path) -> None:
    config = PreflightConfig()
    config.rules.video.minimum_width = 160
    config.rules.video.minimum_height = 90
    empty = PreflightScanner(config=config).scan(video_with_audio, PublishingPackage(title="Title", description="Description", release_contract=ReleaseContract()))
    assert empty.release_contract.results == []
    assert empty.release_contract.passed_count == empty.release_contract.failed_count == 0

    semantic = ReleaseContract(requirements=[RequiredTalkingPoint(id="point", type="REQUIRED_TALKING_POINT", instruction="Discuss privacy", value="privacy")])
    report = PreflightScanner(config=config).scan(video_with_audio, PublishingPackage(title="Title", description="Description", release_contract=semantic))
    assert report.release_contract.results[0].status is ContractStatus.NOT_EVALUATED
    assert report.release_contract.passed_count == 0


def test_malformed_multipart_is_controlled_and_filename_traversal_is_not_used(tmp_path: Path) -> None:
    response = client.post(
        "/api/v1/preflight/scan",
        content=b"not-a-valid-part",
        headers={"Content-Type": "multipart/form-data; boundary=hostile"},
    )
    assert 400 <= response.status_code < 500

    resolved = _media_temp_path(str(tmp_path), "../../escape.mp4", stem="upload")
    assert resolved.parent == tmp_path
    assert resolved.name == "upload.mp4"


def test_streaming_limit_does_not_depend_on_content_length(tmp_path: Path) -> None:
    upload = UploadFile(filename="video.mp4", file=open(tmp_path / "source.bin", "w+b"))
    upload.file.write(b"four")
    upload.file.seek(0)
    with pytest.raises(UploadLimitError):
        asyncio.run(_copy_upload(upload, tmp_path / "upload.mp4", maximum_bytes=3))
    asyncio.run(upload.close())


def test_negative_remove_range_is_rejected_before_ffmpeg() -> None:
    with pytest.raises(ValidationError):
        RepairOperation(
            operation_type="REMOVE_RANGE",
            start_seconds=-0.01,
            end_seconds=1,
        )


def test_description_url_normalization_is_conservative() -> None:
    contract = ReleaseContract(requirements=[
        DescriptionUrl(
            id="url",
            type="DESCRIPTION_URL",
            instruction="Include the delivery URL",
            value="https://Example.com/path/",
        ),
    ])
    inspected = MediaInspection(
        duration_seconds=1,
        format_name="mp4",
        file_size_bytes=1,
        has_video=True,
        video_stream_count=1,
        video_codec="h264",
        width=1920,
        height=1080,
        has_audio=False,
        audio_stream_count=0,
    )
    evaluation = evaluate_release_contract(
        contract,
        package=PublishingPackage(
            title="Title",
            description="Use https://example.com/path#tracking for details.",
        ),
        media=inspected,
        caption_cues=[],
        caption_summary=None,
        caption_findings=[],
    )
    assert evaluation.results[0].status is ContractStatus.PASS
