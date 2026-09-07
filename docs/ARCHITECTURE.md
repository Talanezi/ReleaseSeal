# Architecture

## Release workflows

```text
FINAL EXPORT
Finished package
  -> deterministic technical/package/caption checks
  -> optional bounded content review
  -> evidence + human judgment
  -> allowlisted repair
  -> repaired export
  -> re-scan + deterministic regression verification

REVISION
Previous cut + Revised cut + optional notes
  -> deterministic temporal alignment
  -> physical change map
  -> requested-area correlation + additional changes
  -> optional hash-bound semantic review of short evidence clips
```

These workflows share validation, local media tooling, safe adapters, and presentation conventions but not conclusions. The Final Export scanner owns a content verdict. Revision deliberately has no global pass/fail verdict: its deterministic map states where media changed, and its separate optional semantic layer states only what short evidence appears to show.

## Current state

`creator_preflight.media` validates and inspects local media; `creator_preflight.detectors` contains the independent FFmpeg checks; `creator_preflight.rules` parses creator-style chapter lines and validates video/package metadata; `creator_preflight.release_package` builds the backend-owned package summary and basic thumbnail delivery geometry from that validated state; `creator_preflight.thumbnail_assurance` adds an isolated bounded pixel-analysis report behind that package boundary; `creator_preflight.captions` parses and validates SRT/WebVTT content and performs interval coverage comparisons; `creator_preflight.ai_review` isolates optional Gemini lifecycle primitives; `creator_preflight.promise_check`, `creator_preflight.viewer_pass`, and `creator_preflight.claim_review` own independent final-export AI policies; `creator_preflight.content_sketch` builds bounded local audiovisual proxies for Metadata Assist; `creator_preflight.release_brief` and `creator_preflight.metadata_assist` own bounded presentation assistance; `creator_preflight.release_contract` owns strict obligation types, trusted-state evaluation, semantic validation, and gate findings; `creator_preflight.release_contract_extraction` structures only obligations grounded to pasted brief excerpts; `creator_preflight.repairs` owns deterministic repair planning and the allowlisted FFmpeg rendering boundary; `creator_preflight.verification` owns repaired-timeline mapping, finding comparison, integrity/regression verification, and Review Reel manifests; `creator_preflight.revision` owns application-neutral physical timeline alignment; `creator_preflight.revision_check` owns deterministic revision-note parsing and correlation; `creator_preflight.revision_evidence` owns bounded Previous/Revised evidence planning and transcoding; `creator_preflight.revision_semantic` owns the focused optional semantic reviewer protocol, Gemini implementation, hash validation, request limits, and failure isolation; and `creator_preflight.engine.PreflightScanner` coordinates one complete final-export scan.

The scanner reconciles redundant black-contained freeze findings, sorts final findings deterministically, records every executed check, derives counts, and computes `READY`, `NEEDS_REVIEW`, or `BLOCKED` directly from creator-content finding statuses. Report schema 1.10 separately records `COMPLETE`, `PARTIAL`, or `FAILED` scan completeness and typed execution issues, plus backend-generated release-package, repair, Release Contract, and review-summary state; provider/tool availability failures do not masquerade as content findings. Caption checks are added only when a caption file is supplied, while the speech-coverage check is added only when optional transcription is enabled and audio exists. The report contains no opaque score. Both `creator_preflight.cli` and the FastAPI unified upload endpoint call this same scanner.

The M27 package evaluator never invents missing requirements: absent optional thumbnail, captions, chapters, or contract state is neutral unless an existing rule or Release Contract says otherwise. Supplied PNG/JPEG files reuse the bounded content decoder and receive minimum-resolution, relative 16:9, and file-size checks. Four centralized typed delivery surfaces provide approximate box, edge, and duration-badge geometry; preview metadata uses the probed video duration. Explicit normalized critical regions can be tested against badge/edge geometry, but no region is inferred and no OCR, saliency, learned vision, or quality score exists.

M30 preserves that boundary. Only an M27-validated image enters `ThumbnailAssuranceService`, which asks FFmpeg for one aspect-preserving RGB analysis plane capped at 320px. An independently implemented row-gradient/stroke-run detector consolidates likely text lines and retains at most twelve regions. Region detection and percentile-based foreground/background contrast estimation are advisory; source-to-delivery height scaling is a measured geometry conditional on that region. Existing surface rectangles drive badge and edge intersections. Bilinear downscale/reconstruction supplies an advisory structural-detail-retention ratio, not a quality score. The calibrated defaults are confidence 0.72, delivered text height 8px, estimated local contrast 2.5:1, and detail retention 0.72. They separate controlled large/tiny/low-contrast cases but do not claim universal human readability or accessibility conformance. No provider, OCR, learned model, face detector, randomness, or saliency pass is involved.

