# Public deployment

ReleaseSeal uses two separately deployed surfaces:

- GitHub Pages serves the complete React application at `https://talanezi.github.io/ReleaseSeal/` and static Judge Proof at `https://talanezi.github.io/ReleaseSeal/proof/`.
- Render serves the FastAPI application. User uploads are processed in bounded temporary directories and are not persisted by ReleaseSeal.

## Render Web Service

Use Render's native Python runtime from the repository root.

Build command:

```sh
pip install './backend[ai]'
```

Start command:

```sh
uvicorn releaseseal.api:app --app-dir backend/src --host 0.0.0.0 --port $PORT
```

Health-check path: `/api/v1/capabilities`.

Environment variables:

- `RELEASESEAL_CONFIG=config/releaseseal.hosted.yml`
- `GEMINI_API_KEY=<server-side key>` for Full Review and existing Gemini assistance; omit it for deterministic-only service behavior.

The hosted configuration limits videos to 262,144,000 bytes (250 MiB), permits one concurrent expensive scan, and accepts browser requests only from `http://localhost:5173`, `http://127.0.0.1:5173`, and `https://talanezi.github.io`. FFmpeg/FFprobe must be available on Render's runtime `PATH`. No database or persistent disk is required.

## GitHub Pages

Create this non-secret Actions repository variable:

```text
RELEASESEAL_API_BASE_URL=https://YOUR-RENDER-SERVICE.onrender.com
```

The Pages workflow refuses to deploy without it. It passes the value to Vite as `VITE_API_BASE_URL`, builds in `github-pages` mode with the `/ReleaseSeal/` base, and publishes `frontend/dist`. Do not place `GEMINI_API_KEY` or any secret in a `VITE_*` value.

Enable GitHub Pages with **Source: GitHub Actions**, then trigger the workflow manually or push to `main`. The normal local build retains `/` and relative API paths; `npm run build -- --mode github-pages` is the deploy-specific build.
