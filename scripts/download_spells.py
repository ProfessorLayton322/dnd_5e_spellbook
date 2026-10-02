#!/usr/bin/env python3
"""Download every official 5e spell from dnd.su into the bundled JSON file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spellbook_builder.dndsu import crawl_spells  # noqa: E402
from spellbook_builder.fetch import Fetcher  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "src" / "spellbook_builder" / "data" / "spells.json")
    parser.add_argument("--delay", type=float, default=0.25, help="minimum seconds between requests")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--refresh", action="store_true", help="download records even when already present")
    parser.add_argument("--limit", type=int, help="download only the first N records (parser testing)")
    args = parser.parse_args()

    def progress(index: int, total: int, spell: dict, reused: bool) -> None:
        action = "kept" if reused else "downloaded"
        print(f"[{index:>3}/{total}] {action}: {spell['name']}", flush=True)

    result = crawl_spells(
        Fetcher(timeout=args.timeout, delay=args.delay, retries=args.retries),
        args.output.resolve(),
        refresh=args.refresh,
        limit=args.limit,
        on_progress=progress,
    )
    print(f"Wrote {result['record_count']} spells to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
