#!/usr/bin/env python3
"""
Union two odds-history files, losslessly.

Why this needs to exist. `data/cache/odds_history.parquet` is the only artefact
in this repo that cannot be rebuilt: a price nobody wrote down at 12:00 ET is
gone for good. It is also a binary file committed from two directions - the
scheduled refresh, the closing-line capture, and any local build - so git will
sooner or later present it as a conflict.

Every ordinary resolution of a binary conflict is wrong here. `--ours`,
`--theirs`, `git checkout` and `-X theirs` all pick one side and discard the
other, and both sides routinely hold snapshots the other lacks: merging the two
versions in flight on 2026-07-27 gave 193 rows where one side had 159 and the
other 162, so either pick would have silently destroyed roughly thirty
observations.

Rows are deduplicated on odds_history.KEY - (captured_at, event_id, market,
player) - which is exactly the identity an append-only log already guarantees,
so a union can never double-count and re-running it is a no-op.

Usage:
    # merge another copy into the canonical file
    python scripts/merge_odds_history.py OTHER.parquet

    # resolve a git conflict without losing either side
    git show :2:data/cache/odds_history.parquet > /tmp/ours.parquet
    git show :3:data/cache/odds_history.parquet > /tmp/theirs.parquet
    python scripts/merge_odds_history.py /tmp/ours.parquet /tmp/theirs.parquet
    git add data/cache/odds_history.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data import odds_history  # noqa: E402


def union(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Every distinct snapshot across all inputs, oldest first."""
    usable = [f for f in frames if f is not None and not f.empty]
    if not usable:
        return pd.DataFrame(columns=odds_history.COLUMNS)
    combined = pd.concat(usable, ignore_index=True).reindex(
        columns=odds_history.COLUMNS
    )
    combined = combined.drop_duplicates(subset=odds_history.KEY, keep="first")
    return combined.sort_values("captured_at").reset_index(drop=True)


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"  {path}: missing, treated as empty")
        return pd.DataFrame(columns=odds_history.COLUMNS)
    frame = pd.read_parquet(path)
    print(f"  {path}: {len(frame)} rows")
    return frame


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("sources", nargs="+", type=Path,
                    help="parquet files to merge in")
    ap.add_argument("--into", type=Path, default=odds_history.HISTORY_PATH,
                    help="destination (default: the canonical history file)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("Reading:")
    frames = [_read(args.into)] + [_read(p) for p in args.sources]
    before = len(frames[0])

    merged = union(frames)
    gained = len(merged) - before
    print(f"\nUnion: {len(merged)} rows across "
          f"{merged['captured_at'].nunique() if not merged.empty else 0} snapshots "
          f"({gained:+d} vs the destination)")

    # The number that matters: if a plain pick would have lost rows, say so
    # loudly, because that is the failure this script exists to prevent.
    for path, frame in zip(args.sources, frames[1:]):
        lost = len(merged) - len(frame)
        if lost > 0:
            print(f"  taking {path} alone would have lost {lost} rows")
    if gained > 0:
        print(f"  taking the destination alone would have lost {gained} rows")

    if args.dry_run:
        print("\nDry run - nothing written.")
        return 0

    args.into.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(args.into, index=False)
    print(f"\nWrote {args.into}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
