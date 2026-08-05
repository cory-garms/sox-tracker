"""
Strikeout projections, written once for the backtests to compare.

Why these live apart from `analysis.betting`. `pitcher_strikeout_model` takes a
whole team's frame and returns a table with lines, edges and recommendations
attached. A walk-forward test needs a much smaller thing - "one pitcher, as of
one date, what do you project" - and bending the live model into that shape
would mean passing it filtered data and trusting the filter is the only
difference. Keeping the arithmetic visible and standalone here is what makes the
backtest auditable, and it is the same reason the original team-only backtest
carried its own copy.

The live model and `project_marcel` must therefore be kept in step by hand. That
is a deliberate trade: a duplicated formula that can be read in ten lines beats a
shared one that can only be verified by tracing three call sites.

Each function takes a `prior` frame of a pitcher's *previous* starts and returns
`(projected_strikeouts, projected_innings)`, or `(nan, nan)` when there is not
enough to project from. Nothing about the start being projected, or any start
after it, is ever visible.
"""

from __future__ import annotations

import pandas as pd

from analysis.betting import L5_REGRESSION_INNINGS

# Innings of league-average prior mixed into a pitcher's own rate. Pitcher
# strikeout rate is generally taken to stabilise somewhere near 70 batters
# faced, which is roughly 17-25 innings; 25 is the conservative end and is used
# rather than fitted, because fitting it on the same starts it is evaluated
# against is how a backtest starts flattering itself.
MARCEL_PRIOR_IP = 25.0


def innings(frame: pd.DataFrame) -> float:
    """
    Total innings pitched, in real thirds.

    `ip` is baseball notation - 6.1 means six and a third - so it can never be
    summed. `ip_outs` is the only safe column to aggregate.
    """
    if "ip_outs" in frame.columns:
        return float(frame["ip_outs"].sum()) / 3.0
    return float(frame["ip"].sum())


def project_blend(prior: pd.DataFrame, k_factor: float = 1.0) -> tuple[float, float]:
    """
    The season/last-5 blend, which is what shipped until 2026-08-04.

    Kept after being replaced because a baseline you have stopped measuring is a
    baseline you can silently regress past. If a future model cannot beat this,
    it has not earned the change.
    """
    tot_ip = innings(prior)
    if tot_ip <= 0:
        return float("nan"), float("nan")
    season_k9 = float(prior["so"].sum()) * 9.0 / tot_ip
    season_avg_ip = tot_ip / len(prior)

    last5 = prior.tail(5)
    l5_ip = innings(last5)
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


def project_marcel(
    prior: pd.DataFrame,
    league_k9: float,
    k_factor: float = 1.0,
    prior_ip: float = MARCEL_PRIOR_IP,
) -> tuple[float, float]:
    """
    Marcel-style projection: the pitcher's own K/9 regressed toward the league,
    weighted by how many innings stand behind it, applied to his own innings
    per start.

        k9 = (own_K * 9 + league_k9 * prior_ip) / (own_IP + prior_ip)

    Deliberately has no last-5 term. Measured over 2,347 held-out league starts
    it beats the blend by 0.16 K, and the blend's last-5 term earns nothing at
    all over a plain season average - so the regression is doing the work.
    """
    tot_ip = innings(prior)
    if tot_ip <= 0 or not league_k9:
        return float("nan"), float("nan")
    own_k = float(prior["so"].sum())
    k9 = (own_k * 9.0 + league_k9 * prior_ip) / (tot_ip + prior_ip)
    ip = tot_ip / len(prior)
    return k9 * k_factor * ip / 9.0, ip


def project_season(prior: pd.DataFrame) -> tuple[float, float]:
    """Plain season average - no blend, no regression. The null model."""
    tot_ip = innings(prior)
    if tot_ip <= 0:
        return float("nan"), float("nan")
    k9 = float(prior["so"].sum()) * 9.0 / tot_ip
    ip = tot_ip / len(prior)
    return k9 * ip / 9.0, ip


def project_league(prior: pd.DataFrame, league_k9: float) -> tuple[float, float]:
    """League average rate on the pitcher's own workload. Knows nothing."""
    tot_ip = innings(prior)
    if tot_ip <= 0 or not league_k9:
        return float("nan"), float("nan")
    ip = tot_ip / len(prior)
    return league_k9 * ip / 9.0, ip
