#!/usr/bin/env python3
"""Generate the deterministic ReleaseSeal demo video."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from releaseseal.demo_fixture import generate_demo_video  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the 12-second deterministic ReleaseSeal demo video."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "demo" / "generated" / "releaseseal-demo.mp4",
    )
    args = parser.parse_args()
    try:
        path = generate_demo_video(args.output)
    except RuntimeError as exc:
        print(f"generate-demo: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
