# Verification evidence

All automated commands below are network-free. “Observed” describes the current tests or an already accepted controlled run; it is not a guarantee for arbitrary media.

## Portable Judge Proof

`./scripts/build_judge_proof.sh` generates and validates `frontend/public/proof/judge-proof.json` from production services. `backend/tests/test_judge_proof.py` validates the strict schema, artifact identities, observed facts, correct-artifact receipt, and one-byte mutation mismatch. `frontend/src/JudgeProofApp.test.tsx` validates the static presentation and its generated-engine disclosure.

| Claim | Fixture/source | Expected result | Production implementation | Automated test | Observed result |
|---|---|---|---|---|---|
| Black detection | Attributed USGS Final Export derivative | Timestamped black finding | `PreflightScanner` + video detectors | `test_judge_proof_records_real_engine_acceptance_facts` | `24.00–27.08` detected |
| Safe repair | Same artifact | Allowlisted range removed | `FFmpegRepairEngine` | same test + generated bundle | One `REMOVE_RANGE` operation |
| Repaired re-scan | Repaired USGS artifact | Target resolved | `verify_repair` + scanner | same test | Black target resolved |
| Unexpected-change protection | Original/repaired pair | Zero unrelated changes | deterministic verification | same test | 0 unexpected changes |
| Deliberate unrelated mutation | Controlled verification fixture | Mutation detected | deterministic verification | `test_verification.py::test_visual_regression_detects_deliberate_unaffected_mutation` | Detected |
| Contract failure | Generated 6s media + supplied SRT | SAVE25 absent; SAVE20 near-match; BLOCKED | `ReleaseContractEvaluator` through scanner | `test_judge_proof_records_real_engine_acceptance_facts` | 4 pass, 1 deterministic fail |
| Missing text evidence | Contract fixture without captions | NOT_EVALUATED, never silent pass | `ReleaseContractEvaluator` | `test_release_contract.py::test_missing_text_source_is_not_evaluated_and_late_mention_fails` | NOT_EVALUATED |
| Revision mapping | Authentic USGS Previous/Revised pair | 2 requested changes and 1 additional | `RevisionCheckService` | Judge proof test + `test_revision_check.py` | 94.3% unchanged; 2/2; 1 additional |
| Whole release package | USGS video + authentic thumbnail | Truthful package states and delivery metadata | `release_package.py` through scanner | Judge proof UI test + `test_release_package.py` | 1333×750 JPEG; 3:32 badge |
| Thumbnail delivery assurance | Generated 1280×720 calibration corpus plus authentic USGS JPEG | Large/tiny/contrast/chrome/edge/detail distinctions with textless abstention | `thumbnail_assurance.py` behind `release_package.py` | `test_thumbnail_assurance.py`, API and frontend result tests | Deterministic regions and overlays; USGS text analysis abstained with no false finding |
| Local audio evidence candidate | Fake local transcript over a real multipart video upload | `NEEDS_REVIEW`, exact artifact/range/model provenance; never PASS/FAIL | `release_evidence.py` and recovery API | `test_release_evidence.py::test_machine_evidence_candidates_are_advisory_and_provenance_bound`, `test_api.py::test_audio_evidence_recovery_and_confirmation_use_real_multipart_boundary` | Advisory candidate at canonical source time |
| Machine transcript absence | Transcript contains no requested phrase | Original `NOT_EVALUATED`/caption-derived status remains; absence is not proven | `release_evidence.py` | `test_release_evidence.py::test_machine_transcript_absence_never_proves_absence` | No false deterministic absence |
| Artifact-bound human confirmation | Controlled candidate for `SAVE25` | Confirmed presence passes only the bound requirement; stale artifact/requirement/range/proposition rejected | confirmation API and backend reevaluation | `test_release_evidence.py`, `test_api.py` | Backend-updated verdict and evidence provenance |
| Confirmed forbidden presence | Controlled forbidden phrase candidate | Deterministic human-confirmed FAIL; no machine-only block | `release_evidence.py` | `test_release_evidence.py::test_human_confirmation_upgrades_only_the_bounded_proposition` | FAIL only after explicit confirmation |
| Release Plan/autopilot boundary | Mixed contract, repair, evidence, and human-only state | Deterministic next-action categories; SAFE repair keeps preview/approval/re-scan/regression checks | `release_plan.py`, existing Repair flow | `test_release_evidence.py::test_release_plan_separates_blockers_safe_actions_evidence_and_review`, frontend Repair tests | No autonomous truth mutation |
| Receipt valid | Repaired shipping artifact | VALID | receipt builders + `ReceiptVerifier` | Judge proof test + `test_release_receipt.py` | VALID |
| Wrong receipt artifact | One-byte-mutated temporary copy | MISMATCH | `ReceiptVerifier` | self-check + Judge proof test | MISMATCH |
| Stale receipt digest | Controlled edited receipt | INVALID_RECEIPT | `ReceiptVerifier` | `test_release_receipt.py::test_modified_receipt_with_stale_digest_is_invalid` | INVALID_RECEIPT |

