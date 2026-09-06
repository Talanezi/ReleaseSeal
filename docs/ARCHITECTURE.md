# Architecture

## Current state

`creator_preflight.media` validates and inspects local media; `creator_preflight.detectors` contains the independent FFmpeg checks; `creator_preflight.rules` parses creator-style chapter lines and validates video/package metadata; `creator_preflight.captions` parses and validates SRT/WebVTT content and performs interval coverage comparisons; `creator_preflight.ai_review` isolates an optional reusable Gemini upload session, structured generation, grounded citation extraction, validation, and cleanup; `creator_preflight.promise_check`, `creator_preflight.viewer_pass`, and `creator_preflight.claim_review` own independent task-specific schemas and policies; `creator_preflight.content_sketch` builds bounded local audiovisual proxies for Metadata Assist; `creator_preflight.release_brief` and `creator_preflight.metadata_assist` own bounded presentation assistance; `creator_preflight.repairs` owns deterministic repair planning and the allowlisted FFmpeg rendering boundary; `creator_preflight.verification` owns repaired-timeline mapping, finding comparison, integrity/regression verification, and Review Reel manifests; and `creator_preflight.engine.PreflightScanner` coordinates one complete scan.

The scanner reconciles redundant black-contained freeze findings, sorts final findings deterministically, records every executed check, derives counts, and computes `READY`, `NEEDS_REVIEW`, or `BLOCKED` directly from creator-content finding statuses. Report schema 1.8 separately records `COMPLETE`, `PARTIAL`, or `FAILED` scan completeness and typed execution issues, plus a backend-generated repair plan and AI review brief; provider/tool availability failures do not masquerade as content findings. Caption checks are added only when a caption file is supplied, while the speech-coverage check is added only when optional transcription is enabled and audio exists. The report contains no opaque score. Both `creator_preflight.cli` and the FastAPI unified upload endpoint call this same scanner.

## Target shape

Creator Preflight is a local, single-application system with two adapters around one Python scanning engine:

```text
CLI adapter ───────┐
                   ├── shared scanning engine ── FFprobe / FFmpeg
FastAPI adapter ───┘             │
       ▲                         └── validated YAML configuration
       │
React web UI
```

When explicitly enabled, the engine also calls one optional provider boundary:

```text
PreflightScanner ── shared Gemini upload session ── Files/API adapter
       │                 ├── Promise Check trust boundary
       │                 ├── Final Viewer Pass trust boundary
       │                 └── Claim extraction → one grounded request per selected claim
       └── deterministic       └── validated summaries + review-only findings
```

The Gemini API key exists only in the backend process environment. AI-disabled scans never invoke the provider. Provider failure becomes a non-blocking typed execution issue and task-level unavailable state, makes scan completeness partial, and cannot alter the content verdict or erase deterministic results.

The scanning engine owns input normalization, detector orchestration, finding normalization, deterministic status aggregation, and report serialization. Adapters translate CLI arguments or local HTTP request data into the same engine input and must not duplicate scan rules.

## Repository layout

```text
backend/                 Python package and backend tests
  src/creator_preflight/ Installable package namespace
  tests/                 pytest suite
frontend/                React and TypeScript client
config/                  Versioned default configuration
docs/                    Product, architecture, and status documents
scripts/                 Repository automation scripts
```

## Planned backend boundaries

