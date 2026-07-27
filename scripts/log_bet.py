#!/usr/bin/env python3
"""
Log a bet — real or paper — so it can be graded against the closing line later.

A paper bet is the default. `--stake 0` (the default) records the selection and
the price without implying money moved, and it grades identically, which is the
whole point: an idea should be measurable before it is expensive.

Examples:
    # paper-log tonight's boost candidate
    python scripts/log_bet.py --selection "Athletics" --market h2h \\
        --side Moneyline --price +148 --promo boost_50

    # a prop, with a real stake
    python scripts/log_bet.py --selection "Jack Perkins" \\
        --market pitcher_strikeouts --side Under --line 4.5 --price +120 \\
        --stake 25

    # fill in closing prices from the odds history, then report CLV
    python scripts/log_bet.py --grade
    python scripts/log_bet.py --summary
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data import bet_log, odds_history  # noqa: E402


def _price(raw: str) -> int:
    """"+148" / "-110" / "148" all mean the same thing to a person."""
    return int(str(raw).lstrip("+"))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--selection", help="player or team")
    ap.add_argument("--market", default="h2h")
    ap.add_argument("--side", default="Moneyline", help="Over | Under | Moneyline")
    ap.add_argument("--line", type=float, default=None)
    ap.add_argument("--price", type=_price, help="American odds, e.g. +148 or -110")
    ap.add_argument("--stake", type=float, default=0.0, help="0 = paper bet (default)")
    ap.add_argument("--promo", default="", help="boost_50 | early_win_2run | ''")
    ap.add_argument("--book", default="DraftKings")
    ap.add_argument("--event-id", default="")
    ap.add_argument("--game-date", default=date.today().isoformat())
    ap.add_argument("--model-prob", type=float, default=None)
    ap.add_argument("--consensus-prob", type=float, default=None)
    ap.add_argument("--notes", default="")
    ap.add_argument("--grade", action="store_true",
                    help="fill closing prices from the odds history")
    ap.add_argument("--summary", action="store_true", help="print CLV so far")
    ap.add_argument("--list", action="store_true", help="print the log")
    args = ap.parse_args()

    if args.grade:
        frame = bet_log.grade_from_history(odds_history.load_history())
        filled = int(frame["closing_price"].notna().sum()) if not frame.empty else 0
        print(f"Graded. {filled} of {len(frame)} rows now carry a closing price.")
        return

    if args.summary:
        s = bet_log.clv_summary()
        if not s["n"]:
            print("Nothing graded yet — run --grade once a game has closed.")
            return
        print(f"Settled bets with a close: {s['n']}")
        print(f"Beat the close:            {s['beat_close_pct']}%")
        print(f"Mean CLV:                  {s['mean_clv_points']:+.2f} probability points")
        if s["n"] < 20:
            print("\nToo few to read as evidence. Twenty is roughly where the sign of")
            print("the mean starts to mean something; below that this is an anecdote.")
        return

    if args.list:
        frame = bet_log.load_log()
        print("Bet log is empty." if frame.empty else frame.to_string())
        return

    if not args.selection or args.price is None:
        ap.error("--selection and --price are required when logging a bet")

    bet_log.record_bet(
        selection=args.selection,
        market=args.market,
        side=args.side,
        price=args.price,
        line=args.line,
        stake=args.stake,
        promo=args.promo,
        book=args.book,
        event_id=args.event_id,
        game_date=args.game_date,
        model_prob=args.model_prob,
        consensus_prob=args.consensus_prob,
        notes=args.notes,
    )
    kind = "Paper bet" if args.stake == 0 else f"Bet ({args.stake:g})"
    line = f" {args.line:g}" if args.line is not None else ""
    promo = f" [{args.promo}]" if args.promo else ""
    print(f"{kind} logged: {args.selection} {args.side}{line} @ {args.price:+d}{promo}")


if __name__ == "__main__":
    main()