M28 adds no scanner capability. `JudgeProofBundle` is a strict, versioned read model built only by `scripts/build_judge_proof.py`. The generator compacts the attributed USGS owner-demo media, then invokes the production `PreflightScanner`, repair renderer, repaired-export verifier, Release Contract evaluator, `RevisionCheckService`, receipt builders, and `ReceiptVerifier`. It serializes those typed outputs plus content-addressed relative asset references under `frontend/public/proof/`. The companion verifier parses the same strict schema, hashes every referenced asset, reruns exact-artifact receipt checks (including a temporary one-byte mutation), and rejects any bundle that loses its required observed conditions.

The frontend has a separate static Vite entry at `proof/index.html`. It fetches and renders the authoritative bundle and performs no scan, verdict, repair, contract, revision, or receipt logic. Both entry HTML and proof assets are emitted by a normal production build, so viewing proof requires neither FastAPI nor a provider. Regeneration remains a maintainer operation requiring local production dependencies and the ignored attributed owner-demo inputs. The page visibly labels results as precomputed engine evidence.

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
- `creator_preflight.revision_models`: strict, serializable media-to-media timeline correspondence contracts (`UNCHANGED`, `REMOVED`, `INSERTED`, and `CHANGED`).
- `creator_preflight.revision`: local deterministic fingerprint extraction, monotonic alignment, bounded boundary refinement, and the application-neutral `RevisionMapper` service.
- `creator_preflight.revision_fixture`: portable FFmpeg-only engineering fixtures for revision-map calibration; it has no network or speech-synthesis dependency.
- `creator_preflight.revision_check_models`: strict request, additional-change, and complete Revision Check response contracts.
- `creator_preflight.revision_check`: deterministic previous-timeline note parsing, insertion-anchor inference, and correlation of notes with `RevisionMap` change segments.
- `creator_preflight.release_receipt`: strict Final Export/Revision receipt models, canonical serialization, package fingerprints, backend construction, streaming SHA-256 identities, and typed verification.

The `engine`, `models`, `rules`, `detectors`, `media`, `api`, and `cli` boundaries now exist at the scope required through Milestone 3. Rule and detector logic do not depend on FastAPI, CLI formatting, or React. Adapters translate inputs and render results only. FFmpeg/FFprobe execution uses argument arrays rather than a shell, enforces timeouts, captures diagnostics, and converts tool failures into typed application errors.

Milestone 2 uses one FFmpeg pass per applicable analysis filter. This straightforward sequential design favors reliable parsing and independent testing over premature optimization. Detectors analyze the first selected video or audio stream, matching the primary-stream metadata convention from Milestone 1.

Final finding order is deterministic: blocking findings precede review findings, timestamped findings precede global/package findings within a status, and timestamp/code/message break remaining ties. A freeze is suppressed only when at least 90% of its interval overlaps one detected black interval.

## Data and execution

Metadata Assist is intentionally separate from Full Review. The API inspects the temporary source locally, samples eight four-second windows across long media, and renders a 320×180 H.264/AAC content sketch capped at 32 seconds. Valid supplied caption cues are added as transcript context. Only this lightweight sketch is uploaded for the one metadata generation request, and the browser caches the combined title/description response for the selected `File`.

The web client first reads `/api/v1/capabilities`, then explicitly sends `review_mode=full` or `review_mode=local` with the browser-selected video, title, description, optional captions, and optional thumbnail. Full mode deliberately enables the three Gemini tasks for that request; local mode forcibly disables them. A client-generated opaque UUID associates the existing multipart request with a bounded process-local progress record. The browser polls that record while the scanner reports only real orchestration boundaries; weighted percentages are monotonic, never reach 100 before a terminal report, and carry no invented ETA. Progress state is ephemeral and is cleared after completion or reset. Vite proxies `/api` to FastAPI during local development. The server preserves a recognized video-container suffix, confirms the container with FFprobe, and supplies an explicit bounded MIME type to Gemini. It streams uploads under a configured size limit, executes synchronous scan work in an AnyIO worker thread, bounds process-local scan concurrency, closes uploads, and removes its temporary directory after success or failure. An exact configurable Origin allowlist protects expensive browser POSTs while non-browser clients without an Origin remain supported.

