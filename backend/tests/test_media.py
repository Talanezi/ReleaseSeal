from pathlib import Path

import pytest

from releaseseal.media import (
    MediaInspectionError,
    MediaInspector,
    check_media_tools,
    require_media_tool,
)


def test_inspects_generated_video_and_audio(video_with_audio: Path) -> None:
    result = MediaInspector().inspect(video_with_audio)

    assert result.duration_seconds is not None
    assert 0.9 <= result.duration_seconds <= 1.2
    assert result.file_size_bytes == video_with_audio.stat().st_size
    assert result.format_name is not None
    assert "mp4" in result.format_name
    assert result.has_video is True
    assert result.video_stream_count == 1
    assert result.video_codec == "mpeg4"
    assert result.width == 160
    assert result.height == 90
    assert result.display_aspect_ratio == "16:9"
    assert result.frame_rate == pytest.approx(24.0)
    assert result.pixel_format == "yuv420p"
    assert result.has_audio is True
    assert result.audio_stream_count == 1
    assert result.audio_codec == "aac"
    assert result.channel_count == 1
    assert result.sample_rate == 48000


def test_video_without_audio_is_normalized(video_without_audio: Path) -> None:
    result = MediaInspector().inspect(video_without_audio)

    assert result.has_video is True
    assert result.has_audio is False
    assert result.audio_stream_count == 0
    assert result.audio_codec is None
    assert result.channel_count is None
    assert result.sample_rate is None


def test_nonexistent_path_has_structured_error(tmp_path: Path) -> None:
    with pytest.raises(MediaInspectionError) as captured:
        MediaInspector().inspect(tmp_path / "missing.mp4")

    assert captured.value.code == "file_not_found"
    assert captured.value.message == "The supplied media file does not exist."


def test_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(MediaInspectionError) as captured:
        MediaInspector().inspect(tmp_path)

    assert captured.value.code == "not_a_file"


def test_zero_byte_file_has_structured_error(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.mp4"
    empty_file.touch()

    with pytest.raises(MediaInspectionError) as captured:
        MediaInspector().inspect(empty_file)

    assert captured.value.code == "empty_file"


def test_nonempty_invalid_media_has_structured_error(tmp_path: Path) -> None:
    invalid_file = tmp_path / "not-media.mp4"
    invalid_file.write_bytes(b"this is not media")

    with pytest.raises(MediaInspectionError) as captured:
        MediaInspector().inspect(invalid_file)

    assert captured.value.code == "invalid_media"
    assert captured.value.details is not None
    assert captured.value.details["ffprobe_exit_code"] != 0


def test_spaces_and_unicode_in_path(video_with_audio: Path, tmp_path: Path) -> None:
    unicode_path = tmp_path / "creator clip مرحبا 🎬.mp4"
    unicode_path.write_bytes(video_with_audio.read_bytes())

    result = MediaInspector().inspect(unicode_path)

    assert result.width == 160
    assert result.height == 90
    assert result.has_audio is True


def test_dependency_status_reports_ffmpeg_and_ffprobe() -> None:
    status = check_media_tools()

    assert status.ffprobe_available is True
    assert status.ffprobe_path is not None
    assert status.ffmpeg_available is True
    assert status.ffmpeg_path is not None


def test_missing_media_tool_has_structured_error() -> None:
    with pytest.raises(MediaInspectionError) as captured:
        require_media_tool("releaseseal-tool-that-does-not-exist")

    assert captured.value.code == "media_tool_unavailable"
    assert captured.value.details == {
        "tool": "releaseseal-tool-that-does-not-exist"
    }
