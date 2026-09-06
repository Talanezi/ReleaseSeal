#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON=${PYTHON:-python3}
fi

echo "[1/5] Backend tests"
"$PYTHON" -m pytest backend/tests

echo "[2/5] Frontend tests"
(cd frontend && npm test -- --run)

echo "[3/5] Frontend TypeScript and production build"
(cd frontend && npm run build)

echo "[4/5] Python compile/import sanity"
"$PYTHON" -m compileall -q backend/src scripts
PYTHONPATH="$ROOT/backend/src" "$PYTHON" -c 'import creator_preflight'

echo "[5/5] Patch whitespace check"
git diff --check

echo "Release verification passed (network-free; no provider calls)."