Configuration is loaded from YAML, validated before scanning, and passed explicitly into the engine. Defaults live in `config/preflight.default.yml`. Reports include a schema version so formats can evolve without silent ambiguity.

An optional Release Contract travels with the publishing package into the same scanner. Its discriminated requirement models forbid unknown fields and arbitrary rules. The evaluator reuses inspected media, parsed captions, and submitted title/description rather than probing again. Deterministic failures create blocking contract findings; semantic concerns create review-only findings, and unavailable evidence leaves typed `NOT_EVALUATED` rows plus partial completeness. Full Review batches at most five semantic requirements into one bounded text-only request over at most 20,000 caption characters inside the existing shared Gemini session, so it performs no additional video upload. Manual contracts remain fully usable without Gemini. Brief extraction is a separate explicit text-only route: provider output must validate against the same contract schema, quote an excerpt that exists in the supplied brief, and preserve literal values before it can reach the editor.

After the final finding set is reconciled, deterministic application logic builds the report's repair plan. `AI_ACCIDENTAL_REPETITION` can become a safe removal of the validated repeated occurrence, `VIDEO_BLACK_SEGMENT` can become a preview-required removal, and all other current findings remain human-only. No provider call participates in this decision.

The repair endpoints accept only strict JSON-encoded `REMOVE_RANGE` operations alongside a newly uploaded source file. They re-inspect duration, sort and bound the original-timeline ranges, reject overlaps and effectively whole-video removal, and run FFmpeg outside the async event loop under the existing process-local capacity guard. Preview renders only bounded context around one edit. Apply renders all approved compatible ranges once. Both paths use argument arrays, temporary response files with post-response cleanup, and explicit H.264/AAC MP4 encoding; video-only input remains supported. The source is read-only and never overwritten.

After apply, the browser submits the original and repaired files, approved operations, original typed report, publishing package, and selected review mode to `/api/v1/repairs/verify`. The backend revalidates all inputs and reuses `PreflightScanner` for the repaired export. Local repairs remain local; Full Review repairs reuse the established AI mode and completeness semantics. A provider failure can make verification incomplete but cannot erase deterministic integrity/regression evidence or become a new content finding.

`TimelineTransform` is the sole original↔repaired coordinate authority. The verification adapter parses supplied SRT/WebVTT cues through the existing caption subsystem, maps every surviving cue through that transform, serializes a request-temporary repaired-timeline caption file, and leaves the original upload unchanged. Finding comparison uses stable codes plus mapped interval overlap; targeted removed intervals receive stronger deterministic evidence, while an absent untargeted AI observation is not treated as proof of resolution. Findings first detected by a probabilistic repaired scan remain neutral finding variance, separate from deterministic unexpected visual changes outside approved edits. Visual regression samples at a configurable bounded rate, scales frames to 64×36 grayscale, compares mean and changed-pixel differences, excludes configured cut-boundary tolerance, and merges adjacent changed samples. Review Reel planning prioritizes unexpected changes, remaining/new findings, then repair locations; overlaps are merged and segment/total duration limits are enforced before a second narrow endpoint concatenates only server-generated repaired-timeline intervals.

The M21 `RevisionMapper` is a separate backend service primitive for comparing two independently produced finished cuts whose edit operations are unknown. It hashes inputs for an identical-file fast path, reuses `MediaInspector`, streams at most the configured number of 17×9 grayscale samples per input, attaches bounded FFmpeg audio-window statistics when both versions contain audio, and aligns the two sequences monotonically with rolling score rows plus byte-sized backpointers. Candidate edit regions alone are resampled at higher frequency within a bounded local budget. The output's unchanged ratio is unchanged duration on the previous timeline divided by previous-version duration. The algorithm is deterministic and local; it makes no Gemini or network request and does not support arbitrary scene reordering.

`RevisionCheckService` is the higher-level M22 product boundary. It accepts optional one-line revision notes whose timecodes refer to the previous cut, parses points and explicit ranges deterministically, and correlates them to the mapper's non-unchanged segments. Point notes use a configurable ±3-second neighborhood; explicit ranges use only a 0.25-second boundary tolerance. Removed and changed segments use direct previous-timeline intervals. Insertions receive a stable previous-timeline anchor inferred from adjacent monotonic segments. Matching is overlap-first, nearest-distance second, and segment identifier third; a segment may account for multiple legitimately overlapping requests. Unmatched change segments remain neutral additional changes. This proves only physical media change near a request, never semantic satisfaction.