## Final Export matrix

| Case | Expected result | Observed result | Reproducible evidence | Class |
|---|---|---|---|---|
| Clean media | No fabricated issue | Clean control is READY | `backend/tests/test_report.py::test_ready_report_and_passed_check_accounting` | Deterministic |
| Black export gap | Timestamped finding | Known 2–5s and browser-demo gaps detected | `test_detectors.py`; `./scripts/run_demo.sh` | Deterministic |
| Audio dropout | Timestamped finding | Sustained dropout detected | `test_release_features.py`; tracked demo | Deterministic |
| Repair | Approved interval removed | Output duration reduced; video/audio readable | `test_repairs.py::test_ffmpeg_render_removes_multiple_ranges_and_preserves_video_audio` | Deterministic |
| Caption repair | Cues follow the cut | Inside cues removed; overlaps compressed; source unchanged | `test_verification.py::test_caption_cues_follow_multiple_ranges_and_stay_inside_repaired_duration` | Deterministic |
| Repair regression | Unapproved visual mutation surfaced | Mutation outside cut becomes unexpected media change | `test_verification.py::test_visual_regression_detects_deliberate_unaffected_mutation` | Deterministic |
| AI variance | Not called a media regression | Repaired-only finding is neutral newly detected evidence | `frontend/src/App.test.tsx` finding-variance test | AI + deterministic boundary |
| Relevant opening hook | No fixed timer warning | Relevant setup accepted; direct delivery remains informational | `test_promise_check.py` | AI |
| Factual uncertainty | Abstain rather than invent certainty | Missing claim-specific evidence remains inconclusive | `test_claim_review.py` | AI |
| Release Contract pass | Explicit obligations evaluated from trusted state | Typed matrix covers captions, metadata, duration, resolution, and aspect ratio | `test_release_contract.py::test_deterministic_requirement_matrix_and_evidence_sources` | Deterministic |
| Artifact-bound receipt | Exact package identity and recorded result state | Canonical/digest mutation matrix, CLI verification, and route/UI transport | `test_release_receipt.py`, `test_cli.py::test_verify_receipt_cli_valid_mismatch_and_invalid` | Deterministic |
| Whole release package | Presence/validity and bounded thumbnail delivery measurements | Package matrix, safe geometry, duration badge, API and result UI tests | `test_release_package.py`, `test_api.py`, `App.test.tsx` | Deterministic |
| Missing exact token | Contract blocks delivery without fuzzy passing | `SAVE20` is neutral near-match evidence for required `SAVE25` | `test_release_contract.py::test_deterministic_contract_failure_blocks_real_scan` | Deterministic |
| Semantic uncertainty | Advisory, never deterministic block | Low confidence becomes `NEEDS_REVIEW`; unavailable evidence remains `NOT_EVALUATED` | `test_release_contract.py` semantic tests | AI trust boundary |

