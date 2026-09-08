#!/usr/bin/env python3
"""Generate the paired, ignored final judge-demo media package."""

from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from releaseseal.judge_fixture import generate_judge_demo  # noqa: E402


def main() -> int:
    try:
        defective, corrected, thumbnail = generate_judge_demo(
            REPOSITORY_ROOT / "demo" / "generated" / "judge"
        )
    except RuntimeError as exc:
        print(f"prepare-judge-demo: {exc}", file=sys.stderr)
        return 1
    print("Judge demo package generated:")
    for path in (defective, corrected, thumbnail):
        print(f"  {path.relative_to(REPOSITORY_ROOT)}")
    print("  demo/judge/title.txt")
    print("  demo/judge/description.txt")
    print("  demo/judge/captions-defective.srt")
    print("  demo/judge/captions-corrected.srt")
    print("  demo/judge/ai-config.yml")
    print("See docs/DEMO.md for the backend, frontend, and recording sequence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
