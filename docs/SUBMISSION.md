# Submission draft

## Inspiration

Creation tools increasingly automate making media, but somebody still has to prove the finished artifact is safe to release. Export defects, stale graphics, caption drift, and unintended revision changes are easiest to fix before an audience or client receives the file.

## What it does

ReleaseSeal provides creative release assurance through two workflows. **Final Export** reviews one finished video, points to exact technical and editorial evidence, offers only safe allowlisted repair proposals, renders a new file after approval, and rechecks that export for regressions. **Revision** compares Previous and Revised cuts, aligns their timelines through insertions and removals, correlates revision notes, and exposes additional physical changes that were not mentioned.

Local deterministic checks cover media structure, black/silence/freeze evidence, audio conditions, publishing-package rules, captions, physical version changes, repair execution, and regression comparison. Optional Gemini review interprets opening alignment, continuity evidence, selected grounded claims, and—only when requested—short revision evidence clips. Ambiguous creative decisions remain human judgments.

## How we built it

FastAPI and the CLI share typed Python services. FFprobe normalizes streams; bounded FFmpeg processes extract detector evidence, render repairs, sample repaired regressions, align revision fingerprints, and create short semantic evidence clips. Strict Pydantic models form trust boundaries around reports, provider responses, repairs, timeline maps, and semantic results. React/TypeScript renders those backend decisions and uses numeric timestamps for seeking.

The deterministic revision mapper performs monotonic temporal alignment and remains usable without Gemini. For an eligible timestamped request, optional semantic review verifies source hashes, renders at most two 12-second 320×180 clips, uploads only those clips, validates structured output, and attempts provider cleanup. It never changes the physical map.

## Technical highlights

- Bounded FFmpeg/FFprobe execution without shell commands.
- Shared video/caption timeline transform for non-destructive removals.
- Repaired-export comparison that separates probabilistic finding variance from deterministic unexpected media change.
- Monotonic version alignment tolerant of ordinary re-encoding and downstream realignment after edits.
- Deterministic note/change correlation with stable insertion anchors and unmentioned-change reporting.
- Hash-bound, bounded semantic evidence clips with per-request failure isolation and cleanup.
- Explicit trust hierarchy: deterministic evidence, optional interpretation, human approval.
- Linux CI plus a one-command network-free release gate.

## Challenges

The hard part was not producing more warnings; it was preserving meaning. A black frame may be intentional, a provider may vary, and physical change does not prove a note was satisfied. The architecture therefore separates content verdict from execution completeness, AI variance from deterministic regression, and physical revision evidence from semantic interpretation.

## Accomplishments

The project now supports a complete Scan → Fix → Verify loop for one finished export and a first-class Previous → Revised comparison. It can perform narrow repairs without overwriting the source, transform caption timelines through cuts, re-scan the output, detect unrelated deterministic mutations, map multi-edit revisions without cascading false changes, and optionally interpret only bounded evidence around requested revisions.

## What we learned

Trust comes from bounded claims and reproducible evidence. Provider output is most useful when it is schema-validated and subordinate to deterministic facts. Real creator workflows also need neutral abstention states: “inconclusive” is more honest than fabricated certainty.

## Built with

Python, FastAPI, Pydantic, FFmpeg/FFprobe, React, TypeScript, Vite, Vitest, pytest, optional `google-genai`, and optional `faster-whisper`.

## Limitations

Semantic review is probabilistic and bounded to eligible timestamped requests. Untimed notes are not located automatically. Arbitrary scene reordering is unsupported; static or repetitive content can reduce boundary precision. Repair Mode is deliberately limited to validated range removal. Factual review checks only selected public claims. The public deployment is a stateless hackathon service; there is no project history, collaboration, persistent media storage, or automatic publishing.

## Future work

Potential directions include untimed revision-note localization, broader evaluation on professional edit histories, NLE marker handoff, client delivery requirements, additional provably safe repair classes, and persistent team workflows. None is implemented in this release.