## Revision matrix

| Case | Expected result | Observed result | Reproducible evidence | Class |
|---|---|---|---|---|
| Identical file | 100% unchanged | Hash fast path returns unchanged ratio 1 | `test_revision.py::test_identical_file_uses_hash_fast_path` | Deterministic |
| Ordinary re-encode | No meaningful change | Overwhelmingly unchanged | `test_revision.py::test_normal_h264_reencode_is_overwhelmingly_unchanged` | Deterministic |
| Removal | Correct interval; downstream realigns | Located without cascade | `test_revision.py::test_single_removal_is_located_and_downstream_realigns` | Deterministic |
| Insertion | Correct revised interval; downstream realigns | Located with stable previous anchor | `test_revision.py::test_single_insertion_is_located_and_downstream_realigns` | Deterministic |
| Visual replacement | Changed, visual-only | Correct modality evidence | `test_revision.py::test_same_duration_visual_replacement_is_changed_visual_only` | Deterministic |
| Audio-only replacement | Changed, audio-only | Correct modality evidence | `test_revision.py::test_audio_only_replacement_is_changed_audio_only` | Deterministic |
| Early cut | No downstream cascade | Later timeline remains matched | `test_revision.py::test_early_removal_does_not_cascade_through_remaining_timeline` | Deterministic |
| Multi-edit | Separate edits retained | Intervening matches preserved | `test_revision.py::test_multiple_edits_remain_separate_and_preserve_intervening_matches` | Deterministic |
| Requested physical change | Request correlated | Timestamped note becomes Change detected | `test_revision_check.py::test_notes_match_removed_changed_and_insertion_anchor` | Deterministic |
| Requested area unchanged | Neutral no-change result | No change found | `test_revision_check.py::test_no_change_untimed_and_additional_change_semantics` | Deterministic |
| Additional change | Unmentioned edit remains visible | Additional change emitted | same test as above | Deterministic |
| Untimed note | Needs location | No guessed location | same test as above | Human |

## Semantic Revision Review matrix

| Case | Expected result | Observed result | Reproducible evidence | Class |
|---|---|---|---|---|
| Appears satisfied | Bounded positive interpretation | Typed satisfied result | `test_revision_semantic.py::test_service_statuses_confidence_isolation_order_limit_hash_and_zero_ineligible` | AI |
| Appears unresolved | Bounded concern | Typed unresolved result | same test | AI |
| Inconclusive | Honest abstention | Typed inconclusive result | same test | AI |
| Low confidence | Inconclusive | Confidence policy suppresses conclusion | same test | AI |
| Hash mismatch | Reject review | Source consistency error | same test and route test | Deterministic trust boundary |
| Ineligible request | Zero provider calls | No-change, needs-location, and additional changes excluded | same test | Deterministic policy |
| Whole-source protection | Only evidence clips uploaded | Fake client sees two bounded clip paths | `test_revision_semantic.py::test_gemini_pair_provider_uploads_generates_and_deletes_both_clips` | Deterministic privacy boundary |

## Observed performance

Development-machine controlled observations, not service-level objectives:

| Workload | Observed |
|---|---:|
| RevisionMap, approximately 3-minute pair | 2.230s |
| Revision Check API, approximately 3-minute pair | 2.412s total / 2.349s analysis |
| Controlled semantic revision review | 0.295s evidence rendering / 11.107s provider / 11.712s total |

The accepted live semantic case used a locally generated Previous/Revised pair with a `YEAR 2024` → `YEAR 2025` request at 2–6 seconds. Gemini received only the two bounded clips, returned **Appears satisfied**, and both uploads were deleted. It used one semantic generation and no retry.

## Run it

```sh
./scripts/verify_release.sh
```

Focused deterministic revision proof:

```sh
.venv/bin/python -m pytest backend/tests/test_revision.py backend/tests/test_revision_check.py backend/tests/test_revision_semantic.py
```

Current exact test totals are recorded in `docs/STATUS.md` after the final release run.
