# Competitive Loss Register

This is a skeptical internal release assessment, not a feature roadmap or a claim about any named competitor. It records the strongest remaining arguments against Creator Preflight after the Milestone 29 hostile audit.

## Remaining loss arguments

| Threat category | Competitor advantage | Current response | Remaining gap | Rubric category | Judge importance | Fixable before deadline | Candidate response |
|---|---|---|---|---|---|---|---|
| Specialist thumbnail verification | Deeper visual attention, text-legibility, and composition analysis | Bounded file, geometry, aspect, delivery-surface, badge, safe-area, and explicit critical-region checks | No OCR, inferred critical regions, saliency, or automated text-contrast evidence | Functionality; usefulness | HIGH | YES, if isolated | M30 may add narrowly validated thumbnail assurance without changing package or receipt contracts |
| Contract and sponsor verification | Speech-first evidence can check obligations when captions are absent or inaccurate | Strict typed contract, deterministic metadata/media/caption rules, advisory bounded semantics, and artifact-bound receipt | Deterministic spoken-text checks depend on supplied valid captions; semantic evidence remains intentionally advisory | Functionality; usefulness | HIGH | PARTIAL | A later isolated evidence-source improvement could add an explicitly labeled transcript source; do not weaken deterministic trust policy |
| Autonomous editing and generation | More edits can be completed without leaving the tool | Previewable, approved, deterministic `REMOVE_RANGE`, caption retiming, and automatic re-scan | Most editorial, factual, graphic, audio, and metadata findings correctly remain human-only | Creativity; usefulness | MEDIUM | NO | M31 should expand repair only where a deterministic operation and verification contract are defensible |
| Polished creator workflow tools | Hosted access, persistent projects, collaboration, and integrations reduce setup | Clear local Final Export and Revision workflows plus portable static Judge Proof Mode | Arbitrary-file use still requires local Python, FFmpeg, and optional Gemini configuration; sessions are not persistent | Usefulness; functionality | HIGH | NO | Keep proof mode for evaluation; consider packaging/hosting only after core trust boundaries remain frozen |

## Skeptical rubric audit

| Official category | Strongest repository evidence | Biggest remaining weakness | Plausible superior argument elsewhere? |
|---|---|---|---|
| Functionality — 30% | Real Scan → Fix → Verify; contract-gated Final Export; deterministic Revision mapping; package verification; receipts; self-checking proof fixtures | Limited safe repair vocabulary and caption-dependent deterministic spoken-text evidence | Yes. A narrower specialist can plausibly be deeper at one task, especially thumbnail review or automated editing |
| Technical Execution — 30% | Strict Pydantic/TypeScript boundaries, bounded FFmpeg/provider execution, cleanup, shared uploads, canonical artifact identities, hostile mutation tests, and deterministic self-verification | Local synchronous jobs are bounded rather than distributed; probabilistic review remains provider-dependent | Less plausibly on breadth of trust boundaries, but a production-hosted system can argue stronger operational maturity |
| Creativity — 20% | Combines rendered-media QC, stakeholder obligations, safe repairs, revision evidence, and artifact-bound release identity as one assurance workflow | The product deliberately avoids generative repair breadth and predictive scoring | Yes. Generative editors can look more immediately spectacular even when their release guarantees are weaker |
| Real-World Usefulness — 20% | Exact timestamps, click-to-seek, human dispositions, handoff exports, authentic public-domain demo, and neutral failure semantics | Setup friction, no persistent history/collaboration, and no direct NLE/publishing integration | Yes. Mature workflow products can make adoption easier even with less rigorous verification |

## Freeze implication

M30 thumbnail assurance remains justified because thumbnail review is the clearest high-importance specialist gap that can be added behind an isolated boundary. The higher-value alternative is improving trustworthy transcript evidence for Release Contract checks, but that touches a more sensitive trust boundary and should not displace the planned isolated thumbnail work without an explicit milestone decision.

The scanner contracts, repair verifier, Release Contract trust policy, receipt canonicalization, RevisionMapper, and Judge Proof provenance are core-frozen after M29. Later work may consume or extend their public typed boundaries, but must not casually refactor or weaken them.
