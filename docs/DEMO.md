# Creator Preflight judge demo

## Official browser demo

Start the backend and frontend with the README Quick Start, open `http://127.0.0.1:5173`, and click **Load demo**. The browser loads one deliberately tracked, copyright-free package through the normal product form:

- video: `frontend/public/demo/creator-preflight-official-demo.mp4`
- thumbnail, captions, title, and description: adjacent files with the same `creator-preflight-official-` prefix
- duration: approximately 3:00
- format: 1280×720 H.264/AAC
- story: a narrated, creator-style explainer about the return of European night trains

The tracked binary makes the judge path portable. It does not require macOS speech synthesis, a media download, or fixture generation. Maintainers can regenerate the locally drawn/narrated asset with `.venv/bin/python scripts/generate_official_demo.py`; that optional regeneration command currently uses macOS `say`.

## Expected deterministic evidence

The sample has only three deliberate issues:

| Evidence | Expected interval | Intended workflow |
|---|---:|---|
| Brief black flash candidate | about `00:46.00–00:46.21` | review evidence; no automatic repair |
| Sustained black export gap | about `01:18.04–01:22.04` | preview and approve the backend-owned removal |
| Sustained audio dropout | about `02:06.03–02:12.01` | human judgment; no fabricated audio repair |

The opening is a relevant hook that immediately establishes the title's value. Full Review should treat direct-delivery timing as informational rather than applying a fixed timer. Semantic checks may conservatively abstain; the deterministic repair story remains complete without forcing a probabilistic finding.

## Recommended 90–120 second sequence

1. **0–10s — problem.** “A finished upload can still hide an export gap, a dropped track, or an editorial detail that is painful to discover after publishing.”
2. **10–20s — load.** Click **Load demo**. Briefly show that video, title, description, captions, and thumbnail are already present.
3. **20–35s — check.** Choose Full Review when credentials are configured, then show truthful stage progress, elapsed time, and the optional **What’s happening?** disclosure.
4. **35–52s — understand.** Read the compact AI review. In the Action Queue, click the black export gap and show the main player seeking to `01:18`.
5. **52–70s — fix.** Preview the black removal, compare Original and Proposed repair, approve it, and apply the new export.
6. **70–88s — verify.** Show the automatic repaired scan, no unintended changes, and the Original/Repaired/Review Reel choices in the same player. The Review Reel should be substantially shorter than the three-minute source.
7. **88–102s — judgment.** Use **Review next** on the audio dropout, mark a session-local decision, and point out that acceptance is not mislabeled as an automated resolution.
8. **102–115s — proof and close.** Briefly mention the separately verified controlled Continuity example (narration/graphic conflict, placeholder, repetition) and Claim Review example (Apollo 11/1968 at 12s with provider citations). End with: “Scan. Fix. Verify.”

## Separate engineering fixture

`./scripts/run_demo.sh` generates the 12-second anomaly fixture with black at 2–5s, silence at 3–6s, freeze at 7–10s, hard-limited audio, and a title warning. It is intentionally fast and synthetic for regression work. It is not the official judge video and should not be presented as the creator-style demo.
