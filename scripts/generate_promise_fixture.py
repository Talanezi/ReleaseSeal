#!/usr/bin/env python3
"""Generate the local Promise Check video and aligned thumbnail."""

from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from releaseseal.promise_fixture import generate_promise_fixture  # noqa: E402


def main() -> None:
    root = REPOSITORY_ROOT
    video, thumbnail = generate_promise_fixture(
        root / "demo" / "generated" / "promise-check.mp4",
        root / "demo" / "generated" / "promise-check-thumbnail.png",
    )
    print(f"Generated {video.relative_to(root)}")
    print(f"Generated {thumbnail.relative_to(root)}")


if __name__ == "__main__":
    main()
