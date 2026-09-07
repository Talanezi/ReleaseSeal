#!/usr/bin/env python3
"""Validate the static judge proof and reproduce receipt checks."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from creator_preflight.judge_proof import JudgeProofBundle  # noqa: E402
from creator_preflight.release_receipt import ReceiptVerificationStatus, ReceiptVerifier  # noqa: E402
from build_judge_proof import verify_expected_proof  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify generated Judge Proof Mode evidence.")
    parser.add_argument("root", nargs="?", type=Path, default=ROOT / "frontend" / "public" / "proof")
    args = parser.parse_args()
    try:
        bundle = JudgeProofBundle.model_validate_json((args.root / "judge-proof.json").read_text(encoding="utf-8"))
        verify_expected_proof(bundle, args.root)
        final = bundle.final_export
        verifier = ReceiptVerifier()
        exact = verifier.verify(
            final.receipt.model_dump(mode="json"), video_path=args.root / final.repaired_video.relative_path,
            thumbnail_path=args.root / final.thumbnail.relative_path, title=final.title, description=final.description,
        )
        if exact.status is not ReceiptVerificationStatus.VALID:
            raise RuntimeError("Exact proof artifact no longer validates against its receipt.")
        with tempfile.TemporaryDirectory(prefix="creator-preflight-proof-check-") as temporary:
            mutated = Path(temporary) / "mutated.mp4"
            shutil.copyfile(args.root / final.repaired_video.relative_path, mutated)
            with mutated.open("r+b") as handle:
                handle.seek(-1, 2)
                original = handle.read(1)
                handle.seek(-1, 2)
                handle.write(bytes([original[0] ^ 1]))
            mismatch = verifier.verify(final.receipt.model_dump(mode="json"), video_path=mutated, thumbnail_path=args.root / final.thumbnail.relative_path, title=final.title, description=final.description)
            if mismatch.status is not ReceiptVerificationStatus.MISMATCH:
                raise RuntimeError("Mutated artifact did not mismatch its receipt.")
    except Exception as exc:
        print(f"verify-judge-proof: {exc}", file=sys.stderr)
        return 2
    print("Judge proof valid: production facts, artifact hashes, and receipt checks match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
