# Scripts

- `generate_demo_fixture.py` creates the deterministic, copyright-free 12-second engineering regression video.
- `run_demo.sh` generates that video and scans it with the tracked demo title, description, and SRT package.
- `generate_promise_fixture.py` creates the ignored 36-second semantic Promise Check video and aligned PNG thumbnail used for local Gemini validation.
- `generate_viewer_fixture.py` creates ignored clean and deliberately inconsistent narrated Final Viewer Pass videos. It uses FFmpeg plus the local macOS `say` command; automated tests do not depend on that platform-specific speech generator.
- `generate_claim_fixture.py` is optional maintainer tooling that creates the ignored 36-second narrated Claim Review fixture with one supported fact, one conflicting date, and one subjective statement. Its real narration path uses FFmpeg plus the local macOS `say` command. Automated tests inject portable deterministic FFmpeg audio to validate media assembly and do not claim to validate spoken English or require macOS speech synthesis.

Run both from the repository root. See the root `README.md` and `demo/README.md` for prerequisites, exact commands, and expected findings.

- `generate_official_demo.py` is the maintainer-only regeneration path for the deliberately tracked three-minute judge asset. Judges use **Load demo** in the browser and do not need macOS `say`; only regeneration currently requires it.
