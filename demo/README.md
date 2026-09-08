# Engineering regression package

This package is the fast engineering regression fixture, not the primary judge presentation. It demonstrates real deterministic analysis without downloaded media, accounts, API keys, or optional Whisper. The generated 12-second video contains known black, silent, frozen, and deliberately hard-limited audio intervals.

From the repository root, after completing the backend installation in the main README:

```sh
./scripts/run_demo.sh
```

The command generates `demo/generated/releaseseal-demo.mp4` and scans it with `title.txt`, `description.txt`, and `captions.srt`. The wrapper treats the CLI's expected findings exit code (`1`) as a successful demo run.

Expected findings are black video near 2–5 seconds, silence near 3–6 seconds, a non-black freeze near 7–10 seconds, a global warning for sustained near-full-scale audio sample density, and one title-length recommendation. Captions should parse as four valid cues with 100% merged timeline coverage and no caption findings.

The official creator-style judge package is deliberately tracked under `frontend/public/demo/` and can be loaded from the web UI with **Load demo**. See `docs/DEMO.md`.
