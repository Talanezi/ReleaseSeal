"""Deterministic local media fixtures generated with FFmpeg."""

import shutil
import subprocess
from pathlib import Path

import pytest

from releaseseal.demo_fixture import generate_demo_video


def _ffmpeg_executable() -> str:
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.fail(
            "FFmpeg is required to generate test fixtures but is not available on PATH."
        )
    return executable


def _run_ffmpeg(command: list[str]) -> None:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        pytest.fail(
            "FFmpeg failed to generate deterministic test media: "
            f"exit code {completed.returncode}; {completed.stderr.strip()}"
        )


def _generate_video(path: Path, *, with_audio: bool) -> Path:
    command = [
        _ffmpeg_executable(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=160x90:rate=24:duration=1",
    ]
    if with_audio:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=1000:sample_rate=48000:duration=1",
            ]
        )
    command.extend(["-c:v", "mpeg4", "-pix_fmt", "yuv420p"])
    if with_audio:
        command.extend(["-c:a", "aac", "-shortest"])
    else:
        command.append("-an")
    command.append(str(path))

    _run_ffmpeg(command)
    return path


def _generate_anomaly_video(path: Path, *, size: str = "160x90") -> Path:
    try:
        return generate_demo_video(
            path,
            size=size,
            ffmpeg_binary=_ffmpeg_executable(),
            timeout_seconds=30,
        )
    except RuntimeError as exc:
        pytest.fail(str(exc))


