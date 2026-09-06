#!/usr/bin/env python3
"""Regenerate the deliberately tracked official judge demo package."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from creator_preflight.official_demo_fixture import generate_official_demo  # noqa: E402


def main() -> int:
    try:
        paths = generate_official_demo(ROOT / "frontend" / "public" / "demo")
    except RuntimeError as exc:
        print(f"official-demo: {exc}", file=sys.stderr)
        return 1
    print("Official judge demo generated:")
    for path in paths:
        print(f"  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
