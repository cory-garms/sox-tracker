"""
Walk-forward backtest of the batter total-bases model.

This is where MODEL_ERROR_TB_PROB and MAX_PLAUSIBLE_EDGE_TB_PROB in
analysis/betting.py come from. Neither constant may be edited by hand — re-run
this after any change to the model and copy the numbers it prints.

Method, mirroring the strikeout backtest that produced MODEL_ERROR_K:

  * every start a hitter made, in date order, projected using only the starts
    before it — no information from the day being predicted, or after it;
  * the projection comes from project_batter_tb() in analysis/betting.py, the
    same function the page calls, so this measures the code that ships;
  * bench and pinch-hit games are excluded on both sides: a total-bases prop is
    offered on a hitter who is in the lineup.

What it reports, and why each number matters:

  1. Mean projection accuracy against the alternatives, including the 0.4 season
     / 0.6 last-10 blend the model used to use. If a simpler rule wins, the
     complicated one has no business shipping.
  2. The regression-prior sweep behind TB_REGRESSION_PA.
  3. The model's own error on the question the market asks — will this hitter
     clear the line — by two independent routes: bootstrapping the hitter's own
     sample (parameter noise) and a reliability check (calibration). The larger
     of the two is the honest floor.
  4. Discrimination: AUC and the logistic recalibration slope. A model that
     cannot rank hitter-games has no edge to claim regardless of calibration.

Usage:  python scripts/backtest_batter_tb.py [--season 2026] [--bootstraps 200]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from analysis.betting import (
    MIN_PA_FOR_TB_PROP,
    TB_REGRESSION_PA,
    _lineup_starts,
    _pa_distribution,
    _per_pa_mix,
    _pmf_mean,
    _pmf_over_push,
    _regress_mix,
    _tb_pmf,
    _total_bases,
    project_batter_tb,
)

# A hitter needs some history before a projection means anything. The page's own
# floor is MIN_PA_FOR_TB_PROP plate appearances; the backtest adds a start count
# so that the earliest games of the season, where every hitter looks identical,
# do not dominate the sample.
MIN_PRIOR_STARTS = 10

# The line the whole market is posted at, and therefore the question calibration
# has to be measured on.
REFERENCE_LINE = 1.5


def load_starts(season: int, team_id: int) -> pd.DataFrame:
    path = config.CACHE_DIR / f"batting_{team_id}_{season}.parquet"
    if not path.exists():
        raise SystemExit(f"No cached batting for {season}: {path}\n"
                         f"Run: python fetch.py --season {season} --refresh")
    batting = pd.read_parquet(path)
    starts = _lineup_starts(batting).copy()
    starts["tb"] = _total_bases(starts)
    return starts.sort_values(["game_date", "game_pk"]).reset_index(drop=True)


def walk_forward(starts: pd.DataFrame) -> pd.DataFrame:
    """One row per held-out start, with everything the prior games can say about it."""
    rows = []
    for (pid, pname), games in starts.groupby(["player_id", "player_name"]):
        games = games.sort_values(["game_date", "game_pk"])
        for i in range(len(games)):
            prior, actual = games.iloc[:i], games.iloc[i]
            if len(prior) < MIN_PRIOR_STARTS or prior["pa"].sum() < MIN_PA_FOR_TB_PROP:
                continue

            # The team prior must also be blind to the day being predicted.
            team_prior = starts[starts["game_date"] < actual["game_date"]]
            team_mix = _per_pa_mix(team_prior)

            projection = project_batter_tb(prior, team_mix)
            if projection is None:
                continue
            p_over, _ = _pmf_over_push(projection["pmf"], REFERENCE_LINE)

            l10 = prior.tail(10)
            rows.append({
                "player_id": pid, "player_name": pname,
                "game_date": actual["game_date"],
                "actual_tb": float(actual["tb"]),
                "cleared": int(actual["tb"] > REFERENCE_LINE),
                "proj_tb": projection["proj_tb"],
                "p_over": p_over,
                "prior_pa": float(prior["pa"].sum()),
                "prior_starts": len(prior),
                # alternatives, for the comparison in section 1
                "alt_season": float(prior["tb"].sum()) / len(prior),
                "alt_l10": float(l10["tb"].sum()) / len(l10),
                "alt_blend": 0.4 * (float(prior["tb"].sum()) / len(prior))
                             + 0.6 * (float(l10["tb"].sum()) / len(l10)),
            })
    return pd.DataFrame(rows)


def report_accuracy(held: pd.DataFrame) -> None:
    print("\n1. MEAN PROJECTION — held-out mean absolute / root-mean-square error")
    print("   %-28s %8s %8s %8s" % ("", "MAE", "RMSE", "bias"))
    variants = {
        "season TB per start": held["alt_season"],
        "last 10 starts": held["alt_l10"],
        "0.4 season / 0.6 last-10 (old)": held["alt_blend"],
        "shipped (per-PA, regressed)": held["proj_tb"],
    }
    for label, proj in variants.items():
        err = proj - held["actual_tb"]
        print("   %-28s %8.3f %8.3f %+8.3f"
              % (label, err.abs().mean(), np.sqrt((err ** 2).mean()), err.mean()))
    print("   Note: no variant separates from any other by much. As with the "
          "strikeout\n         model, recency weighting buys nothing — which is "
          "why the shipped\n         projection is a rate model rather than a "
          "hand-tuned blend.")


def report_regression_sweep(starts: pd.DataFrame, held: pd.DataFrame) -> None:
    print("\n2. REGRESSION PRIOR — sweep behind TB_REGRESSION_PA (currently %.0f PA)"
          % TB_REGRESSION_PA)
    print("   %6s %8s %8s" % ("prior", "MAE", "RMSE"))
    cache: dict[tuple, tuple] = {}
    for prior_pa in (0.0, 25.0, 50.0, 100.0, 200.0, 400.0):
        projections = []
        for row in held.itertuples():
            key = (row.player_id, row.game_date)
            if key not in cache:
                games = starts[(starts["player_id"] == row.player_id)
                               & (starts["game_date"] < row.game_date)]
                team_prior = starts[starts["game_date"] < row.game_date]
                cache[key] = (
                    _per_pa_mix(games), float(games["pa"].sum()),
                    _pa_distribution(games), _per_pa_mix(team_prior),
                )
            mix, pa, pa_counts, team_mix = cache[key]
            if mix is None or not pa_counts:
                projections.append(np.nan)
                continue
            regressed = _regress_mix(mix, pa, team_mix, prior_pa)
            projections.append(_pmf_mean(_tb_pmf(regressed, pa_counts)))
        err = pd.Series(projections) - held["actual_tb"].reset_index(drop=True)
        print("   %6.0f %8.3f %8.3f"
              % (prior_pa, err.abs().mean(), np.sqrt((err ** 2).mean())))


def report_probability_error(starts: pd.DataFrame, held: pd.DataFrame,
                             bootstraps: int, stride: int, seed: int) -> float:
    """Parameter noise: how far does the model's own probability move on resampling?"""
    print("\n3a. PARAMETER NOISE — bootstrap of each hitter's own prior sample")
    rng = np.random.default_rng(seed)
    sds = []
    for row in held.iloc[::stride].itertuples():
        prior = starts[(starts["player_id"] == row.player_id)
                       & (starts["game_date"] < row.game_date)]
        team_mix = _per_pa_mix(starts[starts["game_date"] < row.game_date])
        draws = []
        for _ in range(bootstraps):
            sample = prior.sample(len(prior), replace=True,
                                  random_state=int(rng.integers(1 << 31)))
            projection = project_batter_tb(sample, team_mix)
            if projection is None:
                continue
            draws.append(_pmf_over_push(projection["pmf"], REFERENCE_LINE)[0])
        if len(draws) > 1:
            sds.append(float(np.std(draws)))
    sds = np.array(sds)
    print("   resampled %d of %d held-out starts, %d bootstraps each"
          % (len(sds), len(held), bootstraps))
    print("   sd of the model's own over-probability: mean %.4f  median %.4f  p90 %.4f"
          % (sds.mean(), np.median(sds), np.percentile(sds, 90)))
    return float(sds.mean())