- `creator_preflight.engine`: application-neutral scan orchestration and report aggregation.
- `creator_preflight.models`: input, configuration, finding, and report types.
- `creator_preflight.detectors`: focused media and metadata checks that return normalized findings.
- `creator_preflight.media`: subprocess boundary for FFmpeg and FFprobe.
- `creator_preflight.api`: thin FastAPI adapter.
- `creator_preflight.cli`: thin command-line adapter.
- `creator_preflight.captions`: deterministic caption parsing, validation, coverage, and speech/caption interval comparison.
- `creator_preflight.transcription`: optional lazy local faster-whisper adapter.
- `creator_preflight.ai_review`: optional Gemini SDK adapter, bounded remote file lifecycle, native structured-output validation, and observation normalization boundary.
- `creator_preflight.promise_check`: injection-resistant task prompt, typed Promise result, timestamp validation, confidence/evidence gating, and narrow editorial finding normalization.
- `creator_preflight.viewer_pass`: injection-resistant final-viewer prompt, typed internal-consistency result, timestamp validation, conservative confidence/evidence gating, and narrow review-only finding normalization.
- `creator_preflight.claim_review`: max-three claim extraction, one bounded corrective timestamp retry, per-claim Google Search-grounded verification, claim-specific provider-metadata citations, confidence gating, and cautious review-only conflict findings.
- `creator_preflight.release_models` / `release_brief`: strict presentation schema, deterministic local summary, and optional text-only Full Review summary over trusted report facts.
- `creator_preflight.metadata_assist`: explicit one-upload/one-generation title and description assistance with strict bounded output and no fabricated links.
- `creator_preflight.claim_fixture`: small local narrated control with supported, conflicting, and subjective statements.
- `creator_preflight.viewer_fixture`: small local narrated controls for live clean/conflict/placeholder/repetition validation.
- `creator_preflight.thumbnails`: bounded content-based PNG/JPEG validation for optional temporary thumbnail inputs.
- `creator_preflight.repair_models`: strict repairability, operation, proposal, batch, and plan contracts.
- `creator_preflight.repairs`: deterministic finding-to-proposal mapping, untrusted-operation revalidation, and bounded FFmpeg preview/final rendering.
- `creator_preflight.verification_models`: strict resolved/remaining/new, integrity, unexpected-change, reel-manifest, and overall verification contracts.
- `creator_preflight.verification`: centralized original/repaired timeline transform, backend-owned finding comparison, bounded canonical visual sampling, and Review Reel planning.

The `engine`, `models`, `rules`, `detectors`, `media`, `api`, and `cli` boundaries now exist at the scope required through Milestone 3. Rule and detector logic do not depend on FastAPI, CLI formatting, or React. Adapters translate inputs and render results only. FFmpeg/FFprobe execution uses argument arrays rather than a shell, enforces timeouts, captures diagnostics, and converts tool failures into typed application errors.

Milestone 2 uses one FFmpeg pass per applicable analysis filter. This straightforward sequential design favors reliable parsing and independent testing over premature optimization. Detectors analyze the first selected video or audio stream, matching the primary-stream metadata convention from Milestone 1.

Final finding order is deterministic: blocking findings precede review findings, timestamped findings precede global/package findings within a status, and timestamp/code/message break remaining ties. A freeze is suppressed only when at least 90% of its interval overlaps one detected black interval.

## Data and execution

Metadata Assist is intentionally separate from Full Review. The API inspects the temporary source locally, samples eight four-second windows across long media, and renders a 320×180 H.264/AAC content sketch capped at 32 seconds. Valid supplied caption cues are added as transcript context. Only this lightweight sketch is uploaded for the one metadata generation request, and the browser caches the combined title/description response for the selected `File`.

The web client first reads `/api/v1/capabilities`, then explicitly sends `review_mode=full` or `review_mode=local` with the browser-selected video, title, description, optional captions, and optional thumbnail. Full mode deliberately enables the three Gemini tasks for that request; local mode forcibly disables them. A client-generated opaque UUID associates the existing multipart request with a bounded process-local progress record. The browser polls that record while the scanner reports only real orchestration boundaries; weighted percentages are monotonic, never reach 100 before a terminal report, and carry no invented ETA. Progress state is ephemeral and is cleared after completion or reset. Vite proxies `/api` to FastAPI during local development. The server preserves a recognized video-container suffix, confirms the container with FFprobe, and supplies an explicit bounded MIME type to Gemini. It streams uploads under a configured size limit, executes synchronous scan work in an AnyIO worker thread, bounds process-local scan concurrency, closes uploads, and removes its temporary directory after success or failure. An exact configurable Origin allowlist protects expensive browser POSTs while non-browser clients without an Origin remain supported.

