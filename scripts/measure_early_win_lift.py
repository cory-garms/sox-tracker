#!/usr/bin/env python3
"""
Measure what a "team goes up N runs, early win" token is actually worth.

The token grades a moneyline as a winner the moment the team leads by N, and
otherwise settles normally. Its value is therefore not P(ever led by N) — a bet
also wins when the team never leads by N and simply wins by one — but

    P(ever led by N  OR  won)  -  P(won)

which is the extra probability the token buys on top of the price already paid.

Why the *lift* and not the rate. A team's own P(ever up 2) is anchored to the
schedule it happened to play and to how good that team is; it cannot be set
against tonight's price, which already prices tonight's opponent. The lift is
the part that transfers, so that is what this prints and what
analysis.betting.EARLY_WIN_LIFT_2RUN stores.

Method. Walk each game's half-innings and track the running differential.
Checking only at half-inning boundaries is exact, not an approximation: within
a half-inning only the batting team can score, so its peak lead in that
half-inning is always its value at the end of it.

Usage:
    python scripts/measure_early_win_lift.py [--season 2026] [--margin 2]

The printed P(win) is the check worth watching — it must come out at 0.5000
over a full season of team-games, because every game has exactly one winner.
A drift away from that means the linescore walk has lost games, not that the
league became unbalanced.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import MLB_API_BASE, REQUEST_TIMEOUT  # noqa: E402

# The schedule endpoint hydrates linescores in bulk, which turns what would be
# ~2,400 per-game requests into three.
_WINDOWS = [("03-01", "04-30"), ("05-01", "06-15"), ("06-16", "10-05")]


def pull_games(season: int) -> list[dict]:
    games: list[dict] = []
    for start, end in _WINDOWS:
        resp = requests.get(
            f"{MLB_API_BASE}/schedule",
            params={
                "sportId": 1,
                "startDate": f"{season}-{start}",
                "endDate": f"{season}-{end}",
                "hydrate": "linescore",
                "gameType": "R",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        for day in resp.json().get("dates", []):
            games.extend(day.get("games", []))
    return games


def walk(games: list[dict], margin: int) -> tuple[dict, dict]:
    totals: dict[str, int] = defaultdict(int)
    per_team: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for game in games:
        if game.get("status", {}).get("abstractGameState") != "Final":
            continue
        innings = (game.get("linescore") or {}).get("innings") or []
        if not innings:
            continue
        home, away = game["teams"]["home"], game["teams"]["away"]
        home_score, away_score = home.get("score"), away.get("score")
        if home_score is None or away_score is None:
            continue

        home_run = away_run = 0
        home_ever = away_ever = False
        for inning in innings:
            away_run += (inning.get("away") or {}).get("runs") or 0
            if away_run - home_run >= margin:
                away_ever = True
            home_run += (inning.get("home") or {}).get("runs") or 0
            if home_run - away_run >= margin:
                home_ever = True

        for team, ever, scored, allowed in (
            (home["team"], home_ever, home_score, away_score),
            (away["team"], away_ever, away_score, home_score),
        ):
            won = scored > allowed
            for bucket in (totals, per_team[team["id"]]):
                bucket["n"] += 1
                bucket["win"] += won
                bucket["ever"] += ever
                bucket["union"] += ever or won
            per_team[team["id"]]["name"] = team.get("name", "")

    return totals, per_team


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--margin", type=int, default=2, help="run lead that triggers the token")
    args = ap.parse_args()

    games = pull_games(args.season)
    totals, per_team = walk(games, args.margin)
    n = totals["n"]
    if not n:
        print("No completed games with linescores found.")
        return

    p_win = totals["win"] / n
    p_ever = totals["ever"] / n
    p_union = totals["union"] / n
    print(f"{args.season} regular season — {n} team-games, trigger = +{args.margin}\n")
    print(f"  P(win)                     {p_win:.4f}   <- must be 0.5000; it is the parse check")
    print(f"  P(ever led by {args.margin}+)         {p_ever:.4f}")
    print(f"  P(ever led by {args.margin}+ OR won)  {p_union:.4f}   <- the token settles here")
    print(f"\n  TOKEN LIFT                 {p_union - p_win:+.4f}")
    print("\nSet analysis.betting.EARLY_WIN_LIFT_2RUN from the lift above — never by hand.")

    weak = [
        (d["union"] - d["win"]) / d["n"]
        for d in per_team.values()
        if d["n"] > 50 and d["win"] / d["n"] < 0.470
    ]
    if weak:
        print(f"  lift among sub-.470 teams  {sum(weak) / len(weak):+.4f}  (n={len(weak)} teams)")
        print("  (worth checking separately: the token is usually spent on an underdog)")


if __name__ == "__main__":
    main()