def _generate_silence_at_end_video(path: Path) -> Path:
    filter_graph = ";".join(
        [
            "testsrc2=size=160x90:rate=24:duration=4[video]",
            "sine=frequency=440:sample_rate=48000:duration=2[a0]",
            "anullsrc=r=48000:cl=mono,atrim=duration=2[a1]",
            "[a0][a1]concat=n=2:v=0:a=1[audio]",
        ]
    )
    command = [
        _ffmpeg_executable(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-filter_complex",
        filter_graph,
        "-map",
        "[video]",
        "-map",
        "[audio]",
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(path),
    ]
    _run_ffmpeg(command)
    return path


def _generate_low_motion_video(path: Path) -> Path:
    command = [
        _ffmpeg_executable(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x303030:size=160x90:rate=24:duration=5",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=24x24:rate=24:duration=5",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=220:sample_rate=48000:duration=5",
        "-filter_complex",
        "[0:v][1:v]overlay=x='68+4*sin(t)':y=33:shortest=1[video]",
        "-map",
        "[video]",
        "-map",
        "2:a",
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    _run_ffmpeg(command)
    return path


def _generate_ambient_pause_video(path: Path) -> Path:
    command = [
        _ffmpeg_executable(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=160x90:rate=24:duration=8",
        "-f",
        "lavfi",
        "-i",
        "anoisesrc=color=pink:amplitude=0.01:sample_rate=48000:duration=8",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=180:sample_rate=48000:duration=8",
        "-filter_complex",
        (
            "[2:a]volume='if(lt(mod(t,3),1.2),0.15,0)':eval=frame[voice];"
            "[1:a][voice]amix=inputs=2:normalize=0[audio]"
        ),
        "-map",
        "0:v",
        "-map",
        "[audio]",
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    _run_ffmpeg(command)
    return path


def _generate_short_black_transition_video(path: Path) -> Path:
    filter_graph = ";".join(
        [
            "testsrc2=size=160x90:rate=24:duration=2[v0]",
            "color=c=black:size=160x90:rate=24:duration=0.5[v1]",
            "testsrc2=size=160x90:rate=24:duration=2.5[v2]",
            "[v0][v1][v2]concat=n=3:v=1:a=0,format=yuv420p[video]",
            "sine=frequency=440:sample_rate=48000:duration=5[audio]",
        ]
    )
    command = [
        _ffmpeg_executable(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-filter_complex",
        filter_graph,
        "-map",
        "[video]",
        "-map",
        "[audio]",
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(path),
    ]
    _run_ffmpeg(command)
    return path


def _generate_black_flash_video(path: Path) -> Path:
    filter_graph = ";".join(
        [
            "testsrc2=size=160x90:rate=25:duration=2[v0]",
            "color=c=black:size=160x90:rate=25:duration=0.12[v1]",
            "testsrc2=size=160x90:rate=25:duration=2[v2]",
            "[v0][v1][v2]concat=n=3:v=1:a=0,format=yuv420p[video]",
            "sine=frequency=440:sample_rate=48000:duration=4.12[audio]",
        ]
    )
    command = [
        _ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-y",
        "-filter_complex", filter_graph, "-map", "[video]", "-map", "[audio]",
        "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ]
    _run_ffmpeg(command)
    return path


def _generate_near_full_scale_transient_video(path: Path) -> Path:
    filter_graph = ";".join(
        [
            "testsrc2=size=160x90:rate=24:duration=5[video]",
            "sine=frequency=440:sample_rate=48000:duration=2[a0]",
            "aevalsrc=0.99*sin(2*PI*880*t):s=48000:d=0.05[a1]",
            "sine=frequency=550:sample_rate=48000:duration=2.95[a2]",
            "[a0][a1][a2]concat=n=3:v=0:a=1[audio]",
        ]
    )
    command = [
        _ffmpeg_executable(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-filter_complex",
        filter_graph,
        "-map",
        "[video]",
        "-map",
        "[audio]",
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(path),
    ]
    _run_ffmpeg(command)
    return path


@pytest.fixture(scope="session")
def video_with_audio(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _generate_video(
        tmp_path_factory.mktemp("media") / "video with audio.mp4", with_audio=True
    )


@pytest.fixture(scope="session")
def video_without_audio(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _generate_video(
        tmp_path_factory.mktemp("media") / "video-without-audio.mp4",
        with_audio=False,
    )


@pytest.fixture(scope="session")
def anomaly_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """12s: black 2-5s, silence 3-6s, blue static 7-10s, peak 10-11s."""

    return _generate_anomaly_video(
        tmp_path_factory.mktemp("media") / "known-anomalies.mp4"
    )


@pytest.fixture(scope="session")
def api_anomaly_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Default-rule-sized variant for the real unified API contract."""

    return _generate_anomaly_video(
        tmp_path_factory.mktemp("media") / "api-known-anomalies.mp4",
        size="1280x720",
    )


@pytest.fixture(scope="session")
def silence_at_end_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """4s video with silence from 2s through the end."""

    return _generate_silence_at_end_video(
        tmp_path_factory.mktemp("media") / "silence-at-end.mp4"
    )


@pytest.fixture(scope="session")
def low_motion_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _generate_low_motion_video(
        tmp_path_factory.mktemp("media") / "legitimate-low-motion.mp4"
    )


@pytest.fixture(scope="session")
def ambient_pause_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _generate_ambient_pause_video(
        tmp_path_factory.mktemp("media") / "ambient-speech-pauses.mp4"
    )


@pytest.fixture(scope="session")
def short_black_transition_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _generate_short_black_transition_video(
        tmp_path_factory.mktemp("media") / "short-black-transition.mp4"
    )


@pytest.fixture(scope="session")
def black_flash_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _generate_black_flash_video(
        tmp_path_factory.mktemp("media") / "brief-black-flash.mp4"
    )


@pytest.fixture(scope="session")
def near_full_scale_transient_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _generate_near_full_scale_transient_video(
        tmp_path_factory.mktemp("media") / "near-full-scale-transient.mp4"
    )


@pytest.fixture(scope="session")
def audio_only_media(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("media") / "audio-only.m4a"
    command = [
        _ffmpeg_executable(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=1",
        "-c:a",
        "aac",
        str(path),
    ]
    _run_ffmpeg(command)
    return path
