# Judge demo

The demonstration tells one release-assurance story through two real workflows. It does not rely on precomputed reports or force probabilistic AI to return a preferred conclusion.

## Demo assets

### Primary attributed demo

Place one authorized 90–240 second video with normal motion, speech, and audio at:

`.demo/owner/source.mp4`

User-owned footage remains the default:

```sh
.venv/bin/python scripts/build_owner_demo.py .demo/owner/source.mp4
```

For public-domain footage, record its title, credit, and official source URL explicitly:

```sh
.venv/bin/python scripts/build_owner_demo.py .demo/owner/source.mp4 \
  --thumbnail .demo/owner/thumbnail.jpg \
  --source-type public_domain \
  --source-credit "U.S. Geological Survey" \
  --source-title "Before the supereruptions: Yellowstone’s ancient volcanoes" \
  --source-url "https://www.usgs.gov/media/videos/supereruptions-yellowstones-ancient-volcanoes-yellowstone-monthly-update-august-2026"
```

Outputs under `frontend/public/demo/owner/`:

- `final-export-demo.mp4`, title, and description (plus optional owner-supplied captions/thumbnail)
- `revision-previous.mp4`
- `revision-revised.mp4`
- `revision-notes.txt`
- `demo-manifest.json` with source/generated hashes, seeded operations, explicit video and supplied-thumbnail provenance, modification flags, generator/schema versions, and generation time

Supply optional captions and thumbnail with `--captions` and `--thumbnail`. Captions must already describe the owner source; the builder does not invent text. Generated media stays ignored and is not a repository dependency.

### Tracked fallback

When no owner manifest exists, **Load demo** in Final Export uses the tracked copyright-free package. Revision deliberately shows no broken demo button. The fallback contains:

| Evidence | Expected interval |
|---|---:|
| Brief black flash | about `00:46.00–00:46.21` |
| Repairable black gap | about `01:18.04–01:22.04` |
| Audio dropout | about `02:06.03–02:12.01` |

`./scripts/run_demo.sh` is a separate 12-second engineering regression fixture, not an authentic judge video.

## What the owner builder seeds

Final Export retains the natural source except for a black gap at 24–27 seconds and an audio dropout at 54–59 seconds.

Revision uses one normalized, clean source as the Revised cut. The Previous cut
keeps the authentic source footage and timeline while adding only three plausible
version differences:

1. missing picture at 24–27 seconds, requested as “Restore the missing picture”;
2. missing audio at 54–59 seconds, requested as “Restore the missing audio”;
3. one unmentioned moderate exposure difference at 70–74 seconds.

No synthetic cards, slides, or replacement graphics are introduced. The notes
list only the first two changes. The backend must actually compare the files; the
manifest is provenance, not a result.

## Recommended 120-second walkthrough

1. **0:00–0:15 — set the problem.** “I finished a video. Before it ships, I want evidence that the export is sound—and when an editor sends V2, I want to know what actually changed.” Show the two workflow choices.
2. **0:15–0:40 — Final Export.** Load the owner demo (or fallback), run Local Checks or Full Review, open the timestamped black gap, and seek directly to it.
3. **0:40–1:02 — repair and verify.** Preview the bounded removal, approve it, apply once, and show automatic re-scan plus deterministic unexpected-change protection.
4. **1:02–1:34 — Revision.** Load Previous/Revised/notes, compare, and show the high unchanged percentage, two requested physical changes, and the additional unmentioned exposure change.
5. **1:34–1:52 — interpretation boundary.** For one eligible request, optionally send only short Previous/Revised clips. Whatever truthful status returns—Appears satisfied, Appears unresolved, or Inconclusive—keep the physical map visibly authoritative.
6. **1:52–2:00 — close.** “Release assurance for creative work: inspect the artifact, point to evidence, and verify the change.”

## What is deterministic and what is optional

- Deterministic: stream inspection, anomalies, captions/package rules, repair rendering, repaired regression checks, revision alignment, note correlation, and additional physical changes.
- Optional AI: opening/continuity/selected grounded-claim interpretation and bounded semantic interpretation of eligible revision clips.
- Human: ambiguous creative judgment and final approval.

Do not claim exhaustive error detection, semantic certification, guaranteed cleanup, or that physical change proves a revision request was satisfied.

## Recording checklist

- Use a clean browser at normal zoom and an appropriate capture resolution.
- Start backend/frontend before recording; keep the developer console hidden.
- Load the Gemini key server-side only if optional review will be shown.
- Confirm owner demo files or the fallback loader before recording.
- Use a stable network only for the explicit semantic action.
- Disable unrelated desktop notifications.
- Rehearse where deterministic evidence appears; never hardcode or fake AI output.

## Screenshot plan

1. Final Export with a concrete finding and Action Queue.
2. Repair verification showing the target resolved and no deterministic unexpected changes.
3. Revision showing unchanged percentage, requested changes, and one additional change.
4. Semantic review showing **Change detected** separately from **Appears satisfied** or **Inconclusive**.
