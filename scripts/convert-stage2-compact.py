#!/usr/bin/env python3
"""Convert the frozen 60-campaign Stage 2 study and independently compare metrics."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from seedbridge.legacy_compact import convert_stage2_study  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = convert_stage2_study(args.source, args.destination)
    print(
        f"{result['status']}: {result['campaign_count']} campaigns, "
        f"{result['sequence_count']} complete sequences"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
