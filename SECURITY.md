# Security and privacy

Creator Preflight is designed as a local, single-user application. It does not provide accounts, tenant isolation, or an internet-facing deployment security model.

## Data flow

**Local Checks Only** sends the selected files to the local FastAPI process. Media is analyzed with local FFmpeg/FFprobe and is not uploaded to Gemini. **Revision Check** likewise compares the full Previous and Revised files locally and needs no Gemini key.

**Full Review and Metadata Assist** are explicit actions. Full Review may temporarily upload the selected video and thumbnail to Google's Gemini service. Metadata Assist uploads a bounded 32-second, 320×180 audiovisual sketch generated locally from the selected video and may include supplied caption text.

**Optional semantic Revision review** occurs only after a deterministic comparison and another explicit action. The backend validates the submitted source hashes and uploads only bounded Previous/Revised evidence clips for eligible timestamped requests. It does not provide either whole source cut to Gemini for this step. Evidence clips are capped by configuration (12 seconds and 320×180 by default).

The API key remains in the backend process environment and is never sent to the browser. The backend attempts to delete each remote Gemini file after the request; deletion cannot be guaranteed when cleanup itself fails, and provider retention/processing remain subject to Google's service terms.

The backend stores request media only in per-request temporary directories and removes them after success or failure. Repair previews, repaired exports, and Review Reels are temporary responses retained by the browser, not permanent server media.

## Local safeguards

- Video uploads are streamed to disk and limited to 2 GiB by default.
- Caption and thumbnail byte, format, and dimension limits are enforced separately.
- Expensive browser POST requests require a configured local Origin; command-line clients without an Origin remain supported.
- Process-local concurrency limits bound simultaneous scan and render work.
- FFmpeg and FFprobe use argument arrays, bounded execution, and no shell.
- Repair endpoints accept only typed, allowlisted operations and never arbitrary filter or filesystem commands.

These controls reduce accidental or cross-origin abuse of a local service. They are not authentication and should not be treated as protection for a publicly exposed server. Keep FastAPI bound to localhost unless you add an appropriate production security layer.

## Secrets

Keep `GEMINI_API_KEY` in the backend environment or an ignored local environment file. Never place it in YAML, browser code, screenshots, reports, or commits. `.env*` files are ignored except for the safe `.env.example` template.

## Reporting a vulnerability

Please open a GitHub security advisory for the repository when available. Otherwise, open a minimal issue that describes the affected component without publishing credentials, private media, or exploit details; the maintainer can arrange a private follow-up.
