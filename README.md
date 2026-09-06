# Creator Preflight

**Scan. Fix. Verify.**

Review a final export or compare a revised cut before your audience sees it. Creator Preflight finds concrete release problems, maps physical changes between versions, points to exact evidence, repairs the limited edits it can perform safely, and checks corrected exports for regressions.

It combines deterministic media inspection with optional multimodal review. The browser keeps the workflow in one place: a concise AI review, one video player, an Action Queue, repair previews, automatic verification, and editor-friendly exports.

## What it does

- Finds sustained black video, brief black-flash candidates, silence, static frames, stream problems, and suspicious near-full-scale audio with FFmpeg/FFprobe.
- Checks title, description, URLs, chapters, resolution, aspect ratio, and caption requirements.
- Parses SRT and WebVTT content and measures timing, structure, overlap, range, and merged coverage.
- Optionally reviews title/thumbnail promise alignment, internal viewer-facing inconsistencies, and a few important public factual claims.
- Shows timestamped evidence; clicking a finding seeks the selected video.
- Offers deterministic `REMOVE_RANGE` repairs only for validated repeated or black sections, always after preview and approval.
- Re-scans repaired exports, classifies fixed/remaining/new findings, checks unaffected visual regions, and creates a bounded Review Reel.
- Exports the review as CSV, Markdown, or JSON.

The report separates the content verdict (`READY`, `NEEDS_REVIEW`, or `BLOCKED`) from scan completeness (`COMPLETE`, `PARTIAL`, or `FAILED`). A provider outage cannot become a content warning.

## Core workflow

```text
Finished video
  -> Local Checks or Full Review
  -> AI review and Action Queue
  -> preview and approve supported repairs
  -> repaired MP4
  -> automatic re-scan and regression check
  -> Repaired / Review Reel in the main player
```

The browser also offers **Revision**, a local deterministic comparison workflow. Add a previous cut and revised cut, optionally paste one revision note per line, and Creator Preflight maps removed, inserted, changed, and unchanged media. Timestamped notes are correlated with nearby physical changes; untimed notes remain clearly unlocated. A detected change never claims that the requested wording, logo, mix, or other semantic intent is correct.

After that physical comparison, an explicit optional action can compare short Previous/Revised evidence clips against eligible timestamped requests. It reports only **Appears satisfied**, **Appears unresolved**, **Inconclusive**, or **Review unavailable**. The full source cuts are not uploaded for this semantic step, and the deterministic map remains authoritative for where media changed.

Accepted note examples include `00:34 Remove the old logo`, `01:12.25 Lower the music`, `00:34-00:39 Remove this section`, and `1:02:14 Replace the end card`. Notes use the previous-cut timeline. The Revision result provides one Previous/Revised player, clickable change strips, and JSON or Markdown downloads.

Ambiguous findings stay in human review. Marking an item Accepted records a session-local decision; it does not pretend an automated repair resolved it.

## Full Review and Local Checks

**Local Checks Only** runs deterministic technical, publishing, and caption checks. It requires no API key and never sends media to Gemini. Its review summary is generated deterministically.

**Full Review** adds optional Gemini video tasks:

- Opening review distinguishes direct delivery, relevant hooks/setups, unrelated delay, and contradictions. Direct-delivery time is informational; elapsed time alone never creates a warning.
- Continuity review looks conservatively for high-confidence internal inconsistencies, visible placeholders, and accidental repetition.
- Factual review selects at most three important public claims and verifies each independently with Google Search grounding. Only a high-confidence conflict with claim-specific provider citations becomes a warning.

Full Review uploads the video once per scan and shares that temporary remote file across video tasks. AI evidence is probabilistic, review-only, and never blocks publication by itself. Metadata Assist is a separate explicit action that builds a local 32-second, 320×180 audiovisual sketch sampled across long videos, adds supplied caption text when available, and sends only that lightweight sketch for one generation that returns five editable titles and one editable description. The result is cached for the selected browser file. No media is uploaded merely because it was selected.

## Repair safety

The backend, not the model or browser, owns repairability and execution. The only M19 operation is an allowlisted `REMOVE_RANGE`. The server validates all original-timeline ranges again, rejects overlaps and whole-video deletion, and invokes FFmpeg with argument arrays rather than a shell. Video and audio are cut together; repaired exports are new MP4/H.264/AAC files and the source is never overwritten.

## Quick start

