#!/usr/bin/env python3
"""Generate portable Judge Proof Mode assets through production services."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from releaseseal.config import PreflightConfig  # noqa: E402
from releaseseal.engine import PreflightScanner  # noqa: E402
from releaseseal.judge_proof import (  # noqa: E402
    ContractProof,
    FinalExportProof,
    JudgeProofBundle,
    ProofProvenance,
    RevisionProof,
    artifact,
)
from releaseseal.models import FindingStatus, PublishingPackage, ReviewMode  # noqa: E402
from releaseseal.release_contract import (  # noqa: E402
    AspectRatio,
    CaptionsRequired,
    MaxDuration,
    MinResolution,
    ReleaseContract,
    RequiredExactToken,
)
from releaseseal.release_receipt import (  # noqa: E402
    ReceiptVerificationStatus,
    ReceiptVerifier,
    build_final_export_receipt,
    build_revision_receipt,
)
from releaseseal.repairs import FFmpegRepairEngine  # noqa: E402
from releaseseal.revision_check import RevisionCheckService  # noqa: E402
from releaseseal.verification import verify_repair  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build static proof evidence using ReleaseSeal production services.")
    parser.add_argument("--owner-demo", type=Path, default=ROOT / "frontend" / "public" / "demo" / "owner")
    parser.add_argument("--output", type=Path, default=ROOT / "frontend" / "public" / "proof")
    args = parser.parse_args()
    try:
        bundle = build_judge_proof(args.owner_demo, args.output)
        verify_expected_proof(bundle, args.output)
    except Exception as exc:
        print(f"build-judge-proof: {exc}", file=sys.stderr)
        return 2
    print(f"Judge proof built and verified: {args.output / 'judge-proof.json'}")
    return 0


def build_judge_proof(owner_demo: Path, output: Path) -> JudgeProofBundle:
    manifest_path = owner_demo / "demo-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Authentic owner demo is missing. Build it with scripts/build_owner_demo.py first.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source_type") != "public_domain" or not manifest.get("source_credit"):
        raise RuntimeError("Judge proof requires explicit public-domain source provenance.")
    assets = manifest["assets"]
    required = [
        owner_demo / assets["final_export"]["video"], owner_demo / assets["final_export"]["thumbnail"],
        owner_demo / assets["revision"]["previous"], owner_demo / assets["revision"]["revised"],
        owner_demo / assets["revision"]["notes"],
    ]
    if any(not item.is_file() for item in required):
        raise RuntimeError("Authentic owner demo assets are incomplete.")
    output.mkdir(parents=True, exist_ok=True)
    media_dir = output / "assets"
    media_dir.mkdir(parents=True, exist_ok=True)
    final_original = media_dir / "yellowstone-final-export.mp4"
    revision_previous = media_dir / "yellowstone-revision-previous.mp4"
    revision_revised = media_dir / "yellowstone-revision-revised.mp4"
    thumbnail = media_dir / "yellowstone-thumbnail.jpg"
    _compact(owner_demo / assets["final_export"]["video"], final_original)
    _compact(owner_demo / assets["revision"]["previous"], revision_previous)
    _compact(owner_demo / assets["revision"]["revised"], revision_revised)
    shutil.copy2(owner_demo / assets["final_export"]["thumbnail"], thumbnail)

    title = (owner_demo / assets["final_export"]["title"]).read_text(encoding="utf-8").strip()
    description = (owner_demo / assets["final_export"]["description"]).read_text(encoding="utf-8").strip()
    config = PreflightConfig()
    scanner = PreflightScanner(config=config, configuration_source="judge-proof deterministic defaults")
    package = PublishingPackage(title=title, description=description, thumbnail_path=thumbnail)
    original_report = scanner.scan(final_original, package, review_mode=ReviewMode.LOCAL)
    proposal = next((item for item in original_report.repair_plan.proposals if item.finding_code == "VIDEO_BLACK_SEGMENT" and item.operation), None)
    if proposal is None or proposal.operation is None:
        raise RuntimeError("Expected black-section repair proposal was not reproduced.")
    repaired = media_dir / "yellowstone-repaired.mp4"
    FFmpegRepairEngine().render(final_original, repaired, [proposal.operation])
    repaired_report = scanner.scan(repaired, package, review_mode=ReviewMode.LOCAL)
    verification = verify_repair(final_original, repaired, [proposal.operation], original_report, repaired_report, config.verification)
    created_at = datetime.now(timezone.utc)
    receipt = build_final_export_receipt(
        shipping_video_path=repaired, original_video_path=final_original,
        report=original_report, verification=verification, operations=[proposal.operation],
        config=config, title=title, description=description, thumbnail_path=thumbnail,
        created_at=created_at,
    )
    verifier = ReceiptVerifier()
    receipt_valid = verifier.verify(receipt.model_dump(mode="json"), video_path=repaired, thumbnail_path=thumbnail, title=title, description=description)
    with tempfile.TemporaryDirectory(prefix="releaseseal-proof-mutation-") as temporary:
        mutated = Path(temporary) / "mutated.mp4"
        shutil.copyfile(repaired, mutated)
        with mutated.open("r+b") as handle:
            handle.seek(-1, 2)
            original = handle.read(1)
            handle.seek(-1, 2)
            handle.write(bytes([original[0] ^ 1]))
        receipt_mismatch = verifier.verify(receipt.model_dump(mode="json"), video_path=mutated, thumbnail_path=thumbnail, title=title, description=description)

    contract_video = media_dir / "contract-control.mp4"
    contract_captions = media_dir / "contract-control.srt"
    _contract_video(contract_video)
    contract_captions.write_text("1\n00:00:00,500 --> 00:00:02,500\nUse promo code SAVE20 for this release.\n", encoding="utf-8")
    contract = ReleaseContract(name="Controlled delivery brief", requirements=[
        RequiredExactToken(id="promo", type="REQUIRED_EXACT_TOKEN", instruction="Use exact promo code SAVE25", value="SAVE25"),
        MaxDuration(id="duration", type="MAX_DURATION", instruction="Keep the video under ten seconds", maximum_seconds=10),
        MinResolution(id="resolution", type="MIN_RESOLUTION", instruction="Deliver at least 1280×720", minimum_width=1280, minimum_height=720),
        AspectRatio(id="aspect", type="ASPECT_RATIO", instruction="Deliver at 16:9", width_ratio=16, height_ratio=9),
        CaptionsRequired(id="captions", type="CAPTIONS_REQUIRED", instruction="Supply captions"),
    ])
    contract_title = "Controlled release package"
    contract_description = "A deterministic release-contract proof fixture."
    contract_report = scanner.scan(contract_video, PublishingPackage(title=contract_title, description=contract_description, captions_path=contract_captions, release_contract=contract), review_mode=ReviewMode.LOCAL)

    notes = (owner_demo / assets["revision"]["notes"]).read_text(encoding="utf-8")
    revision_report = RevisionCheckService(config=config.revision_check).check(
        revision_previous, revision_revised, notes,
        previous_filename=revision_previous.name, revised_filename=revision_revised.name,
    )
    revision_receipt = build_revision_receipt(previous_path=revision_previous, revised_path=revision_revised, notes=notes, report=revision_report, config=config, created_at=created_at)
    revision_valid = verifier.verify(revision_receipt.model_dump(mode="json"), previous_path=revision_previous, revised_path=revision_revised, revision_notes=notes)

    contract_video_artifact = artifact(contract_video, root=output, mime_type="video/mp4")
    bundle = JudgeProofBundle(
        generated_at=created_at,
        provenance=ProofProvenance(
            source_type="public_domain", source_credit=manifest["source_credit"],
            source_title=manifest["source_title"], source_url=manifest.get("source_url"),
            source_sha256=manifest["source_sha256"], owner_demo_generator_version=manifest.get("generator_version"),
        ),
        final_export=FinalExportProof(
            original_video=artifact(final_original, root=output, mime_type="video/mp4"),
            repaired_video=artifact(repaired, root=output, mime_type="video/mp4"),
            thumbnail=artifact(thumbnail, root=output, mime_type="image/jpeg"),
            title=title, description=description, original_report=original_report,
            repair_operation=proposal.operation, verification=verification, receipt=receipt,
            receipt_valid=receipt_valid, receipt_mutated_artifact=receipt_mismatch,
        ),
        release_contract=ContractProof(
            provenance=ProofProvenance(
                source_type="generated_control",
                source_credit="ReleaseSeal deterministic fixture generator",
                source_title="SAVE20 captioned Release Contract control",
                source_sha256=contract_video_artifact.sha256,
            ),
            video=contract_video_artifact,
            captions=artifact(contract_captions, root=output, mime_type="application/x-subrip"),
            title=contract_title, description=contract_description, contract=contract, report=contract_report,
        ),
        revision=RevisionProof(
            previous_video=artifact(revision_previous, root=output, mime_type="video/mp4"),
            revised_video=artifact(revision_revised, root=output, mime_type="video/mp4"),
            notes=notes, report=revision_report, receipt=revision_receipt, receipt_valid=revision_valid,
        ),
    )
    verify_expected_proof(bundle, output)
    (output / "judge-proof.json").write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return bundle


def verify_expected_proof(bundle: JudgeProofBundle, root: Path) -> None:
    from releaseseal.judge_proof import proof_artifacts

    for item in proof_artifacts(bundle):
        path = root / item.relative_path
        actual = artifact(path, root=root, mime_type=item.mime_type)
        if actual.sha256 != item.sha256 or actual.size_bytes != item.size_bytes:
            raise RuntimeError(f"Proof artifact identity mismatch: {item.relative_path}")
    referenced = {item.relative_path for item in proof_artifacts(bundle)}
    actual_assets = {
        path.relative_to(root).as_posix()
        for path in (root / "assets").iterdir()
        if path.is_file()
    }
    if actual_assets != referenced:
        raise RuntimeError("Proof assets contain missing, unreferenced, or stale files.")
    if not any(item.code == "VIDEO_BLACK_SEGMENT" for item in bundle.final_export.original_report.findings):
        raise RuntimeError("Final Export proof lost the expected black finding.")
    if not any(item.original_finding and item.original_finding.code == "VIDEO_BLACK_SEGMENT" for item in bundle.final_export.verification.resolved):
        raise RuntimeError("Repair proof did not resolve the black finding.")
    if bundle.final_export.verification.unexpected_changes:
        raise RuntimeError("Repair proof contains unexpected media changes.")
    if bundle.final_export.receipt_valid.status is not ReceiptVerificationStatus.VALID:
        raise RuntimeError("Correct-artifact receipt verification is not valid.")
    if bundle.final_export.receipt_mutated_artifact.status is not ReceiptVerificationStatus.MISMATCH:
        raise RuntimeError("Mutated-artifact receipt proof did not mismatch.")
    promo = next((item for item in bundle.release_contract.report.release_contract.results if item.requirement_id == "promo"), None)
    if bundle.release_contract.report.verdict is not FindingStatus.BLOCKED or promo is None or promo.status.value != "FAIL" or "SAVE20" not in promo.evidence:
        raise RuntimeError("Release Contract proof did not reproduce the grounded SAVE25/SAVE20 failure.")
    revision = bundle.revision.report
    if revision.requested_change_count != 2 or revision.requested_changes_detected_count != 2 or revision.requested_changes_not_detected_count != 0 or revision.additional_change_count != 1:
        raise RuntimeError("Revision proof did not reproduce two requested and one additional change.")
    if bundle.revision.receipt_valid.status is not ReceiptVerificationStatus.VALID:
        raise RuntimeError("Revision receipt verification is not valid.")


def _compact(source: Path, destination: Path) -> None:
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source),
        "-vf", "fps=12,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "32", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "64k", "-ar", "48000", "-movflags", "+faststart", str(destination),
    ], timeout=360)


def _contract_video(destination: Path) -> None:
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "64k", "-shortest", "-movflags", "+faststart", str(destination),
    ], timeout=120)


def _run(command: list[str], *, timeout: float) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError("FFmpeg could not generate a judge-proof artifact.")


if __name__ == "__main__":
    raise SystemExit(main())
