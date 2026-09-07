from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from creator_preflight.judge_proof import JudgeProofBundle


ROOT = Path(__file__).resolve().parents[2]
PROOF_ROOT = ROOT / "frontend" / "public" / "proof"
BUNDLE_PATH = PROOF_ROOT / "judge-proof.json"
sys.path.insert(0, str(ROOT / "scripts"))
from build_judge_proof import verify_expected_proof  # noqa: E402


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


@pytest.fixture
def isolated_proof(tmp_path: Path) -> Path:
    root = tmp_path / "proof"
    (root / "assets").mkdir(parents=True)
    shutil.copy2(BUNDLE_PATH, root / "judge-proof.json")
    for source in (PROOF_ROOT / "assets").iterdir():
        os.link(source, root / "assets" / source.name)
    return root


def _isolated_bundle(root: Path) -> JudgeProofBundle:
    return JudgeProofBundle.model_validate_json((root / "judge-proof.json").read_text(encoding="utf-8"))


def test_judge_proof_self_check_rejects_changed_missing_and_stale_assets(isolated_proof: Path) -> None:
    changed = isolated_proof / "assets" / "contract-control.srt"
    changed.unlink()
    changed.write_text("mutated", encoding="utf-8")
    with pytest.raises(RuntimeError, match="identity mismatch"):
        verify_expected_proof(_isolated_bundle(isolated_proof), isolated_proof)

    shutil.copy2(PROOF_ROOT / "assets" / "contract-control.srt", changed)
    missing = isolated_proof / "assets" / "contract-control.mp4"
    missing.unlink()
    with pytest.raises((FileNotFoundError, RuntimeError)):
        verify_expected_proof(_isolated_bundle(isolated_proof), isolated_proof)

    os.link(PROOF_ROOT / "assets" / "contract-control.mp4", missing)
    (isolated_proof / "assets" / "stale.tmp").write_bytes(b"stale")
    with pytest.raises(RuntimeError, match="stale"):
        verify_expected_proof(_isolated_bundle(isolated_proof), isolated_proof)


def test_judge_proof_self_check_rejects_stale_json_fact(isolated_proof: Path) -> None:
    payload = json.loads((isolated_proof / "judge-proof.json").read_text(encoding="utf-8"))
    payload["final_export"]["verification"]["unexpected_changes"] = [{
        "start_seconds": 30,
        "end_seconds": 31,
        "maximum_mean_difference": 20,
        "sample_count": 2,
    }]
    bundle = JudgeProofBundle.model_validate(payload)
    with pytest.raises(RuntimeError, match="unexpected media changes"):
        verify_expected_proof(bundle, isolated_proof)
