#!/usr/bin/env python3
"""
Walk-forward strikeout backtest across every starter in the league, against
standard baselines.

Two things the team-only backtest could not do.

**Measure.** Over 73 held-out starts the standard error on MODEL_ERROR_K is
±0.41 K, so an improvement had to exceed ~0.8 K before the test could see it.
No realistic modelling change is that large, which means every feature was
destined to measure as "no change" whether or not it worked - and the opponent
K-rate adjustment duly did. `pitcher_strikeout_model` projects a starter from
his own log and knows nothing about Boston, so it can be run over the whole
league: ~2,950 starts, standard error ~±0.08 K.

**Compare.** A model that has only ever been compared to itself has not been
shown to be worth anything. Tom Tango's Marcel exists to be the floor - "the
minimum level of competence you should expect from any forecaster" - and its
central lesson is the one this model does not apply: regress a player's own
rate toward the league mean by sample size.

Usage:
    python scripts/backtest_league_k.py [--season 2026] [--min-prior-starts 3]
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from analysis.k_projections import (  # noqa: E402
    project_blend, project_league, project_marcel, project_season,
)
from client.mlb_client import MLBClient  # noqa: E402
from data import league_pitching as lp  # noqa: E402
from data import opponent as opp  # noqa: E402
from scripts.backtest_pitcher_k import decompose  # noqa: E402

BOOTSTRAP_RESAMPLES = 2000


def se_of_model_error(d: dict) -> float:
    """
    Standard error on a *single* model's error estimate.

    SE(MSE) ~ MSE * sqrt(2/n) for roughly-normal residuals, and model_err is
    sqrt(MSE - poisson), so the error propagates as SE(MSE) / (2 * model_err).

    This is the right error bar to print next to one model's absolute accuracy.
    It is the WRONG thing to compare two models with - see `paired_ci`.
    """
    n, mse, me = d.get("n", 0), d.get("rmse", 0) ** 2, d.get("model_err", 0)
    if not n or me <= 0:
        return float("nan")
    return (mse * math.sqrt(2.0 / n)) / (2.0 * me)


def paired_ci(
    sq_a: list[float], sq_b: list[float],
    resamples: int = BOOTSTRAP_RESAMPLES, seed: int = 7,
) -> tuple[float, float, float]:
    """
    95% CI on the MSE gap between two models, resampling STARTS rather than
    models. Positive means `a` is worse. Units are K^2.

    Why paired. Both models predict the same held-out starts, so most of the
    variation in either one's absolute error is variation in the starts
    themselves - the same hard nights make every model look bad at once.
    Comparing a difference against the standard error of one model's *absolute*
    error tests a far noisier quantity than the one being asked about. That was
    the original bug here: blend and Marcel differ by 0.164 K against an
    unpaired 2 x SE of 0.23 K, so the script reported "cannot separate them"
    when resampling the shared starts puts the gap comfortably clear of zero.

    Why MSE and not model error. `model_err` is sqrt(max(0, mse - poisson)),
    and on this data mse (~5.24) sits only ~0.2-0.5 above the Poisson floor
    (~4.97). Bootstrap resamples routinely push that difference negative, where
    the max(0, ...) clips it to zero - so the resampled distribution piles up
    against a hard floor and the lower bound of the CI comes back as exactly
    +0.00000 no matter which seed is used. That is an artefact of the clip, not
    a finding, and it made a real effect look unmeasurable: the opponent factor
    on top of Marcel reported [+0.000, +0.233] clipped, and [+0.016, +0.120] -
    stable across seeds, clear of zero - on the unclipped MSE.

    MSE is the honest paired statistic because the Poisson term subtracted from
    it is a property of the projection's scale rather than of its accuracy, and
    it is near-identical across these models (4.947-4.980). Ranking by MSE and
    ranking by model error therefore agree; only the error bar differs.
    """
    n = len(sq_a)
    if n == 0 or n != len(sq_b):
        return float("nan"), float("nan"), float("nan")
    point = sum(sq_a) / n - sum(sq_b) / n
    rng = random.Random(seed)
    diffs = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append((sum(sq_a[i] for i in idx) - sum(sq_b[i] for i in idx)) / n)
    diffs.sort()
    return point, diffs[int(0.025 * resamples)], diffs[int(0.975 * resamples)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=config.SEASON)
    ap.add_argument("--min-prior-starts", type=int, default=3)
    args = ap.parse_args()

    client = MLBClient()
    # max_age_hours=0: read whatever is cached. Re-fetching ~200 game logs to
    # re-measure a fixed historical sample would change the answer only by
    # adding starts, which is the one thing a run-to-run comparison must not do.
    logs = lp.load_league_logs(args.season, client=client, max_age_hours=0)
    hitting = opp.load_team_hitting_logs(args.season, client=client, max_age_hours=0)
    if logs.empty:
        print("No league pitching logs cached. Run once with network access.")
        return 1

    starts = logs[logs["is_start"]].dropna(subset=["game_date"]).copy()
    league_k9 = lp.league_k_per_9(logs)
    print(f"League starters {args.season}: {starts['player_id'].nunique()} pitchers, "
          f"{len(starts)} starts, league K/9 {league_k9:.2f}\n")

    models = ("league", "season", "marcel", "blend", "blend+opp", "marcel+opp")
    preds: dict[str, list[float]] = {k: [] for k in models}
    actual: list[float] = []

    for _, group in starts.groupby("player_id"):
        group = group.sort_values("game_date")
        for i in range(len(group)):
            if i < args.min_prior_starts:
                continue
            prior, row = group.iloc[:i], group.iloc[i]
            date = str(row["game_date"])
            # League rate as of this date only - never its own future.
            lk9 = lp.league_k_per_9(logs, before=date) or league_k9

            p_blend, _ = project_blend(prior, 1.0)
            if p_blend != p_blend:
                continue
            p_season, _ = project_season(prior)
            p_marcel, _ = project_marcel(prior, lk9)
            p_league, _ = project_league(prior, lk9)

            factor = 1.0
            if not hitting.empty and pd.notna(row.get("opponent_id")):
                factor = opp.opponent_k_factor(
                    hitting, int(row["opponent_id"]), before=date)
            p_blend_opp, _ = project_blend(prior, factor)
            p_marcel_opp, _ = project_marcel(prior, lk9, k_factor=factor)

            for key, val in (("league", p_league), ("season", p_season),
                             ("marcel", p_marcel), ("blend", p_blend),
                             ("blend+opp", p_blend_opp),
                             ("marcel+opp", p_marcel_opp)):
                preds[key].append(val)
            actual.append(float(row["so"]))

    print(f"{'model':<14}{'RMSE':>8}{'MAE':>8}{'model err':>11}{'  +/- SE':>10}{'bias':>8}")
    print("-" * 59)
    results = {}
    for key in models:
        d = decompose(preds[key], actual)
        results[key] = d
        print(f"{key:<14}{d['rmse']:>8.3f}{d['mae']:>8.3f}"
              f"{d['model_err']:>11.3f}{se_of_model_error(d):>10.3f}{d['bias']:>+8.3f}")

    n = results["blend"]["n"]
    print(f"\nheld-out starts: {n}")

    # Per-start squared residuals, so two models can be compared on the starts
    # they actually share rather than on their own separate error bars.
    sq = {k: [(p - a) ** 2 for p, a in zip(preds[k], actual)] for k in models}

    print("\nPaired comparisons - resampling the starts, 95% CI on the MSE gap")
    print("-" * 70)
    contrasts = (
        ("blend", "season"),       # does the last-5 term earn anything?
        ("blend", "marcel"),       # does regression to the mean beat the blend?
        ("blend", "blend+opp"),    # does the opponent factor help?
        ("marcel", "marcel+opp"),  # ...and does it still help on top of Marcel?
        ("blend", "marcel+opp"),   # shipped-vs-shipped: the whole change
    )
    for a, b in contrasts:
        point, lo, hi = paired_ci(sq[a], sq[b])
        if lo > 0:
            verdict = f"{b} better"
        elif hi < 0:
            verdict = f"{a} better"
        else:
            verdict = "no measurable difference"
        print(f"{a:>11} - {b:<12}{point:>+9.4f} K^2  "
              f"[{lo:+.4f}, {hi:+.4f}]  {verdict}")

    best = min(results, key=lambda k: results[k]["model_err"])
    print(f"\nlowest measured error: {best} ({results[best]['model_err']:.3f} K)")
    print(f"Set MODEL_ERROR_K = {results[best]['model_err']:.2f} if you ship "
          f"{best}.")
    print("Set it from the model actually shipped, not from the best row, and")
    print("do not keep an older lower value because it let the page speak.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