def report_calibration(held: pd.DataFrame, bins: int = 6) -> float:
    """Reliability: do predicted probabilities match observed frequencies?"""
    print("\n3b. CALIBRATION — predicted vs observed rate of clearing %.1f bases"
          % REFERENCE_LINE)
    held = held.copy()
    held["bin"] = pd.qcut(held["p_over"], bins, duplicates="drop")
    table = held.groupby("bin", observed=True).agg(
        n=("cleared", "size"), predicted=("p_over", "mean"), observed=("cleared", "mean"))
    table["gap"] = table["predicted"] - table["observed"]
    print("   %6s %10s %10s %8s" % ("n", "predicted", "observed", "gap"))
    for _, r in table.iterrows():
        print("   %6d %10.3f %10.3f %+8.3f" % (r["n"], r["predicted"], r["observed"], r["gap"]))

    weights = table["n"] / table["n"].sum()
    rms_gap = float(np.sqrt((weights * table["gap"] ** 2).sum()))
    noise = float(np.sqrt((weights * table["predicted"] * (1 - table["predicted"])
                           / table["n"]).sum()))
    print("   weighted RMS gap %.4f   sampling-noise floor %.4f" % (rms_gap, noise))
    if rms_gap < noise:
        print("   The gap is smaller than the noise floor: this test cannot resolve\n"
              "   miscalibration finer than %.3f, which is itself a lower bound on\n"
              "   what the model may claim to know." % noise)
    return max(rms_gap, noise)