`POST /api/v1/revisions/check` streams each of two uploads under the existing per-file limit, preserves safe media suffixes in separate request-temporary paths, applies Origin and process-capacity protection, and runs the synchronous mapper in an AnyIO worker. Cleanup covers both uploads on success and failure. Revision capability depends only on FFmpeg and FFprobe, not Gemini, transcription, or a key. The React client keeps Final Export and Revision as separate form, processing, and result state paths while sharing the existing application shell and canonical timecode formatter.

M23 adds a separate explicit `POST /api/v1/revisions/semantic-review` layer. The client resubmits both files and the strict deterministic report; the backend validates the report and both SHA-256 hashes before selecting only timestamped `CHANGE_DETECTED` requests. Revision-map correspondence produces two temporary H.264 evidence clips per selected request, at most 12 seconds and 320×180 with AAC when audio exists. `CHANGED` uses direct paired regions, `REMOVED` uses the previous region plus its revised cut neighborhood, and `INSERTED` uses the previous insertion anchor plus the revised insertion. Up to five requests run in original note order with provider concurrency capped at two. Each focused Gemini request uploads only its two evidence clips, uses native structured output, deletes both provider files, and returns a separate probabilistic report. Low-confidence conclusions become `INCONCLUSIVE`; one failure becomes `NOT_REVIEWED` without changing any deterministic state. The React UI invokes this only after an explicit action and exports the semantic layer separately.

M26 receipt generation is an explicit post-result backend operation and performs no scan or provider call. The Final Export route hashes the supplied shipping video and optional package files while preserving normalized title, description, and canonical Release Contract digests. Repaired receipts bind the original and repaired video roles, normalized approved operations, repaired re-scan state, and deterministic unexpected-change intervals. Revision receipts bind distinct Previous/Revised roles, canonical notes, deterministic request/additional-change results, and separately labeled advisory semantic results. Missing optional assets use explicit `ABSENT` identities rather than empty or unknown hashes.

Canonical receipt JSON uses UTF-8, sorted object keys, compact separators, JSON-compatible finite numbers, and semantically defined array order. `receipt_content_sha256` covers the entire receipt except that digest field. Package and Revision fingerprints use the same serializer. These hashes detect accidental corruption or mismatched artifacts; they are not signatures, attestations, or protection against an actor who can rewrite the receipt and recompute its digest.

## Status and dependency direction

The overall status order is `READY < NEEDS_REVIEW < BLOCKED`. Aggregation is deterministic and independent of presentation. The dependency direction is adapters → engine → domain models/media boundary; the domain layer never imports an adapter.

The core runtime depends on Python packages, Node build tooling for the frontend, and locally installed FFmpeg/FFprobe. Deterministic scans do not depend on network services at scan time. `faster-whisper` is isolated in the `transcription` optional dependency group, imported lazily, and disabled by default. The default `local_files_only` setting prevents an implicit model download; loaded models are reused within the backend process.

Gemini support is isolated in the `ai` optional dependency group and disabled by default. When enabled, the backend reads `GEMINI_API_KEY`, uploads the video once, polls provider processing within a configured bound, and runs independently enabled tasks against the same remote file before one cleanup. Claim Review adds one schema-constrained video extraction and one text-only Google Search-grounded request for each selected claim, bounded at three; displayed URLs are accepted only from that claim's provider grounding metadata. One extraction correction is allowed only for invalid timestamps, never to invent or clamp evidence. Selected claims without usable evidence are inconclusive rather than clean. One task failure cannot erase another task's valid result; remote identifiers and secrets are not exposed; all AI findings are review-only and cannot produce `BLOCKED`.

Full Review may use one additional text-only structured generation while the shared session is open to phrase a concise AI review from already trusted verdict, finding, interval, and repairability data. It is explicitly instructed to summarize the review rather than the video's subject. Unknown action identifiers are rejected and any failure produces a deterministic fallback without changing content verdict or scan completeness. Local Checks always uses the deterministic brief and makes no provider call. `/api/v1/metadata/assist` is a separate explicit, origin/capacity/upload-limited operation: a bounded local sketch upload yields both five titles and one description, then remote and local cleanup run. The browser caches that paired result only for the currently selected `File` and caption selection.

Creator-facing time references are formatted by backend/frontend canonical formatters as `MM:SS.xx` (or `H:MM:SS.xx` for hour-plus media). Numeric seconds remain in typed reports for computation and seeking, but the AI-review prompt and deterministic repair/verification copy do not expose raw floating-point timestamps. Continuity summary copy is derived only from issues that passed the Viewer trust boundary; rejected provider commentary is not promoted into the consumer report.