Configuration is loaded from YAML, validated before scanning, and passed explicitly into the engine. Defaults live in `config/preflight.default.yml`. Reports include a schema version so formats can evolve without silent ambiguity.

After the final finding set is reconciled, deterministic application logic builds the report's repair plan. `AI_ACCIDENTAL_REPETITION` can become a safe removal of the validated repeated occurrence, `VIDEO_BLACK_SEGMENT` can become a preview-required removal, and all other current findings remain human-only. No provider call participates in this decision.

The repair endpoints accept only strict JSON-encoded `REMOVE_RANGE` operations alongside a newly uploaded source file. They re-inspect duration, sort and bound the original-timeline ranges, reject overlaps and effectively whole-video removal, and run FFmpeg outside the async event loop under the existing process-local capacity guard. Preview renders only bounded context around one edit. Apply renders all approved compatible ranges once. Both paths use argument arrays, temporary response files with post-response cleanup, and explicit H.264/AAC MP4 encoding; video-only input remains supported. The source is read-only and never overwritten.

After apply, the browser submits the original and repaired files, approved operations, original typed report, publishing package, and selected review mode to `/api/v1/repairs/verify`. The backend revalidates all inputs and reuses `PreflightScanner` for the repaired export. Local repairs remain local; Full Review repairs reuse the established AI mode and completeness semantics. A provider failure can make verification incomplete but cannot erase deterministic integrity/regression evidence or become a new content finding.

`TimelineTransform` is the sole original↔repaired coordinate authority. Finding comparison uses stable codes plus mapped interval overlap; targeted removed intervals receive stronger deterministic evidence, while an absent untargeted AI observation is not treated as proof of resolution. Visual regression samples at a configurable bounded rate, scales frames to 64×36 grayscale, compares mean and changed-pixel differences, excludes configured cut-boundary tolerance, and merges adjacent changed samples. Review Reel planning prioritizes unexpected changes, remaining/new findings, then repair locations; overlaps are merged and segment/total duration limits are enforced before a second narrow endpoint concatenates only server-generated repaired-timeline intervals.

## Status and dependency direction

The overall status order is `READY < NEEDS_REVIEW < BLOCKED`. Aggregation is deterministic and independent of presentation. The dependency direction is adapters → engine → domain models/media boundary; the domain layer never imports an adapter.

The core runtime depends on Python packages, Node build tooling for the frontend, and locally installed FFmpeg/FFprobe. Deterministic scans do not depend on network services at scan time. `faster-whisper` is isolated in the `transcription` optional dependency group, imported lazily, and disabled by default. The default `local_files_only` setting prevents an implicit model download; loaded models are reused within the backend process.

Gemini support is isolated in the `ai` optional dependency group and disabled by default. When enabled, the backend reads `GEMINI_API_KEY`, uploads the video once, polls provider processing within a configured bound, and runs independently enabled tasks against the same remote file before one cleanup. Claim Review adds one schema-constrained video extraction and one text-only Google Search-grounded request for each selected claim, bounded at three; displayed URLs are accepted only from that claim's provider grounding metadata. One extraction correction is allowed only for invalid timestamps, never to invent or clamp evidence. Selected claims without usable evidence are inconclusive rather than clean. One task failure cannot erase another task's valid result; remote identifiers and secrets are not exposed; all AI findings are review-only and cannot produce `BLOCKED`.

Full Review may use one additional text-only structured generation while the shared session is open to phrase a concise AI review from already trusted verdict, finding, interval, and repairability data. It is explicitly instructed to summarize the review rather than the video's subject. Unknown action identifiers are rejected and any failure produces a deterministic fallback without changing content verdict or scan completeness. Local Checks always uses the deterministic brief and makes no provider call. `/api/v1/metadata/assist` is a separate explicit, origin/capacity/upload-limited operation: a bounded local sketch upload yields both five titles and one description, then remote and local cleanup run. The browser caches that paired result only for the currently selected `File` and caption selection.
