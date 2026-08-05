#!/usr/bin/env python3
"""
Walk-forward backtest of the strikeout model over one team's starts.

**This script no longer sets MODEL_ERROR_K.** `scripts/backtest_league_k.py`
does, and this one is kept as the local sanity check beside it.

Why it lost that job. It can only see one team's rotation - about 80 held-out
starts - where the standard error on the measurement is roughly +/-0.4 K. That
is wide enough to contain almost any answer: it reported the model error as 1.43,
then 1.39, then 1.26 across three runs that changed nothing about the model, and
it declared the opponent adjustment worthless when a league-wide test later put
that effect comfortably clear of zero. A measurement that noisy cannot referee a
modelling decision, and treating it as though it could is what kept a falsified
comment in analysis/betting.py for a week.

What it is still good for: the projection knows nothing about which team it is
run on, so Boston's number should sit within sampling error of the league one.
If it does not, something is wrong with *this team's* data - a mis-parsed game
log, a reliever counted as a starter - and that is worth catching.

Method. For each start, project it using only the starts before it, then compare
to what actually happened. Nothing about the start being projected, or anything
after it, is visible. The opponent's strikeout rate is likewise bounded to games
before that date, which is the whole reason data/opponent.py stores a game log
rather than a season total.

The decomposition is the point:

    total RMSE^2  =  irreducible Poisson variance  +  model error^2

A strikeout count scatters around its own true mean even when the mean is
exactly right, and for a Poisson that scatter is sqrt(mean). Subtracting it
leaves the part that is the model actually being wrong, which is the only part
a better model can remove - and the only honest floor on an edge.

Usage:
    python scripts/backtest_pitcher_k.py [--season 2026] [--min-prior-starts 3]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from analysis.betting import MODEL_ERROR_K  # noqa: E402
from analysis.k_projections import project_marcel  # noqa: E402
from client.mlb_client import MLBClient  # noqa: E402
from data import league_pitching as lp  # noqa: E402
from data import opponent as opp  # noqa: E402
from data.fetcher import Fetcher  # noqa: E402


def decompose(projected: list[float], actual: list[float]) -> dict[str, float]:
    n = len(projected)
    if not n:
        return {"n": 0}
    mse = sum((p - a) ** 2 for p, a in zip(projected, actual)) / n
    rmse = math.sqrt(mse)
    # A perfect projection of a Poisson count still scatters by sqrt(mean).
    poisson_var = sum(projected) / n
    model_err = math.sqrt(max(0.0, mse - poisson_var))
    bias = sum(p - a for p, a in zip(projected, actual)) / n
    mae = sum(abs(p - a) for p, a in zip(projected, actual)) / n
    return {
        "n": n, "rmse": rmse, "poisson": math.sqrt(poisson_var),
        "model_err": model_err, "bias": bias, "mae": mae,
    }


def report(label: str, d: dict[str, float]) -> None:
    if not d.get("n"):
        print(f"{label}: no held-out starts")
        return
    print(f"{label}")
    print(f"    held-out starts       {d['n']}")
    print(f"    total RMSE            {d['rmse']:.2f} K")
    print(f"    irreducible Poisson   {d['poisson']:.2f} K")
    print(f"    model's own error     {d['model_err']:.2f} K")
    print(f"    mean abs error        {d['mae']:.2f} K")
    print(f"    bias (proj - actual)  {d['bias']:+.2f} K")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=config.SEASON)
    ap.add_argument("--team", default=config.TEAM_ABBR)
    ap.add_argument("--min-prior-starts", type=int, default=3,
                    help="starts required before a projection is attempted")
    args = ap.parse_args()

    team_id = config.TEAMS.get(args.team, {}).get("id", config.TEAM_ID)
    client = MLBClient()
    fetcher = Fetcher(team_id=team_id, season=args.season, client=client)
    pitching = fetcher.load("pitching")
    games = fetcher.load("games")
    logs = opp.load_team_hitting_logs(args.season, client=client, max_age_hours=0)
    league_logs = lp.load_league_logs(args.season, client=client, max_age_hours=0)
    league_k9 = lp.league_k_per_9(league_logs)

    if pitching.empty:
        print("No pitching data cached.")
        return 1
    if logs.empty:
        print("No opponent hitting logs - cannot measure the adjustment.")
        return 1
    if not league_k9:
        print("No league pitching logs - the shipped model regresses toward the")
        print("league mean and cannot be reproduced without them.")
        return 1

    # game_pk -> opponent, so each start knows who it faced.
    opp_by_game = dict(zip(games["game_pk"], games["opponent_id"]))
    date_by_game = dict(zip(games["game_pk"], games["game_date"].astype(str)))

    starters = pitching[pitching["is_starter"] == True].copy()
    starters["game_date"] = starters["game_pk"].map(date_by_game)
    starters["opponent_id"] = starters["game_pk"].map(opp_by_game)
    starters = starters.dropna(subset=["game_date", "opponent_id"])

    base_p, base_a, adj_p, adj_a = [], [], [], []
    factors = []

    for pid, group in starters.groupby("player_id"):
        group = group.sort_values("game_date")
        for i in range(len(group)):
            if i < args.min_prior_starts:
                continue
            prior = group.iloc[:i]
            row = group.iloc[i]
            actual = float(row["so"])
            date = str(row["game_date"])

            # League rate as of this date only - never its own future.
            lk9 = lp.league_k_per_9(league_logs, before=date) or league_k9
            proj_base, _ = project_marcel(prior, lk9)
            if proj_base != proj_base:               # NaN
                continue

            factor = opp.opponent_k_factor(logs, int(row["opponent_id"]), before=date)
            proj_adj, _ = project_marcel(prior, lk9, k_factor=factor)

            base_p.append(proj_base); base_a.append(actual)
            adj_p.append(proj_adj);   adj_a.append(actual)
            factors.append(factor)

    print(f"Walk-forward backtest - {args.team} {args.season}")
    print(f"opponent factors applied: {len(factors)}, "
          f"range {min(factors):.3f} to {max(factors):.3f}, "
          f"mean {sum(factors)/len(factors):.3f}\n")

    base = decompose(base_p, base_a)
    adj = decompose(adj_p, adj_a)
    report("MARCEL          (pitcher only)", base)
    print()
    report("MARCEL + OPP    (as shipped)", adj)

    print("\n" + "=" * 62)
    print(f"{args.team} sits at {adj['model_err']:.2f} K over {adj['n']} starts, "
          f"against the")
    print(f"league-wide {MODEL_ERROR_K:.2f} K that MODEL_ERROR_K is actually set "
          f"from.")
    print()
    print("At this sample the standard error is roughly +/-0.4 K, so these two")
    print("agreeing to within about 0.8 K is all this script can tell you - and")
    print("all it is being asked. A large gap means this team's game logs are")
    print("wrong, not that the constant should move.")
    print("=" * 62)
    print("\nMODEL_ERROR_K comes from scripts/backtest_league_k.py. Do not set it")
    print("from the number above; 80 starts cannot resolve a modelling change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