Prerequisites: Python 3.10+, FFmpeg/FFprobe on `PATH`, and Node.js 22+ with npm.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install './backend[dev]'
cd frontend && npm ci && cd ..
```

Run the network-free deterministic demo:

```sh
./scripts/run_demo.sh
```

It generates a copyright-free 12-second video locally and detects the known black, silence, static-frame, hard-limited-audio, and title findings.

Start the web app in two terminals:

```sh
.venv/bin/uvicorn creator_preflight.api:app --app-dir backend/src --reload --host 127.0.0.1 --port 8000
```

```sh
cd frontend
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to FastAPI on `127.0.0.1:8000`.

Click **Load demo** for the tracked three-minute, 720p official judge package. It loads the sample video, thumbnail, captions, title, and description into the same form and scan workflow as creator-selected files. The package is intentionally small enough to clone and run without media generation tools. Its deterministic evidence is a brief black flash near `00:46`, a repairable black export gap near `01:18–01:22`, and an audio dropout near `02:06–02:12`. See [the demo guide](docs/DEMO.md).

### Optional Full Review

```sh
.venv/bin/python -m pip install './backend[ai]'
export GEMINI_API_KEY="your-server-side-key"
.venv/bin/uvicorn creator_preflight.api:app --app-dir backend/src --reload --host 127.0.0.1 --port 8000
```

No special YAML profile is needed for browser Full Review. The key remains server-side. Network access to Google's service is required. The verified path uses `google-genai` 2.22.0 and `gemini-3.7-flash`; this does not imply every model, account, codec, or video size is verified.

### Optional local speech coverage

```sh
.venv/bin/python -m pip install './backend[transcription]'
```

Transcription is disabled by default and `local_files_only` prevents an unexpected model download. The `faster-whisper` 1.2.1 `tiny.en` CPU/int8 path was smoke-tested. Initial model acquisition may require a download; inference is local.

## CLI

```sh
.venv/bin/creator-preflight scan path/to/video.mp4 \
  --title "Publishing title" \
  --description "Publishing description" \
  --captions path/to/captions.srt
```

Use `--json` for a machine-readable report and `--config` for an advanced YAML profile. Exit codes are 0 for Ready, 1 for content findings, and 2 for usage/config/runtime failure.

## Architecture

```text
React web app / CLI
        -> shared FastAPI and PreflightScanner contracts
        -> deterministic FFmpeg, package, caption checks
        -> optional local speech analysis
        -> optional shared Gemini session
             -> Opening review
             -> Continuity review
             -> claim extraction and per-claim grounded verification
             -> text-only AI review over trusted report state
        -> typed repair and verification engine

Previous cut + revised cut
        -> deterministic RevisionMapper
        -> optional note correlation
        -> Revision Check report and comparison player
```

Pydantic models form trust boundaries around configuration, reports, provider output, repairs, and verification. React renders the typed report and never recalculates the verdict or invents repairability. See [Architecture](docs/ARCHITECTURE.md), [Specification](docs/SPEC.md), and [Status](docs/STATUS.md).

## Demo and submission

- [Judge demo](docs/DEMO.md) gives a 90 to 120 second product walkthrough.
- [Submission draft](docs/SUBMISSION.md) contains factual Devpost material.
- `frontend/public/demo/creator-preflight-official-demo.mp4` is the portable official judge asset. `scripts/generate_official_demo.py` documents how maintainers can regenerate it; judges do not need that platform-specific generation step.
- `./scripts/run_demo.sh` remains the separate 12-second engineering regression workflow.

## Privacy and limitations

Local Checks stays within the local browser/backend workflow. Full Review temporarily sends the selected video to Gemini; Metadata Assist sends a locally generated lightweight audiovisual sketch instead of the full-resolution source. Both happen only after explicit user action, and remote cleanup is attempted. The server does not permanently store uploaded media. See [SECURITY.md](SECURITY.md) for the exact data flow and local security assumptions.

Detectors surface evidence, not creative intent. AI review may abstain, miss issues, or return approximate timestamps. Factual review checks only a few selected claims and is not whole-video factual certification. Repair Mode supports one narrow removal operation, not general editing. Visual regression sampling is bounded and is not byte-for-byte or full audio-waveform equivalence.

## Tested release stack

The frontend dependency versions are pinned in `package.json` and `package-lock.json`. The release was exercised with Python 3.10, Node.js 22.21.0, FFmpeg/FFprobe 8.1.2, React 19.2.8, Vite 8.2.2, TypeScript 7.0.2, and Vitest 4.1.11. CI repeats backend and frontend validation on Linux with Python 3.11 and Node.js 22.

## License

This repository uses the [Creator Preflight Source-Available Evaluation License](LICENSE). It permits viewing, judging, education, and personal non-commercial evaluation, but it is not an OSI-approved open-source license and does not grant commercial use or redistribution rights.
