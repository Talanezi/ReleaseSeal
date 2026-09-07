# Judge navigation

For the deliberately skeptical counter-assessment—including the strongest remaining argument against the project in each rubric category—see [`LOSS_REGISTER.md`](LOSS_REGISTER.md). That register complements this evidence map; it is not a product claim or competitive scorecard.

Creator Preflight is creative release assurance for two related decisions: whether one final export is ready to ship, and whether a revised cut changed where the notes expected it to.

Start at `/proof/` for a backend-free inspection path. The page links every claim to typed, generated engine state and clearly discloses that the evidence is precomputed. Rebuild and self-verify it with `./scripts/build_judge_proof.sh`.

## Functionality

| Implemented capability | Evidence | Where to look | Material boundary |
|---|---|---|---|
| Final Export scans real media and publishing inputs | Tracked browser demo; backend detector, caption, API, and report tests | `backend/src/creator_preflight/engine.py`, `frontend/src/components/ResultsView.tsx` | Findings are evidence, not creative certainty |
| Preview, approve, render, and verify a narrow repair | FFmpeg repair and automatic verification integration tests | `repairs.py`, `verification.py` | Only allowlisted range removal |
| Revision maps V1/V2 physical changes and notes | Identical, re-encode, removal, insertion, replacement, audio, and multi-edit tests | `revision.py`, `revision_check.py` | Physical change does not prove intent |
| Optional bounded semantic revision review | Fake-provider matrix plus one accepted controlled live case | `revision_evidence.py`, `revision_semantic.py` | Eligible timestamped requests only |
| Contract-driven release gate | Deterministic matrix, hostile extraction tests, API and result UI tests | `release_contract.py`, `release_contract_extraction.py`, Final Export form/results | AI structures explicit brief text; backend evaluates deterministic obligations |
| Artifact-bound release evidence | Exact-video/package mutation matrix plus CLI verification | `release_receipt.py`, receipt API routes, Final Export/Revision receipt downloads | Receipt digest detects stale modification; it is not a signature or legal attestation |
| Whole delivery package | One compact result for video, authentic thumbnail, captions, publishing text, chapters, and requirements | `release_package.py`, Final Export package summary and delivery preview | Thumbnail review is bounded file/geometry analysis, not a creative-quality score |
| Automated thumbnail delivery assurance | Provider-free pixel analysis measures confident text-like regions at delivered sizes, estimated contrast, modeled chrome/edge overlap, and structural detail retention | `thumbnail_assurance.py`, `test_thumbnail_assurance.py`, Delivery Preview overlays | Heuristic interpretation is advisory, abstains on uncertain/textless images, and never predicts CTR or blocks release |
| Spoken-requirement evidence recovery | Optional local ASR finds bounded candidate moments; explicit listening/confirmation upgrades only an artifact-bound presence fact | `release_evidence.py`, recovery/confirmation API tests, Release Plan UI | Machine text never passes, fails, or blocks by itself; absence is never inferred from a miss |

## Creativity

The product treats finished-media release as an assurance problem rather than another creation surface. Its distinctive loop is media evidence → bounded repair/version change → re-verification. The same trust hierarchy applies to both Final Export and Revision: deterministic facts first, optional interpretation second, human approval last.

Evidence: the two first-class workflows in `frontend/src/App.tsx`, shared typed contracts, and the end-to-end walkthrough in `docs/DEMO.md`.

- Treats release readiness as an evidence-and-obligation problem, not another generative editor.
- Connects a bounded repair to an automatic re-scan and unaffected-media regression check.
- Separates requested Revision changes from additional physical changes and optional semantic interpretation.
- Binds exact package artifacts and recorded decisions in a machine-verifiable receipt without overclaiming a signature.

Proof pointers: `/proof/` sections B–E, `test_verification.py`, `test_revision_check.py`, and `test_release_receipt.py`.

## Technical execution

- FFmpeg/FFprobe subprocesses are bounded and never use a shell.
- Pydantic forbids unknown provider/report fields at trust boundaries.
- Caption and video cuts share one timeline transform.
- Revision alignment is monotonic and bounded; semantic review is hash-bound to the deterministic report.
- Provider tasks isolate failure and attempt cleanup.
- CI and `./scripts/verify_release.sh` run without credentials or provider traffic.

Evidence: `backend/tests/test_verification.py`, `test_revision.py`, `test_revision_check.py`, `test_revision_semantic.py`, and `.github/workflows/ci.yml`.

Judge Proof itself is strict and self-verifying: Pydantic rejects unknown bundle fields and unsafe artifact paths; every referenced asset is SHA-256 checked; expected production facts are asserted; and exact receipt verification is rerun against both the correct and a temporary one-byte-mutated artifact. See `creator_preflight/judge_proof.py`, `scripts/build_judge_proof.py`, `scripts/verify_judge_proof.py`, and `test_judge_proof.py`.

## Real-world usefulness

Final Export catches release defects at seekable timestamps and helps with a limited safe correction. Revision gives creators and reviewers a concrete change map rather than requiring a full manual rewatch to discover every physical edit. Downloads provide portable JSON/Markdown/CSV evidence.

Boundary: this is a local, single-user release candidate, not a hosted collaboration or general editing system. AI can abstain and does not certify release safety.

- Final Export puts black, silence, caption, package, and contract evidence at source timecodes.
- Repair approval never overwrites the original and the corrected output is rechecked before presentation.
- Release Contract catches delivery obligations that technical QC cannot, demonstrated by SAVE25 versus actual caption evidence SAVE20.
- When captions are absent or omit a required positive phrase, local evidence recovery reduces manual hunting while preserving source, model, source time, and artifact identity. Human confirmation—not ASR—changes deterministic contract truth.
- Revision shows whether requested regions physically changed and preserves unmentioned changes for review.
- The package/receipt path connects what was inspected to the exact artifact intended to ship.

Evidence pointers: `/proof/`, `docs/EVIDENCE.md`, and the focused production tests named there.
