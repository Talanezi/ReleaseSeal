#!/usr/bin/env python3
"""Generate clean and problematic Final Viewer Pass validation media."""

from pathlib import Path

from releaseseal.viewer_fixture import generate_viewer_pass_fixture


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "demo" / "generated"
    clean = generate_viewer_pass_fixture(output / "viewer-pass-clean.mp4", problematic=False)
    problematic = generate_viewer_pass_fixture(output / "viewer-pass-problematic.mp4", problematic=True)
    print(f"Generated {clean.relative_to(root)}")
    print(f"Generated {problematic.relative_to(root)}")


if __name__ == "__main__":
    main()
