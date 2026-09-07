#!/bin/sh
set -eu

REPOSITORY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$REPOSITORY_ROOT"
PYTHONPATH=backend/src .venv/bin/python scripts/build_judge_proof.py "$@"
PYTHONPATH=backend/src .venv/bin/python scripts/verify_judge_proof.py
