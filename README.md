# Creator Preflight

**Scan. Fix. Verify.**

Creator Preflight is creative release assurance for finished media. It checks the artifact that will ship, points to concrete evidence, repairs only narrowly allowlisted problems, and verifies the corrected export. It also compares a previous cut with a revised cut so requested changes and unmentioned physical changes are visible before approval.

Two workflows are first-class:

- **Final Export — Review one finished video before it ships.** Deterministic media, package, and caption checks can be extended with optional content review. Findings are timestamped and seekable; supported removals are previewed, approved, rendered to a new file, and rechecked for regressions.
- **Revision — Compare a previous cut with the revised cut.** A local deterministic map aligns the two timelines through removals and insertions, correlates timestamped notes, and surfaces additional changes. Optional semantic review sends only bounded evidence clips for eligible requests.

The distinctive loop is **actual media → evidence → bounded change → re-verification**. Deterministic measurements establish physical facts; optional AI interprets content conservatively; people retain ambiguous creative judgment and final approval.

## Why it exists

Creation tools help make an edit. Release mistakes still hide in the finished render: black gaps, dropped audio, broken captions, an unintended duplicate, or an editor revision outside the brief. Creator Preflight reviews what viewers and clients will actually receive.

## What it does

### Final Export

- Inspects streams and decodes bounded FFmpeg evidence for black, brief flashes, silence, static frames, unreadable media failures, and suspicious near-full-scale sample density.
- Checks title, description, URLs, chapters, format recommendations, SRT/WebVTT timing, caption structure, and coverage.
- Optionally reviews opening alignment, high-confidence continuity issues, and up to three selected public factual claims with provider citation metadata.
- Shows exact evidence in one player; timestamped findings and timeline markers seek directly to it.
- Maps trusted repetition and black-gap findings to one backend-owned `REMOVE_RANGE` operation. Every edit requires preview and approval; the source is never overwritten.
- Re-scans repaired MP4/H.264/AAC output, transforms supplied caption timing through the same cut map, and separates resolved/remaining/newly detected findings from deterministic unexpected media change.
- Produces a bounded Review Reel and CSV, Markdown, or JSON handoff.

### Revision

- Compares Previous and Revised media locally with a deterministic monotonic timeline map.
- Tolerates ordinary re-encoding and identifies removed, inserted, changed, and unchanged regions without a downstream change cascade.
- Correlates timestamped revision notes with physical change evidence. Untimed notes remain **Needs a timecode**; unmentioned edits remain **Additional changes**.
- Keeps physical change separate from semantic intent: “Change detected” never means the requested wording or mix is automatically correct.
- Optionally reviews up to five eligible `CHANGE_DETECTED` requests. Only short 320×180 Previous/Revised evidence clips (maximum 12 seconds each) are uploaded, source hashes are revalidated, and the deterministic map remains unchanged.

## The trust model

| Layer | Owns | Does not claim |
|---|---|---|
| Deterministic | Media structure, timestamps, physical revision changes, caption transforms, repair execution, regression comparison | Creative intent or semantic correctness |
| Optional AI | Opening/content interpretation, selected grounded claims, bounded revision-note interpretation | Certification, exhaustive review, or authority over deterministic evidence |
| Human | Ambiguous creative judgment and final approval | That an accepted intentional finding was automatically repaired |

Content verdict (`READY`, `NEEDS_REVIEW`, `BLOCKED`) is separate from scan completeness (`COMPLETE`, `PARTIAL`, `FAILED`). Provider failure cannot masquerade as a creator-content warning.

## Demo

Click **Load demo** in Final Export for the tracked, network-free fallback package. It enters the normal production scan path and shows a flash near `00:46`, a repairable black gap near `01:18–01:22`, and an audio dropout near `02:06–02:12`.

For the submission recording, build both workflows from one owner-supplied 90–240 second audiovisual source:

```sh
.venv/bin/python scripts/build_owner_demo.py .demo/owner/source.mp4
```

That writes ignored assets plus a provenance manifest under `frontend/public/demo/owner/`. When the manifest is present, both forms expose the owner demo through real browser `File` objects; otherwise Final Export safely falls back to the tracked synthetic package and Revision shows no broken demo action. See the [demo guide](docs/DEMO.md), [judging map](docs/JUDGING.md), and [evidence matrix](docs/EVIDENCE.md).

## How it works

```text
FINAL EXPORT
Finished package
  -> deterministic checks + optional content review
  -> timestamped findings + human judgment
  -> bounded preview/repair
  -> repaired export
  -> re-scan + deterministic regression verification

REVISION
Previous cut + Revised cut + optional notes
  -> deterministic temporal alignment
  -> physical change map + note correlation
  -> requested areas + additional changes
  -> optional semantic review of bounded evidence clips
```

FastAPI and the CLI share the same typed scanner. Pydantic validates configuration, reports, provider output, repairs, verification, revision maps, and semantic results. React consumes these contracts without recalculating verdicts or repairability.

## Quick start

Prerequisites: Python 3.10+, FFmpeg/FFprobe on `PATH`, and Node.js 22+ with npm.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install './backend[dev]'
cd frontend && npm ci && cd ..
```

Start the local app in two terminals:

```sh
.venv/bin/uvicorn creator_preflight.api:app --app-dir backend/src --reload --host 127.0.0.1 --port 8000
```

```sh
cd frontend
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. **Local Checks Only** requires no key and never uploads media. For **Full Review** and optional Revision semantic review:

```sh
.venv/bin/python -m pip install './backend[ai]'
export GEMINI_API_KEY="your-server-side-key"
```

The key stays server-side. Full Review may upload the selected video and thumbnail; Revision semantic review uploads only bounded evidence clips. Network access and provider availability are required only for explicitly requested AI work.

CLI and deterministic demo:

```sh
.venv/bin/creator-preflight scan path/to/video.mp4 --title "Publishing title" --description "Publishing description"
./scripts/run_demo.sh
```

Optional local caption speech coverage uses `./backend[transcription]`; transcription remains disabled and model download remains blocked by default.

## Evidence and tests

Run the complete network-free release gate:

```sh
./scripts/verify_release.sh
```

It runs backend tests, frontend tests, TypeScript/production build, Python compile/import sanity, and `git diff --check`. It makes no provider calls and downloads no models. CI repeats backend and frontend validation on Linux. Exact current counts and observed controlled performance belong in [docs/EVIDENCE.md](docs/EVIDENCE.md), not in the product promise.

## Privacy

- Local Checks and deterministic Revision comparison run in the local backend.
- Full Review temporarily sends the selected media to Gemini only after explicit selection; deletion is attempted but cannot be guaranteed if provider cleanup fails.
- Metadata Assist uploads a locally generated 32-second, 320×180 content sketch rather than the full master.
- Revision semantic review uploads only hash-bound, bounded evidence clips—not the full Previous/Revised source files.
- Request media lives in temporary directories; no account, database, or permanent server media store exists.

See [SECURITY.md](SECURITY.md) for precise boundaries.

## Limitations

Semantic review is probabilistic. Physical change does not prove semantic intent. AI revision review is request-limited, untimed notes are not auto-located, arbitrary large scene reordering is unsupported, and repetitive/static media may yield approximate boundaries. Repair Mode intentionally supports only validated removal. Factual review checks selected claims rather than certifying a video. Browser codec support varies. There is no persistent project history or collaboration system.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/SPEC.md](docs/SPEC.md).

## License

This repository uses the [Creator Preflight Source-Available Evaluation License](LICENSE). It permits viewing, judging, education, and personal non-commercial evaluation; it is not an OSI-approved open-source license and does not grant commercial use or redistribution rights.
