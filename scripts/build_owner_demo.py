#!/usr/bin/env python3
"""Build reproducible judge-demo derivatives from one authorized source video."""

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
SCHEMA_VERSION = "1.0"
GENERATOR_VERSION = "2"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create deterministic demo derivatives from authorized footage.")
    parser.add_argument("source", nargs="?", type=Path, default=ROOT / ".demo" / "owner" / "source.mp4")
    parser.add_argument("--output", type=Path, default=ROOT / "frontend" / "public" / "demo" / "owner")
    parser.add_argument("--title", default="A creative release review")
    parser.add_argument("--description", default="A creator video prepared for the release-assurance demo.")
    parser.add_argument("--captions", type=Path)
    parser.add_argument("--thumbnail", type=Path)
    parser.add_argument("--source-type", choices=("user_owned", "public_domain"), default="user_owned")
    parser.add_argument("--source-credit")
    parser.add_argument("--source-title")
    parser.add_argument("--source-url")
    args = parser.parse_args()
    try:
        outputs = build_owner_demo(
            args.source,
            args.output,
            args.title,
            args.description,
            args.captions,
            args.thumbnail,
            source_type=args.source_type,
            source_credit=args.source_credit,
            source_title=args.source_title,
            source_url=args.source_url,
        )
    except (RuntimeError, MediaInspectionError) as exc:
        print(f"build-owner-demo: {exc}", file=sys.stderr)
        return 2
    print(f"Owner demo built: {outputs['manifest']}")
    print("Validate locally: open the web app, load each demo, and run the real workflows.")
    return 0


def build_owner_demo(
    source: Path,
    output: Path,
    title: str,
    description: str,
    captions: Path | None,
    thumbnail: Path | None,
    *,
    source_type: str = "user_owned",
    source_credit: str | None = None,
    source_title: str | None = None,
    source_url: str | None = None,
) -> dict[str, Path]:
    if not source.is_file():
        raise RuntimeError(f"Source not found: {source}")
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
    provenance = _source_provenance(source_type, source_credit, source_title, source_url)

    ffmpeg = require_media_tool("ffmpeg")
    output.mkdir(parents=True, exist_ok=True)
    # Keep the accepted 90–240 second source timeline intact so optional
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
    # The Revised cut is the normalized clean master. The Previous cut keeps
    # that authentic footage throughout and adds only plausible seeded defects.
    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source), "-t", f"{duration:.3f}",
        "-map", "0:v:0", "-map", "0:a:0",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-r", "24",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(revised),
    ])

    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(revised),
        "-vf", (
            "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,24,27)',"
            "eq=brightness=-0.20:enable='between(t,70,74)'"
        ),
        "-af", "volume=0:enable='between(t,54,59)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(previous),
    ])
    # Final Export uses the same realistic black and audio-dropout defects. It
    # deliberately omits the unmentioned exposure variance used by Revision.
    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(revised),
        "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,24,27)'",
        "-af", "volume=0:enable='between(t,54,59)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(final_export),
    ])

    notes.write_text(
        "00:24-00:27 Restore the missing picture\n"
        "00:54-00:59 Restore the missing audio\n",
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
    thumbnail_provenance = (
        {
            "asset_role": "supplied_thumbnail",
            "source_type": provenance["source_type"],
            "source_credit": provenance["source_credit"],
            "source_title": provenance["source_title"],
            "source_url": provenance["source_url"],
            "modified_for_demo": False,
        }
        if thumbnail_name
        else None
    )
    manifest.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **provenance,
        "source_filename": source.name,
        "source_sha256": _sha256(source),
        "thumbnail_provenance": thumbnail_provenance,
        "generated_sha256": {path.name: _sha256(path) for path in generated},
        "seed_operations": [
            {"workflow": "final_export", "kind": "black_gap", "start_seconds": 24, "end_seconds": 27},
            {"workflow": "final_export", "kind": "audio_dropout", "start_seconds": 54, "end_seconds": 59},
            {"workflow": "revision", "kind": "requested_missing_picture", "previous_start_seconds": 24, "previous_end_seconds": 27},
            {"workflow": "revision", "kind": "requested_missing_audio", "previous_start_seconds": 54, "previous_end_seconds": 59},
            {"workflow": "revision", "kind": "unmentioned_exposure_change", "previous_start_seconds": 70, "previous_end_seconds": 74},
        ],
        "assets": {
            "final_export": {"video": final_export.name, "title": title_path.name, "description": description_path.name, "captions": caption_name, "thumbnail": thumbnail_name},
            "revision": {"previous": previous.name, "revised": revised.name, "notes": notes.name},
        },
    }, indent=2) + "\n", encoding="utf-8")
    return {"manifest": manifest, "final_export": final_export, "previous": previous, "revised": revised, "notes": notes}


def _source_provenance(
    source_type: str,
    source_credit: str | None,
    source_title: str | None,
    source_url: str | None,
) -> dict[str, str | bool | None]:
    if source_type not in {"user_owned", "public_domain"}:
        raise RuntimeError("Source type must be user_owned or public_domain.")
    credit = source_credit.strip() if source_credit else None
    title = source_title.strip() if source_title else None
    url = source_url.strip() if source_url else None
    if source_type == "public_domain" and (not credit or not title):
        raise RuntimeError("Public-domain sources require --source-credit and --source-title.")
    if url is not None and not url.startswith(("https://", "http://")):
        raise RuntimeError("Source URL must be an HTTP or HTTPS URL.")
    return {
        "source_type": source_type,
        "source_credit": credit,
        "source_title": title,
        "source_url": url,
        "modified_for_demo": True,
    }


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
