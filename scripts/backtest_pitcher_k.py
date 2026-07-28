#!/usr/bin/env python3
"""
Walk-forward backtest of the strikeout model, with and without the opponent
adjustment. Prints the number that MODEL_ERROR_K must be set from.

Method. For each start, project it using only the starts before it - the same
blend the live model uses - then compare to what actually happened. Nothing
about the start being projected, or anything after it, is visible to the
projection. The opponent's strikeout rate is likewise bounded to games before
that date, which is the whole reason data/opponent.py stores a game log rather
than a season total.

The decomposition is the point:

    total RMSE^2  =  irreducible Poisson variance  +  model error^2

A strikeout count scatters around its own true mean even when the mean is
exactly right, and for a Poisson that scatter is sqrt(mean). Subtracting it
leaves the part that is the model actually being wrong, which is the only part
a better model can remove - and the only honest floor on an edge.

    MODEL_ERROR_K = sqrt(max(0, total_RMSE^2 - mean_projection))

Usage:
    python scripts/backtest_pitcher_k.py [--season 2026] [--min-prior-starts 3]

Whatever this prints is what the constant becomes. Setting it by hand, or
keeping an older lower value because the new one is inconvenient, defeats the
only mechanism keeping this page honest.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from analysis.betting import L5_REGRESSION_INNINGS  # noqa: E402
from client.mlb_client import MLBClient  # noqa: E402
from data import opponent as opp  # noqa: E402
from data.fetcher import Fetcher  # noqa: E402


def _innings(frame: pd.DataFrame) -> float:
    if "ip_outs" in frame.columns:
        return float(frame["ip_outs"].sum()) / 3.0
    return float(frame["ip"].sum())


def project(prior: pd.DataFrame, k_factor: float = 1.0) -> tuple[float, float]:
    """
    (projected strikeouts, projected innings) from prior starts only.

    Deliberately a re-implementation of the live blend rather than a call into
    it: the model function takes a whole team's frame and returns a table, and
    bending it to answer "one start, as of one date" would mean passing it
    filtered data and trusting that the filter is the only difference. Keeping
    the arithmetic visible here is what makes the backtest auditable.
    """
    tot_ip = _innings(prior)
    if tot_ip <= 0:
        return float("nan"), float("nan")
    season_k9 = float(prior["so"].sum()) * 9.0 / tot_ip
    season_avg_ip = tot_ip / len(prior)

    last5 = prior.tail(5)
    l5_ip = _innings(last5)
    if l5_ip > 0:
        l5_k9 = float(last5["so"].sum()) * 9.0 / l5_ip
        l5_avg_ip = l5_ip / len(last5)
    else:
        l5_k9, l5_avg_ip = season_k9, season_avg_ip

    w5 = l5_ip / (l5_ip + L5_REGRESSION_INNINGS) if l5_ip > 0 else 0.0
    ws = 1.0 - w5
    k9 = (season_k9 * ws + l5_k9 * w5) * k_factor
    ip = season_avg_ip * ws + l5_avg_ip * w5
    return k9 * ip / 9.0, ip


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
    logs = opp.load_team_hitting_logs(args.season, client=client)

    if pitching.empty:
        print("No pitching data cached.")
        return 1
    if logs.empty:
        print("No opponent hitting logs - cannot measure the adjustment.")
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

            proj_base, _ = project(prior, 1.0)
            if proj_base != proj_base:               # NaN
                continue

            factor = opp.opponent_k_factor(logs, int(row["opponent_id"]), before=date)
            proj_adj, _ = project(prior, factor)

            base_p.append(proj_base); base_a.append(actual)
            adj_p.append(proj_adj);   adj_a.append(actual)
            factors.append(factor)

    print(f"Walk-forward backtest - {args.team} {args.season}")
    print(f"opponent factors applied: {len(factors)}, "
          f"range {min(factors):.3f} to {max(factors):.3f}, "
          f"mean {sum(factors)/len(factors):.3f}\n")

    base = decompose(base_p, base_a)
    adj = decompose(adj_p, adj_a)
    report("BASELINE  (pitcher only)", base)
    print()
    report("ADJUSTED  (+ opponent K rate)", adj)

    print("\n" + "=" * 58)
    delta = adj["model_err"] - base["model_err"]
    if delta < -0.005:
        print(f"The adjustment REDUCED model error by {abs(delta):.2f} K "
              f"({base['model_err']:.2f} -> {adj['model_err']:.2f}).")
    elif delta > 0.005:
        print(f"The adjustment INCREASED model error by {delta:.2f} K "
              f"({base['model_err']:.2f} -> {adj['model_err']:.2f}).")
        print("Keep the baseline. An adjustment that does not measure better is")
        print("a story, not a model.")
    else:
        print(f"No measurable change ({base['model_err']:.2f} -> "
              f"{adj['model_err']:.2f} K).")
    print("=" * 58)
    print(f"\nSet MODEL_ERROR_K = {min(adj['model_err'], base['model_err']):.2f}")
    print("Copy the measurement. Do not round it down, and do not keep an older")
    print("lower value because it let the page speak.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
