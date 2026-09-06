#!/usr/bin/env python3
"""Build reproducible judge-demo derivatives from one user-owned creator video."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from creator_preflight.media import MediaInspector, MediaInspectionError, require_media_tool  # noqa: E402
from creator_preflight.promise_fixture import _canvas, _draw_text, _fill_rect, _write_ppm  # noqa: E402

SCHEMA_VERSION = "1.0"
GENERATOR_VERSION = "1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create deterministic demo derivatives from user-owned footage.")
    parser.add_argument("source", nargs="?", type=Path, default=ROOT / ".demo" / "owner" / "source.mp4")
    parser.add_argument("--output", type=Path, default=ROOT / "frontend" / "public" / "demo" / "owner")
    parser.add_argument("--title", default="A creator-owned release review")
    parser.add_argument("--description", default="A user-owned creator video prepared for the release-assurance demo.")
    parser.add_argument("--captions", type=Path)
    parser.add_argument("--thumbnail", type=Path)
    args = parser.parse_args()
    try:
        outputs = build_owner_demo(args.source, args.output, args.title, args.description, args.captions, args.thumbnail)
    except (RuntimeError, MediaInspectionError) as exc:
        print(f"build-owner-demo: {exc}", file=sys.stderr)
        return 2
    print(f"Owner demo built: {outputs['manifest']}")
    print("Validate locally: open the web app, load each demo, and run the real workflows.")
    return 0


def build_owner_demo(source: Path, output: Path, title: str, description: str, captions: Path | None, thumbnail: Path | None) -> dict[str, Path]:
    if not source.is_file():
        raise RuntimeError(f"User-owned source not found: {source}")
    media = MediaInspector().inspect(source)
    if not media.has_video or not media.has_audio or media.duration_seconds is None or media.width is None or media.height is None:
        raise RuntimeError("Source must contain readable video and audio.")
    if not 90 <= media.duration_seconds <= 240:
        raise RuntimeError("Source duration must be between 90 and 240 seconds.")
    if captions is not None and not captions.is_file():
        raise RuntimeError("Supplied captions file does not exist.")
    if captions is not None and captions.suffix.lower() not in {".srt", ".vtt"}:
        raise RuntimeError("Supplied captions must be SRT or WebVTT.")
    if thumbnail is not None and not thumbnail.is_file():
        raise RuntimeError("Supplied thumbnail file does not exist.")
    if thumbnail is not None and thumbnail.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise RuntimeError("Supplied thumbnail must be PNG or JPEG.")

    ffmpeg = require_media_tool("ffmpeg")
    output.mkdir(parents=True, exist_ok=True)
    # Keep the accepted 90–240 second source timeline intact so optional owner
    # captions remain aligned with every generated derivative.
    duration = media.duration_seconds
    # Normalize judge assets to a broadly playable 720p canvas while preserving
    # source aspect ratio. This also keeps a low-resolution owner source from
    # tripping the default package minimum in a demo about seeded defects.
    width = 1280
    height = 720
    previous = output / "revision-previous.mp4"
    revised = output / "revision-revised.mp4"
    final_export = output / "final-export-demo.mp4"
    notes = output / "revision-notes.txt"
    title_path = output / "final-export-title.txt"
    description_path = output / "final-export-description.txt"
    approved_card = output / ".approved-card.ppm"

    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source), "-t", f"{duration:.3f}",
        "-map", "0:v:0", "-map", "0:a:0",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-r", "24",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(previous),
    ])

    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(previous),
        "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,24,27)'",
        "-af", "volume=0:enable='between(t,54,59)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(final_export),
    ])

    _write_ppm(approved_card, _approved_card(width, height))
    graph = _revision_graph(duration)
    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(previous),
        "-loop", "1", "-framerate", "24", "-t", "5", "-i", str(approved_card),
        "-f", "lavfi", "-t", "4", "-i", f"color=c=0x26485f:s={width}x{height}:r=24",
        "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=4",
        "-filter_complex", graph, "-map", "[video]", "-map", "[audio]", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(revised),
    ])
    approved_card.unlink(missing_ok=True)

    notes.write_text(
        "00:12-00:16 Remove the obsolete aside\n"
        "00:30-00:35 Replace the old shot with the APPROVED 2025 card\n"
        "00:45 Insert the approved transition card\n",
        encoding="utf-8",
    )
    title_path.write_text(title.strip() + "\n", encoding="utf-8")
    description_path.write_text(description.strip() + "\n", encoding="utf-8")

    caption_name = _copy_optional(captions, output, "final-export-captions")
    thumbnail_name = _copy_optional(thumbnail, output, "final-export-thumbnail")
    generated = [final_export, previous, revised, notes, title_path, description_path]
    if caption_name: generated.append(output / caption_name)
    if thumbnail_name: generated.append(output / thumbnail_name)
    manifest = output / "demo-manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_ownership": "User-supplied demo source",
        "source_filename": source.name,
        "source_sha256": _sha256(source),
        "generated_sha256": {path.name: _sha256(path) for path in generated},
        "seed_operations": [
            {"workflow": "final_export", "kind": "black_gap", "start_seconds": 24, "end_seconds": 27},
            {"workflow": "final_export", "kind": "audio_dropout", "start_seconds": 54, "end_seconds": 59},
            {"workflow": "revision", "kind": "requested_removal", "previous_start_seconds": 12, "previous_end_seconds": 16},
            {"workflow": "revision", "kind": "requested_visual_replacement", "previous_start_seconds": 30, "previous_end_seconds": 35},
            {"workflow": "revision", "kind": "requested_insertion", "previous_anchor_seconds": 45, "duration_seconds": 4},
            {"workflow": "revision", "kind": "unmentioned_visual_change", "previous_start_seconds": 65, "previous_end_seconds": 69},
        ],
        "assets": {
            "final_export": {"video": final_export.name, "title": title_path.name, "description": description_path.name, "captions": caption_name, "thumbnail": thumbnail_name},
            "revision": {"previous": previous.name, "revised": revised.name, "notes": notes.name},
        },
    }, indent=2) + "\n", encoding="utf-8")
    return {"manifest": manifest, "final_export": final_export, "previous": previous, "revised": revised, "notes": notes}


def _approved_card(width: int, height: int) -> list[bytearray]:
    pixels = _canvas((25, 53, 72), width=width, height=height)
    _fill_rect(pixels, 0, 0, width, max(20, height // 10), (12, 24, 34))
    scale = max(3, min(width // 115, height // 36))
    _draw_text(pixels, "APPROVED", max(20, width // 8), max(30, height // 3), scale=scale, color=(244, 247, 249))
    _draw_text(pixels, "2025", max(20, width // 8), max(60, height // 2), scale=scale, color=(239, 196, 92))
    return pixels


def _revision_graph(duration: float) -> str:
    ranges = [
        (0, 12, ""),
        (16, 30, ""),
        (35, 45, ""),
        (45, 65, ""),
        (65, 69, ",drawbox=x=0:y=ih*0.7:w=iw:h=ih*0.3:color=white:t=fill"),
        (69, duration, ""),
    ]
    video = [f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS{effect}[v{index}]" for index, (start, end, effect) in enumerate(ranges)]
    audio = [f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]" for index, (start, end, _) in enumerate(ranges)]
    extras = ["[1:v]trim=duration=5,setpts=PTS-STARTPTS[vcard]", "[0:a]atrim=start=30:end=35,asetpts=PTS-STARTPTS[acard]", "[2:v]trim=duration=4,setpts=PTS-STARTPTS[vinsert]", "[3:a]atrim=duration=4,asetpts=PTS-STARTPTS[ainsert]"]
    order = "[v0][a0][v1][a1][vcard][acard][v2][a2][vinsert][ainsert][v3][a3][v4][a4][v5][a5]"
    return ";".join([*video, *audio, *extras, f"{order}concat=n=8:v=1:a=1[video][audio]"])


def _copy_optional(source: Path | None, output: Path, stem: str) -> str | None:
    if source is None: return None
    destination = output / f"{stem}{source.suffix.lower()}"
    shutil.copy2(source, destination)
    return destination.name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def _run(command: list[str]) -> None:
    try: completed = subprocess.run(command, capture_output=True, text=True, timeout=360, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc: raise RuntimeError("FFmpeg could not build the owner demo package.") from exc
    if completed.returncode != 0: raise RuntimeError("FFmpeg could not build the owner demo package from this source.")


if __name__ == "__main__":
    raise SystemExit(main())
