"""
Has the strikeout model actually got better?

The site publishes a model error and gates every NO CALL on it, but nothing on
it said whether the model behind that constant had improved, got worse, or never
changed. Asking the prediction log is hopeless: the replayed rows end 2026-08-23
and the live rows begin 2026-08-24, so early-versus-late is exactly
replay-versus-live and the two cannot be separated.

What can answer it is the lineage. Each projection this repo has shipped still
exists as a function in analysis/k_projections.py -- `project_blend` is what ran
until 2026-08-04, `project_marcel` replaced it, and the opponent factor is
applied on top of whichever is in force. Run all of them over the same held-out
league starts and the comparison is exact: same starts, same priors, same
opponents, only the arithmetic differs.

That comparison already existed in scripts/backtest_league_k.py, run by hand,
with its conclusion -- "beats the blend by 0.16 K" -- written into a docstring
on 2026-08-05 and never recomputed. This module is that walk-forward, shared
with the script and cached, so the page can state the lineage from a number
rather than from a memory of one.

Cost: no network and no odds quota; it reads the cached league logs. It takes
about 18 seconds over ~3,200 held-out starts, which is too slow for every page
build and is why the result is cached like any other league-wide measurement.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import config
from analysis import scoring
from analysis.k_projections import (
    project_blend,
    project_league,
    project_marcel,
    project_season,
)
from data import cache_freshness, league_pitching as lp, opponent as opp

log = logging.getLogger(__name__)

# In shipping order, so the table reads as a history rather than a ranking.
# "shipped" marks what the page runs today; "retired" what it ran before.
MODELS: tuple[dict[str, Any], ...] = (
    {"key": "league", "label": "League average", "status": "baseline",
     "note": "Every starter gets the league rate. The floor any model must clear."},
    {"key": "season", "label": "Season average", "status": "baseline",
     "note": "The pitcher's own rate, unregressed."},
    {"key": "blend", "label": "Season / last-5 blend", "status": "retired",
     "note": "Shipped until 2026-08-04."},
    {"key": "blend+opp", "label": "Blend + opponent", "status": "retired",
     "note": "The blend with the opponent strikeout factor applied."},
    {"key": "marcel", "label": "Marcel regression", "status": "component",
     "note": "Own rate regressed toward the league by innings behind it."},
    {"key": "marcel+opp", "label": "Marcel + opponent", "status": "shipped",
     "note": "What the board runs today."},
)

# The pairs worth reporting: each one isolates a single decision.
COMPARISONS: tuple[tuple[str, str, str], ...] = (
    ("blend", "season", "Did the last-5 term earn anything?"),
    ("blend", "marcel", "Did replacing the blend with regression help?"),
    ("marcel", "marcel+opp", "Does the opponent factor help?"),
    ("blend", "marcel+opp", "Both changes together, against what shipped before."),
)

MIN_PRIOR_STARTS = 3


def cache_path(season: int) -> Path:
    return config.CACHE_DIR / f"model_lineage_{season}.json"


def _decompose(projected, actual) -> dict[str, float]:
    return scoring.decompose(projected, actual)


def measure(season: int = config.SEASON,
            min_prior_starts: int = MIN_PRIOR_STARTS) -> dict[str, Any]:
    """
    Every model this repo has shipped, over the same held-out league starts.

    Walk-forward: each start is projected from that pitcher's previous starts
    only, and the league rate is taken as of that date, so no model ever sees
    its own future. Returns {} when the league logs are not cached rather than
    fetching ~200 game logs from inside a page build.
    """
    logs = lp.load_league_logs(season, client=None, max_age_hours=0)
    if logs is None or logs.empty:
        return {}
    hitting = opp.load_team_hitting_logs(season, client=None, max_age_hours=0)

    starts = logs[logs["is_start"]].dropna(subset=["game_date"]).copy()
    league_k9 = lp.league_k_per_9(logs)
    if not league_k9:
        return {}

    keys = [m["key"] for m in MODELS]
    preds: dict[str, list[float]] = {k: [] for k in keys}
    actual: list[float] = []

    for _, group in starts.groupby("player_id"):
        group = group.sort_values("game_date")
        for i in range(len(group)):
            if i < min_prior_starts:
                continue
            prior, row = group.iloc[:i], group.iloc[i]
            date = str(row["game_date"])
            lk9 = lp.league_k_per_9(logs, before=date) or league_k9

            p_blend, _ = project_blend(prior, 1.0)
            if p_blend != p_blend:                      # NaN: nothing to project from
                continue
            factor = 1.0
            if hitting is not None and not hitting.empty and pd.notna(row.get("opponent_id")):
                factor = opp.opponent_k_factor(hitting, int(row["opponent_id"]), before=date)

            values = {
                "league": project_league(prior, lk9)[0],
                "season": project_season(prior)[0],
                "marcel": project_marcel(prior, lk9)[0],
                "blend": p_blend,
                "blend+opp": project_blend(prior, factor)[0],
                "marcel+opp": project_marcel(prior, lk9, k_factor=factor)[0],
            }
            for k in keys:
                preds[k].append(values[k])
            actual.append(float(row["so"]))

    if not actual:
        return {}

    rows = []
    for spec in MODELS:
        d = _decompose(preds[spec["key"]], actual)
        rows.append({**spec, **{
            "rmse": d["rmse"], "mae": d["mae"],
            "model_err": d["model_err"], "bias": d["bias"],
            "se": scoring.se_of_model_error(d),
        }})

    y = np.asarray(actual, dtype=float)
    pairs = []
    for a, b, question in COMPARISONS:
        pa = np.asarray(preds[a], dtype=float)
        pb = np.asarray(preds[b], dtype=float)
        gap, lo, hi = _paired_mse_gap(pa, pb, y)
        better = None
        if np.isfinite(lo) and np.isfinite(hi) and not (lo <= 0 <= hi):
            better = b if gap > 0 else a
        pairs.append({"a": a, "b": b, "question": question,
                      "gap": gap, "lo": lo, "hi": hi, "better": better})

    return {
        "season": season,
        "n": len(actual),
        "pitchers": int(starts["player_id"].nunique()),
        "league_k9": float(league_k9),
        "models": rows,
        "comparisons": pairs,
    }


def _paired_mse_gap(pa: np.ndarray, pb: np.ndarray, y: np.ndarray,
                    draws: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """
    Mean squared error of `a` minus that of `b`, with a paired bootstrap.

    Paired because both models predict the same starts: most of the variance is
    the starts themselves, and resampling them independently would drown a real
    difference in noise that cancels. A positive gap means `b` is better.
    """
    ok = np.isfinite(pa) & np.isfinite(pb) & np.isfinite(y)
    pa, pb, y = pa[ok], pb[ok], y[ok]
    if len(y) < 10:
        return float("nan"), float("nan"), float("nan")
    ea, eb = (pa - y) ** 2, (pb - y) ** 2
    diff = ea - eb
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diff), (draws, len(diff)))
    boots = diff[idx].mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(diff.mean()), float(lo), float(hi)


def load(season: int = config.SEASON,
         max_age_hours: float = 24.0,
         force_refresh: bool = False) -> dict[str, Any]:
    """
    The lineage, cached.

    Twenty-four hours rather than the usual twelve: the answer moves only when
    the league plays, and the walk-forward is the most expensive thing on the
    page. A failed re-measurement serves the stored copy rather than emptying
    the section.
    """
    path = cache_path(season)
    cached: dict[str, Any] | None = None
    if path.exists() and not force_refresh:
        try:
            cached = json.loads(path.read_text())
        except Exception as e:                              # noqa: BLE001
            log.warning("Could not read %s: %s", path, e)
        if cached and not cache_freshness.is_stale(path, max_age_hours):
            return cached
    try:
        fresh = measure(season)
    except Exception as e:                                  # noqa: BLE001
        log.warning("Model lineage re-measurement failed (%s); using the cache", e)
        return cached or {}
    if not fresh:
        return cached or {}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fresh, indent=1))
    except OSError as e:
        log.warning("Could not write %s: %s", path, e)
    return fresh
