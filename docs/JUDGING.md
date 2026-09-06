# Judge navigation

Creator Preflight is creative release assurance for two related decisions: whether one final export is ready to ship, and whether a revised cut changed where the notes expected it to.

## Functionality

| Implemented capability | Evidence | Where to look | Material boundary |
|---|---|---|---|
| Final Export scans real media and publishing inputs | Tracked browser demo; backend detector, caption, API, and report tests | `backend/src/creator_preflight/engine.py`, `frontend/src/components/ResultsView.tsx` | Findings are evidence, not creative certainty |
| Preview, approve, render, and verify a narrow repair | FFmpeg repair and automatic verification integration tests | `repairs.py`, `verification.py` | Only allowlisted range removal |
| Revision maps V1/V2 physical changes and notes | Identical, re-encode, removal, insertion, replacement, audio, and multi-edit tests | `revision.py`, `revision_check.py` | Physical change does not prove intent |
| Optional bounded semantic revision review | Fake-provider matrix plus one accepted controlled live case | `revision_evidence.py`, `revision_semantic.py` | Eligible timestamped requests only |

## Creativity

The product treats finished-media release as an assurance problem rather than another creation surface. Its distinctive loop is media evidence → bounded repair/version change → re-verification. The same trust hierarchy applies to both Final Export and Revision: deterministic facts first, optional interpretation second, human approval last.

Evidence: the two first-class workflows in `frontend/src/App.tsx`, shared typed contracts, and the end-to-end walkthrough in `docs/DEMO.md`.

## Technical execution

- FFmpeg/FFprobe subprocesses are bounded and never use a shell.
- Pydantic forbids unknown provider/report fields at trust boundaries.
- Caption and video cuts share one timeline transform.
- Revision alignment is monotonic and bounded; semantic review is hash-bound to the deterministic report.
- Provider tasks isolate failure and attempt cleanup.
- CI and `./scripts/verify_release.sh` run without credentials or provider traffic.

Evidence: `backend/tests/test_verification.py`, `test_revision.py`, `test_revision_check.py`, `test_revision_semantic.py`, and `.github/workflows/ci.yml`.

## Real-world usefulness

Final Export catches release defects at seekable timestamps and helps with a limited safe correction. Revision gives creators and reviewers a concrete change map rather than requiring a full manual rewatch to discover every physical edit. Downloads provide portable JSON/Markdown/CSV evidence.

Boundary: this is a local, single-user release candidate, not a hosted collaboration or general editing system. AI can abstain and does not certify release safety.
