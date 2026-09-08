"""Command-line adapter for the shared ReleaseSeal scanner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from releaseseal.config import ConfigurationError, PreflightConfig, load_config
from releaseseal.detectors import DetectorExecutionError
from releaseseal.engine import PreflightScanner
from releaseseal.media import MediaInspectionError
from releaseseal.models import (
    FindingStatus,
    PreflightReport,
    PublishingPackage,
    ScanCompleteness,
)
from releaseseal.release_contract import ReleaseContract
from releaseseal.release_receipt import ReceiptVerificationStatus, ReceiptVerifier
from releaseseal.thumbnails import ThumbnailValidationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="releaseseal")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan", help="scan one local creator video")
    scan_parser.add_argument("video_path", type=Path)
    scan_parser.add_argument("--title", default="")
    description_group = scan_parser.add_mutually_exclusive_group()
    description_group.add_argument("--description", default=None)
    description_group.add_argument("--description-file", type=Path)
    scan_parser.add_argument("--captions", type=Path)
    scan_parser.add_argument("--thumbnail", type=Path)
    scan_parser.add_argument("--config", type=Path)
    scan_parser.add_argument("--json", action="store_true", dest="json_output")
    verify_parser = subparsers.add_parser("verify-receipt", help="verify an artifact-bound release receipt")
    verify_parser.add_argument("receipt_path", type=Path)
    verify_parser.add_argument("--video", type=Path, required=True, help="final video, or Previous video for a Revision receipt")
    verify_parser.add_argument("--revised-video", type=Path)
    verify_parser.add_argument("--thumbnail", type=Path)
    verify_parser.add_argument("--captions", type=Path)
    verify_parser.add_argument("--title")
    verify_description = verify_parser.add_mutually_exclusive_group()
    verify_description.add_argument("--description")
    verify_description.add_argument("--description-file", type=Path)
    verify_parser.add_argument("--contract", type=Path, help="Release Contract JSON to compare")
    verify_parser.add_argument("--revision-notes", type=Path)
    verify_parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "verify-receipt":
        return _verify_receipt(args)

    try:
        description = _load_description(args.description, args.description_file)
        if args.captions is not None and not args.captions.is_file():
            raise CliInputError(f"Captions path is not a file: {args.captions}")
        if args.thumbnail is not None and not args.thumbnail.is_file():
            raise CliInputError(f"Thumbnail path is not a file: {args.thumbnail}")
        config = load_config(args.config) if args.config else PreflightConfig()
        report = PreflightScanner(
            config=config,
            configuration_source=str(args.config) if args.config else "typed defaults",
        ).scan(
            args.video_path,
            PublishingPackage(
                title=args.title,
                description=description,
                captions_path=args.captions,
                thumbnail_path=args.thumbnail,
            ),
        )
    except (
        CliInputError,
        ConfigurationError,
        DetectorExecutionError,
        MediaInspectionError,
        ThumbnailValidationError,
        OSError,
    ) as exc:
        message = getattr(exc, "message", str(exc))
        print(f"releaseseal: {message}", file=sys.stderr)
        return 2

    if args.json_output:
        print(report.model_dump_json())
    else:
        print(format_human_report(report))
    if report.scan_completeness is not ScanCompleteness.COMPLETE:
        return 2
    return 0 if report.verdict is FindingStatus.READY else 1


def _verify_receipt(args) -> int:
    try:
        required_paths = [args.receipt_path, args.video]
        optional_paths = [args.revised_video, args.thumbnail, args.captions, args.description_file, args.contract, args.revision_notes]
        for path in required_paths:
            if not path.is_file():
                raise CliInputError(f"Path is not a file: {path}")
        for path in optional_paths:
            if path is not None and not path.is_file():
                raise CliInputError(f"Path is not a file: {path}")
        contract = ReleaseContract.model_validate_json(args.contract.read_text(encoding="utf-8")) if args.contract else None
        description = _load_description(args.description, args.description_file) if args.description is not None or args.description_file else None
        notes = args.revision_notes.read_text(encoding="utf-8") if args.revision_notes else None
        result = ReceiptVerifier().verify(
            args.receipt_path.read_bytes(),
            video_path=args.video,
            revised_path=args.revised_video,
            thumbnail_path=args.thumbnail,
            captions_path=args.captions,
            title=args.title,
            description=description,
            contract=contract,
            revision_notes=notes,
        )
    except (CliInputError, OSError, UnicodeError, ValueError) as exc:
        print(f"releaseseal: {getattr(exc, 'message', str(exc))}", file=sys.stderr)
        return 2
    if args.json_output:
        print(result.model_dump_json())
    else:
        heading = {
            ReceiptVerificationStatus.VALID: "RECEIPT VALID",
            ReceiptVerificationStatus.MISMATCH: "RECEIPT MISMATCH",
            ReceiptVerificationStatus.INVALID_RECEIPT: "INVALID RECEIPT",
            ReceiptVerificationStatus.INCOMPLETE_VERIFICATION: "RECEIPT VERIFICATION INCOMPLETE",
        }[result.status]
        print(heading)
        for check in result.checks:
            print(check)
        for mismatch in result.mismatches:
            print(mismatch)
        if result.recorded_verdict:
            print(f"Recorded verdict: {result.recorded_verdict}")
        if result.recorded_completeness:
            print(f"Recorded completeness: {result.recorded_completeness}")
    if result.status is ReceiptVerificationStatus.VALID:
        return 0
    if result.status in {ReceiptVerificationStatus.MISMATCH, ReceiptVerificationStatus.INCOMPLETE_VERIFICATION}:
        return 1
    return 2


class CliInputError(Exception):
    pass


def _load_description(direct: str | None, path: Path | None) -> str:
    if path is not None:
        if not path.is_file():
            raise CliInputError(f"Description path is not a file: {path}")
        return path.read_text(encoding="utf-8")
    return direct or ""


def format_human_report(report: PreflightReport) -> str:
    media = report.media
    dimensions = (
        f"{media.width}x{media.height}"
        if media.width is not None and media.height is not None
        else "unknown dimensions"
    )
    duration = _format_duration(media.duration_seconds)
    lines = [
        "RELEASESEAL",
        "",
        report.verdict.value.replace("_", " "),
        f"Scan completeness: {report.scan_completeness.value}",
        "",
        "Media",
        f"{dimensions} • {media.video_codec or 'no video'} • "
        f"{media.audio_codec or 'no audio'} • {duration}",
        "",
        f"PASS  {report.passed_check_count} checks",
        f"WARN  {report.warning_count}",
        f"FAIL  {report.critical_count}",
    ]
    for finding in report.findings:
        label = "FAIL" if finding.status is FindingStatus.BLOCKED else "WARN"
        location = _format_finding_location(finding)
        title = (
            str(finding.details.get("title"))
            if finding.details and finding.details.get("title")
            else finding.message
        )
        lines.append(f"{label:<5} {location:<23} {title}")
    return "\n".join(lines)


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown duration"
    total_seconds = max(0, round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, second = divmod(remainder, 60)
    return (
        f"{hours:02d}:{minutes:02d}:{second:02d}"
        if hours
        else f"{minutes:02d}:{second:02d}"
    )


def _format_finding_location(finding) -> str:
    start = finding.timestamp_start_seconds
    end = finding.timestamp_end_seconds
    if start is None:
        return "PACKAGE"
    if end is None:
        return _format_timestamp(start)
    return f"{_format_timestamp(start)}–{_format_timestamp(end)}"


def _format_timestamp(seconds: float) -> str:
    minutes, second = divmod(seconds, 60)
    return f"{int(minutes):02d}:{second:05.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
