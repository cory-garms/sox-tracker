"""
Forecast scoring — how good was a projection, really?

The maths here already existed, scattered across three backtest scripts that
each printed to stdout. That was fine when the only consumer was someone running
a script, and useless to a page that needs the numbers rather than the report.
These are the same computations returning data, so the scripts and the track
record page cannot drift into disagreeing about what the model's error is.

Everything is a pure function of two sequences. Nothing here reads a file.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import pandas as pd


def decompose(projected: Sequence[float], actual: Sequence[float]) -> dict[str, float]:
    """
    Split projection error into irreducible scatter and model error.

    A *perfect* projection of a count still misses, because the count is
    random: a true mean of 5.2 strikeouts produces 3s and 8s. Poisson variance
    equals the mean, so subtracting it from MSE leaves the part of the error the
    model is actually responsible for. This is the quantity MODEL_ERROR_K names,
    and the gate every NO CALL decision runs through.
    """
    pairs = [(float(p), float(a)) for p, a in zip(projected, actual)
             if p is not None and a is not None and not (pd.isna(p) or pd.isna(a))]
    n = len(pairs)
    if not n:
        return {"n": 0}

    mse = sum((p - a) ** 2 for p, a in pairs) / n
    poisson_var = sum(p for p, _ in pairs) / n
    return {
        "n": n,
        "mse": mse,
        "rmse": math.sqrt(mse),
        "poisson": math.sqrt(max(0.0, poisson_var)),
        # Negative under the root means the observed scatter is smaller than
        # Poisson noise alone — the model cannot be shown to add error at all.
        "model_err": math.sqrt(max(0.0, mse - poisson_var)),
        "bias": sum(p - a for p, a in pairs) / n,
        "mae": sum(abs(p - a) for p, a in pairs) / n,
    }


def se_of_model_error(d: dict[str, float]) -> float:
    """
    Standard error on the model-error estimate.

    Reported so a difference between two versions is not read as real when it
    is inside the noise of measuring it.
    """
    n, err = d.get("n", 0), d.get("model_err", 0.0)
    if not n or err <= 0:
        return float("nan")
    return d["mse"] / (math.sqrt(2 * n) * 2 * err)


def brier(p: Sequence[float], y: Sequence[int]) -> float:
    """Mean squared error of a probability forecast. Lower is better."""
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    if not len(p):
        return float("nan")
    return float(((p - y) ** 2).mean())


def calibration(p: Sequence[float], y: Sequence[int], bins: int = 6) -> dict[str, Any]:
    """
    Do stated probabilities match observed frequencies?

    When the model says 58%, does it happen 58% of the time? Returns the
    reliability table plus a **sampling-noise floor**: with a small sample the
    observed rate in a bin scatters even under a perfect model, and a gap
    smaller than that floor is not evidence of miscalibration. Reporting the
    gap without the floor is how small samples get over-read.
    """
    frame = pd.DataFrame({"p": np.asarray(p, dtype=float), "y": np.asarray(y, dtype=float)}).dropna()
    if frame.empty:
        return {"n": 0, "table": pd.DataFrame(), "rms_gap": float("nan"),
                "noise_floor": float("nan"), "resolvable": False}

    n_bins = max(1, min(bins, frame["p"].nunique()))
    frame["bin"] = pd.qcut(frame["p"], n_bins, duplicates="drop")
    table = frame.groupby("bin", observed=True).agg(
        n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean"),
    ).reset_index(drop=True)
    table["gap"] = table["predicted"] - table["observed"]

    weights = table["n"] / table["n"].sum()
    rms_gap = float(np.sqrt((weights * table["gap"] ** 2).sum()))
    noise = float(np.sqrt(
        (weights * table["predicted"] * (1 - table["predicted"]) / table["n"]).sum()
    ))
    return {
        "n": int(len(frame)),
        "table": table,
        "rms_gap": rms_gap,
        "noise_floor": noise,
        # False means the test cannot tell this model from a well-calibrated one.
        "resolvable": rms_gap > noise,
    }


def discrimination(p: Sequence[float], y: Sequence[int]) -> dict[str, float]:
    """
    Can the forecast tell these events apart at all?

    AUC is rank-based (0.50 = coin flip). The recalibration slope asks whether
    the *spread* of the predictions is real: a slope near 1 means a prediction
    of 0.7 really is more likely than one of 0.55; a slope near 0 means the
    model is quoting variation it does not have.
    """
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = ~(np.isnan(p) | np.isnan(y))
    p, y = p[ok], y[ok]

    out: dict[str, float] = {
        "n": int(len(p)), "auc": float("nan"), "slope": float("nan"),
        "brier": float("nan"), "brier_base": float("nan"), "skill": float("nan"),
        "base_rate": float("nan"), "sd": float("nan"), "information": float("nan"),
    }
    if len(p) == 0:
        return out

    base = float(y.mean())
    out["base_rate"] = base
    out["sd"] = float(p.std())
    out["brier"] = brier(p, y)
    out["brier_base"] = brier(np.full_like(p, base), y)
    out["skill"] = (1 - out["brier"] / out["brier_base"]) if out["brier_base"] > 0 else float("nan")

    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    if n_pos and n_neg:
        order = np.argsort(p)
        ranks = np.empty(len(p), dtype=float)
        ranks[order] = np.arange(1, len(p) + 1)
        # Average ranks over ties so a flat predictor scores 0.5, not better.
        ranks = pd.DataFrame({"p": p, "r": ranks}).groupby("p")["r"].transform("mean").to_numpy()
        out["auc"] = float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))

    if len(np.unique(p)) > 1 and n_pos and n_neg:
        clipped = np.clip(p, 1e-9, 1 - 1e-9)
        logit = np.log(clipped / (1 - clipped))
        design = np.column_stack([np.ones_like(logit), logit])
        beta = np.zeros(2)
        for _ in range(60):
            mu = 1 / (1 + np.exp(-design @ beta))
            w = np.clip(mu * (1 - mu), 1e-9, None)
            try:
                beta = beta + np.linalg.solve(
                    design.T @ (design * w[:, None]), design.T @ (y - mu))
            except np.linalg.LinAlgError:
                break
        out["slope"] = float(beta[1])
        out["information"] = abs(out["slope"]) * out["sd"]

    return out


def versus_market(
    model_p: Sequence[float],
    market_p: Sequence[float],
    y: Sequence[int],
) -> dict[str, Any]:
    """
    The question that decides whether any edge exists.

    Both forecasts are scored on the *same* events. If the model's Brier score
    is not lower than the de-vigged market's, the model has no information the
    price did not already carry, and no amount of edge arithmetic changes that.

    `beats_market` is deliberately strict: ties go to the market, which is the
    forecast you can get for free.

    A raw win is not enough, so the difference carries a **paired bootstrap
    confidence interval**. On the real 2026 sample the total-bases model "beat"
    the market by 0.0005 Brier — a win by any comparison that stops at the sign,
    and indistinguishable from zero once resampled. `distinguishable` is what
    the page should read, not `beats_market`.
    """
    frame = pd.DataFrame({
        "model": np.asarray(model_p, dtype=float),
        "market": np.asarray(market_p, dtype=float),
        "y": np.asarray(y, dtype=float),
    }).dropna()

    if frame.empty:
        return {"n": 0, "model_brier": float("nan"), "market_brier": float("nan"),
                "difference": float("nan"), "beats_market": False,
                "ci_low": float("nan"), "ci_high": float("nan"),
                "distinguishable": False}

    model_brier = brier(frame["model"], frame["y"])
    market_brier = brier(frame["market"], frame["y"])
    ci_low, ci_high = _paired_ci(
        frame["model"].to_numpy(), frame["market"].to_numpy(), frame["y"].to_numpy()
    )

    return {
        "n": int(len(frame)),
        "model_brier": model_brier,
        "market_brier": market_brier,
        # Positive means the model is better (its error is smaller).
        "difference": market_brier - model_brier,
        "beats_market": model_brier < market_brier,
        "ci_low": ci_low,
        "ci_high": ci_high,
        # The interval excludes zero, so the sign is not just resampling luck.
        "distinguishable": bool(ci_low > 0 or ci_high < 0),
    }


def _paired_ci(
    model_p: np.ndarray,
    market_p: np.ndarray,
    y: np.ndarray,
    resamples: int = 2000,
    seed: int = 7,
) -> tuple[float, float]:
    """
    95% interval on the Brier gap, resampling *events* rather than forecasts.

    Paired because both forecasts saw the same games: resampling them
    independently would throw away the pairing and widen the interval for no
    reason. Same approach as scripts/backtest_league_k.py's paired_ci.
    """
    n = len(y)
    if n < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    per_event = (market_p - y) ** 2 - (model_p - y) ** 2
    draws = rng.integers(0, n, size=(resamples, n))
    means = per_event[draws].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def sample_verdict(n: int, threshold: int = 30) -> str:
    """
    Plain-language statement of whether a sample can support a claim.

    The board already says this about CLV — "an anecdote, not a record, 20+
    before the sign means anything" — and every figure on the track record page
    deserves the same caveat before it is read.
    """
    if n == 0:
        return "No graded predictions yet."
    if n < threshold:
        return (f"{n} graded — an anecdote, not a record. "
                f"Around {threshold} before any of this means much.")
    return f"{n} graded."