def report_discrimination(held: pd.DataFrame) -> float:
    """AUC and recalibration slope — can the model rank hitter-games at all?"""
    print("\n4. DISCRIMINATION — can the model tell these starts apart?")
    y = held["cleared"].to_numpy()
    p = held["p_over"].to_numpy()

    order = np.argsort(p)
    ranks = np.empty(len(p), dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    # average ranks over ties, so a flat predictor scores 0.5 rather than better
    frame = pd.DataFrame({"p": p, "rank": ranks})
    ranks = frame.groupby("p")["rank"].transform("mean").to_numpy()
    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    auc = (ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)

    logit = np.log(np.clip(p, 1e-9, 1 - 1e-9) / (1 - np.clip(p, 1e-9, 1 - 1e-9)))
    design = np.column_stack([np.ones_like(logit), logit])
    beta = np.zeros(2)
    for _ in range(60):
        mu = 1 / (1 + np.exp(-design @ beta))
        w = np.clip(mu * (1 - mu), 1e-9, None)
        beta = beta + np.linalg.solve(design.T @ (design * w[:, None]),
                                      design.T @ (y - mu))
    slope = float(beta[1])

    base = float(y.mean())
    brier = float(((p - y) ** 2).mean())
    brier_base = float(((base - y) ** 2).mean())
    print("   base rate %.4f   mean prediction %.4f   sd of predictions %.4f"
          % (base, p.mean(), p.std()))
    print("   AUC %.4f  (0.50 = coin flip)" % auc)
    print("   Brier %.4f vs %.4f for always quoting the base rate — skill %+.4f"
          % (brier, brier_base, 1 - brier / brier_base))
    print("   recalibration slope %.3f  (1.00 = the spread of predictions is real)" % slope)
    information = abs(slope) * float(p.std())
    print("   demonstrated information: |slope| x sd = %.4f" % information)
    return information


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--season", type=int, default=config.SEASON)
    parser.add_argument("--team-id", type=int, default=config.TEAM_ID)
    parser.add_argument("--bootstraps", type=int, default=60,
                        help="bootstrap draws per sampled start (default 60)")
    parser.add_argument("--stride", type=int, default=7,
                        help="bootstrap every Nth held-out start (default 7)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    starts = load_starts(args.season, args.team_id)
    held = walk_forward(starts)
    if held.empty:
        raise SystemExit("No held-out starts — is the cache populated?")

    print("=" * 72)
    print("BATTER TOTAL BASES — WALK-FORWARD BACKTEST, %d" % args.season)
    print("=" * 72)
    print("held-out starts: %d   hitters: %d   dates: %s to %s"
          % (len(held), held["player_id"].nunique(),
             held["game_date"].min(), held["game_date"].max()))

    report_accuracy(held)
    report_regression_sweep(starts, held)
    parameter_noise = report_probability_error(starts, held, args.bootstraps,
                                               args.stride, args.seed)
    calibration_floor = report_calibration(held)
    information = report_discrimination(held)

    error = max(parameter_noise, calibration_floor)
    print("\n" + "=" * 72)
    print("CONSTANTS FOR analysis/betting.py")
    print("=" * 72)
    print("MODEL_ERROR_TB_PROB        = %.3f   # larger of parameter noise (%.4f)"
          % (error, parameter_noise))
    print("                                     # and calibration resolution (%.4f)"
          % calibration_floor)
    print("MAX_PLAUSIBLE_EDGE_TB_PROB = %.3f   # demonstrated information" % information)
    if information <= error * 1.25:
        print("\nThe ceiling sits within a quarter of the floor. The model's whole")
        print("demonstrated information is barely larger than its own noise, so there")
        print("is no honest window to recommend from — the table must publish the")
        print("line, both probabilities and the gap, and no bet.")
    else:
        print("\nThe band is open: edges between %.3f and %.3f clear the model's own"
              % (error, information))
        print("error without exceeding what it has been shown to know.")


if __name__ == "__main__":
    main()
