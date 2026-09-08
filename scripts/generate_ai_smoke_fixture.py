#!/usr/bin/env python3
"""Generate the small local video used for explicit Gemini smoke validation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from releaseseal.ai_smoke_fixture import generate_ai_smoke_video  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "demo" / "generated" / "gemini-video-smoke.mp4",
    )
    args = parser.parse_args()
    print(generate_ai_smoke_video(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
