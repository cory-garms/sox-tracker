"""
What the postgame log can say that the graded record cannot.

Two questions the track record page could only answer by hand until now.

**Projection accuracy.** The graded record scores 230 predictions, because a
prediction is only graded when a book posted a line to grade it against. The log
holds far more than that: every row whose player actually appeared carries an
`actual`, priced or not. Scoring projection against outcome instead of against a
line roughly doubles the sample and, more to the point, includes the players the
market never quoted.

**The selection effect.** Which is where those extra rows earn their keep. The
model can rank hitter-games across the roster and cannot rank the ones a book
has priced. That claim has been on the page since August as a hand-typed table
from a one-off measurement, and by 2026-09-07 two of its six numbers had moved
materially -- the priced recalibration slope from -0.014 to -0.822, and the
hitter count from 54 to 22. A page whose argument is "we measure rather than
assert" cannot carry a table nobody recomputes. This module recomputes it.

The walk-forward lives here rather than in scripts/backtest_batter_tb.py so the
script and the page share one implementation. It is the script's, moved
unchanged: every start a hitter made, in date order, projected using only the
starts before it.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

import config
from analysis import scoring
from analysis.betting import (
    MIN_PA_FOR_TB_PROP,
    _lineup_starts,
    _per_pa_mix,
    _pmf_over_push,
    _total_bases,
    project_batter_tb,
)

# A hitter needs some history before a projection means anything. The page's own
# floor is MIN_PA_FOR_TB_PROP plate appearances; the backtest adds a start count
# so the earliest games of the season, where every hitter looks identical, do
# not dominate the sample.
MIN_PRIOR_STARTS = 10

# The line the whole market is posted at, and therefore the question
# discrimination has to be measured on.
REFERENCE_LINE = 1.5

GRADED = ("over", "under", "push")


def load_starts(season: int, team_id: int) -> pd.DataFrame:
    path = config.CACHE_DIR / f"batting_{team_id}_{season}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"No cached batting for {season}: {path}\n"
            f"Run: python fetch.py --season {season} --refresh"
        )
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
                "alt_season": float(prior["tb"].sum()) / len(prior),
                "alt_l10": float(l10["tb"].sum()) / len(l10),
                "alt_blend": 0.4 * (float(prior["tb"].sum()) / len(prior))
                             + 0.6 * (float(l10["tb"].sum()) / len(l10)),
            })
    return pd.DataFrame(rows)


def priced_keys(history: pd.DataFrame,
                market: str = "batter_total_bases") -> set[tuple[int, str]]:
    """
    (player_id, game_date) for every player-game a book actually posted a line on.

    Read from the prediction log rather than the odds log because that is where
    the line the model was quoted against is recorded, already collapsed to one
    row per player-game by latest_per_game.
    """
    if history is None or history.empty:
        return set()
    from data import predictions_history as ph

    kept = ph.latest_per_game(history)
    priced = kept[(kept["market"] == market) & kept["line"].notna()]
    out: set[tuple[int, str]] = set()
    for pid, date in zip(priced["player_id"], priced["game_date"]):
        if pd.isna(pid):
            continue
        out.add((int(pid), str(date)))
    return out


def selection_table(held: pd.DataFrame,
                    priced: set[tuple[int, str]]) -> list[dict[str, Any]]:
    """
    The same question asked of two populations: every hitter-start, and only the
    ones a book priced.

    Returns a row per population with n, AUC, recalibration slope, base rate and
    how many distinct hitters it rests on -- the last because "the twelve
    regulars a book bothers to quote" is the actual mechanism, and a reader
    cannot check that claim without the count.
    """
    if held is None or held.empty:
        return []
    flag = [(int(p), str(d)) in priced
            for p, d in zip(held["player_id"], held["game_date"])]
    held = held.assign(priced=flag)

    rows = []
    for label, sub in (("All hitter-starts", held),
                       ("Only those a book priced", held[held["priced"]])):
        if sub.empty:
            continue
        d = scoring.discrimination(sub["p_over"], sub["cleared"])
        rows.append({
            "population": label,
            "n": int(d["n"]),
            "auc": d["auc"],
            "slope": d["slope"],
            "base_rate": d["base_rate"],
            "hitters": int(sub["player_id"].nunique()),
        })
    return rows


def projection_accuracy(history: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Projection against outcome, for every row whose player appeared.

    The graded record can only score a prediction a book priced. This scores
    every prediction the box score can settle, split by whether a line existed,
    which is the comparison the selection effect is made of.

    `r` is the correlation between projection and actual across player-games --
    can the model tell one start from another. It is reported with a Fisher
    interval because on these sample sizes the point estimate alone invites a
    conclusion the data does not support.
    """
    if history is None or history.empty:
        return []
    from data import predictions_history as ph

    kept = ph.latest_per_game(history)
    kept = kept[kept["actual"].notna() & kept["projection"].notna()]
    if kept.empty:
        return []

    rows = []
    for market, sub in kept.groupby("market"):
        for label, part in (("priced", sub[sub["line"].notna()]),
                            ("unpriced", sub[sub["line"].isna()])):
            n = len(part)
            if n == 0:
                continue
            err = part["projection"].to_numpy() - part["actual"].to_numpy()
            r, lo, hi = _corr_ci(part["projection"], part["actual"])
            rows.append({
                "market": market, "population": label, "n": n,
                "mae": float(np.abs(err).mean()),
                "bias": float(err.mean()),
                "r": r, "r_lo": lo, "r_hi": hi,
                "graded": int(part["outcome"].isin(GRADED).sum()),
            })
    return rows


def _corr_ci(x, y, conf: float = 1.96) -> tuple[float, float, float]:
    """Pearson r with a Fisher-z interval; NaNs when the sample cannot carry one."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n < 4 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan"), float("nan"), float("nan")
    r = float(np.corrcoef(x, y)[0, 1])
    if not np.isfinite(r) or abs(r) >= 1.0:
        return r, float("nan"), float("nan")
    z, se = np.arctanh(r), 1.0 / np.sqrt(n - 3)
    return r, float(np.tanh(z - conf * se)), float(np.tanh(z + conf * se))


def gap_z(rows: list[dict[str, Any]], market: str) -> float:
    """
    Whether the priced/unpriced correlation gap survives its own sample sizes.

    The individual correlations are mostly indistinguishable from zero; the
    difference between them is the claim, so the difference is what gets tested.
    Fisher-z on two independent correlations.
    """
    got = {r["population"]: r for r in rows if r["market"] == market}
    p, u = got.get("priced"), got.get("unpriced")
    if not p or not u or p["n"] < 5 or u["n"] < 5:
        return float("nan")
    if not (np.isfinite(p["r"]) and np.isfinite(u["r"])):
        return float("nan")
    se = np.sqrt(1.0 / (p["n"] - 3) + 1.0 / (u["n"] - 3))
    return float((np.arctanh(u["r"]) - np.arctanh(p["r"])) / se)
