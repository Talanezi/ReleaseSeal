# Final owner QA

Run this once with the intended recording machine and owner-owned demo package.

## Startup

- Start FastAPI and Vite using the README commands.
- Open `/api/v1/capabilities`; confirm local tools and intended review modes are available without exposing a key.
- Confirm the browser has no console errors.

## Final Export

- Load the owner demo if installed; otherwise confirm the fallback demo loads.
- Run Local Checks and verify truthful progress, findings, counts, timeline markers, and click-to-seek.
- If showing Full Review, confirm the key is server-side and each review summary matches accepted findings.
- Preview and approve the black-gap repair; compare original/repaired context.
- Apply; confirm new MP4 playback/download, transformed captions, automatic re-scan, and no false caption-duration warning.
- Inspect verification categories, Review Reel, and CSV/Markdown/JSON downloads.

## Revision

- Load Previous, Revised, and notes (the demo action appears only with a valid owner manifest).
- Compare; inspect unchanged percentage, three requested areas, no-change/needs-location behavior if present, and one additional change.
- Seek Previous/Revised evidence from request rows and timeline strips.
- Expand technical details with keyboard and pointer; confirm readable wrapping.
- If enabled, run semantic review and confirm the bounded-clip privacy copy, conservative status, and exports.

## Responsive and accessibility

- Inspect at 1440, 1024, 768, and 430 CSS pixels with no page-level horizontal overflow.
- At 430px confirm file rows, summaries, players, strips, buttons, and exports remain usable.
- Tab through workflow, file, disclosure, player, finding, repair, and semantic controls; confirm focus is visible and icon-only controls have names.
- Confirm status is communicated by words as well as color.

## Failure paths

- New scan/comparison clears stale files, decisions, repairs, and object URLs.
- Cancel an active operation.
- Stop the backend and confirm workflow-specific safe error copy.
- Run local mode without Gemini; then test unavailable AI without losing deterministic results.
- Confirm a semantic source-hash mismatch instructs the user to compare again.

## Release

- Run `./scripts/verify_release.sh`.
- Confirm CI is green, documentation links work, no secrets/media artifacts are staged, and recording assets are owner-authorized.
