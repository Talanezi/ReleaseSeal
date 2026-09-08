#!/usr/bin/env python3
"""Generate the ignored controlled Claim Review fixture."""

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from releaseseal.claim_fixture import generate_claim_review_fixture  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".demo/claim-review.mp4"))
    args = parser.parse_args()
    print(generate_claim_review_fixture(args.output))


if __name__ == "__main__":
    main()
