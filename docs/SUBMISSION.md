# Devpost draft material

## Inspiration / problem

Creators often discover export mistakes, missing package details, editorial inconsistencies, or an incorrect factual detail only after publishing. Creator Preflight applies the familiar idea of a software linter to the final upload package: inspect the artifact that viewers will actually receive and point directly to evidence worth reviewing.

## What it does

Creator Preflight accepts a finished video, title, description, optional captions, and optional thumbnail. It returns a typed report with a transparent `READY`, `NEEDS_REVIEW`, or `BLOCKED` verdict, exact timestamps, evidence, and suggested review actions. In the web interface, timestamped findings and timeline markers seek the locally selected video.

The report combines deterministic media QC and publishing rules with three optional Gemini review tasks: Opening review, Continuity review, and grounded Claim Review. SRT and WebVTT caption timing and coverage are inspected directly. Optional local Whisper can compare detected speech intervals with caption coverage.

## How it was built

FastAPI and the CLI call the same Python `PreflightScanner`. FFprobe normalizes media metadata; bounded FFmpeg filters detect sustained black, silence, freeze, and suspicious near-full-scale audio density. Pydantic models validate configuration, package inputs, findings, reports, and every AI trust boundary. React and TypeScript render the real API report without recalculating its verdict.

When explicitly enabled, one Gemini Files API upload is shared by Opening review, Continuity review, and claim extraction. Each of at most three selected claims receives its own Google Search-grounded request, preventing citations from one claim being attached to another. Citation links come from provider grounding metadata, not model-authored URLs. Remote cleanup is attempted once after the video tasks.

## Technical highlights

- Deterministic, copyright-free FFmpeg fixtures with known anomaly timestamps.
- One scanner and report contract across CLI, API, and web UI.
- Conservative, review-only AI findings with confidence and evidence gates.
- Task-level failure isolation: provider failure preserves deterministic results.
- Real SRT/WebVTT parsing, merged coverage accounting, and optional local speech-gap comparison.
- Real Gemini video upload, structured output, shared-session orchestration, grounded citations, and cleanup verified on controlled fixtures.
- Backend-owned safe repair proposals, explicit preview/approval, automatic repaired-export verification, and one-player Original/Repaired/Review Reel review.
- A concise AI review over trusted findings, deterministic local fallback, editor exports, and explicit cached title/description assistance generated from a bounded local content sketch rather than the full-resolution master.
- Truthful live progress tied to actual scan boundaries, with elapsed time and calm long-stage reassurance rather than a simulated timer or ETA.
- A portable three-minute 720p creator-style judge package that loads directly in the browser and remains useful even when semantic review conservatively abstains.

## Challenges

The hardest work was calibrating deterministic checks to avoid treating legitimate creative content as corruption, enforcing schema and citation trust boundaries around probabilistic model output, and handling provider timeouts/quota without making deterministic scanning unreliable. AI prompts also needed to distinguish substantive delivery from a title card or superficial mention.

## Accomplishments

Creator Preflight grew from a media inspector into an end-to-end release system: Scan, Fix, Verify. Its web workflow combines configurable deterministic checks, isolated multimodal review, click-to-seek evidence, safe typed repair operations, human judgment, regression verification, a Review Reel, and claim-specific provider citations.

The final demonstration keeps the evidence honest: the tracked three-minute creator package shows a brief flash, a repairable black export gap, and an audio dropout. Its opening is a relevant hook rather than a timer-based warning, and the workflow proceeds through preview, repair, verification, human review, and Review Reel. Focused controlled fixtures remain the separately verified Continuity and grounded Claim Review proofs; no single video is presented as proof of every subsystem.

## Built during the hackathon

The repository contains the media inspection and detector core, report/rule engine, CLI and FastAPI surfaces, React interface, caption and optional transcription systems, Gemini provider boundary and review tasks, deterministic fixture generators, automated tests, and demo documentation.

## Limitations

Detectors identify evidence, not creative intent. Gemini observations and claim verification can abstain, miss issues, or return approximate timestamps. Claim Review checks at most three selected public claims and does not certify the entire video. Search coverage and source quality vary. Initial Whisper model acquisition and Gemini review require network access; Gemini also requires the creator to opt in and provide a server-side API key.

## Future work

Possible next steps include broader real-world evaluation, provider observability, saved local reports, and more accessible evidence comparison. These are not implemented in the hackathon release.
