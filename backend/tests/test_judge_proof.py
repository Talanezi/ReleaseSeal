from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from creator_preflight.judge_proof import JudgeProofBundle


ROOT = Path(__file__).resolve().parents[2]
PROOF_ROOT = ROOT / "frontend" / "public" / "proof"
BUNDLE_PATH = PROOF_ROOT / "judge-proof.json"


def load_bundle() -> JudgeProofBundle:
    return JudgeProofBundle.model_validate_json(BUNDLE_PATH.read_text(encoding="utf-8"))


def test_committed_judge_proof_is_strict_and_self_verifying() -> None:
    bundle = load_bundle()
    assert bundle.generation_origin == "GENERATED_FROM_ENGINE"
    assert bundle.final_export.generation_origin == "GENERATED_FROM_ENGINE"
    assert bundle.release_contract.generation_origin == "GENERATED_FROM_ENGINE"
    assert bundle.revision.generation_origin == "GENERATED_FROM_ENGINE"

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_judge_proof.py"), str(PROOF_ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Judge proof valid" in result.stdout


def test_judge_proof_records_real_engine_acceptance_facts() -> None:
    bundle = load_bundle()
    final = bundle.final_export
    assert final.original_report.review_mode.value == "local"
    assert final.original_report.ai_review.status.value == "disabled"
    assert any(finding.code == "VIDEO_BLACK_SEGMENT" for finding in final.original_report.findings)
    assert any(item.original_finding and item.original_finding.code == "VIDEO_BLACK_SEGMENT" for item in final.verification.resolved)
    assert final.verification.unexpected_changes == []
    assert final.receipt_valid.status.value == "VALID"
    assert final.receipt_mutated_artifact.status.value == "MISMATCH"

    contract = bundle.release_contract.report.release_contract
    assert bundle.release_contract.report.review_mode.value == "local"
    promo = next(item for item in contract.results if item.requirement_id == "promo")
    assert bundle.release_contract.report.verdict.value == "BLOCKED"
    assert promo.status.value == "FAIL"
    assert "SAVE20" in promo.evidence

    revision = bundle.revision.report
    assert revision.revision_map.unchanged_ratio == pytest.approx(0.943, abs=0.001)
    assert revision.requested_changes_detected_count == 2
    assert revision.requested_changes_not_detected_count == 0
    assert revision.additional_change_count == 1


def test_judge_proof_schema_rejects_unknown_fields_and_unsafe_paths() -> None:
    payload = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        JudgeProofBundle.model_validate(payload)

    payload.pop("unexpected")
    payload["final_export"]["original_video"]["relative_path"] = "../private.mp4"
    with pytest.raises(ValidationError):
        JudgeProofBundle.model_validate(payload)
