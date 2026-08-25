"""
Team win probability — the null model, built first and on purpose.

The prop models here were built and then measured, and the measurement said
they do not beat the market. This one is built the other way round: the
moneyline has been captured across nine books on every build since the
multi-book fix, `analysis.clv` can score a projection against the price it was
quoted at, and the grading loop settles outcomes nightly. The scoreboard exists
before the model does.

**This is the baseline, not the model.** Team run-scoring and run-prevention,
combined by log5, adjusted for home field. Nothing about who is pitching. That
omission is deliberate and is the whole point: the starting pitcher is the
largest remaining term, and a version that includes one has to beat this to
earn its place. `analysis.k_projections` keeps `project_blend` for exactly this
reason — a baseline you stop measuring is a baseline you can silently regress
past.

Everything here is a pure function of numbers. Nothing reads a file or a
network. The inputs it needs — runs scored, runs allowed, games played — come
from the standings endpoint, which carries them for all thirty teams.
"""

from __future__ import annotations

import math
from typing import Any

# Home advantage, as the home team's share of a matchup between equals.
#
# The textbook figure is .540 and it is out of date: the league-wide home
# winning percentage has drifted down for two decades and has sat near .530 in
# recent seasons. Using .540 would hand every home side about a point of
# probability it has not earned. Named rather than inlined so that when this is
# measured against the 28 stored moneylines it can be fitted rather than
# assumed.
HOME_FIELD_WIN_PCT = 0.530

# Pythagorean exponent floor. Pythagenpat derives the exponent from scoring
# environment rather than fixing it at 1.83, which matters at the extremes; the
# floor stops a division by zero for a team that has not scored yet.
MIN_RUNS_PER_GAME = 0.5


def pythagenpat_exponent(runs_scored: float, runs_allowed: float, games: int) -> float:
    """
    The exponent, derived from the scoring environment rather than assumed.

    Fixed-1.83 Pythagorean is a good approximation in an average run
    environment and drifts at the edges. Pythagenpat sets the exponent to
    (runs per game) ** 0.287, which is the standard correction and costs
    nothing to use.
    """
    if games <= 0:
        return 1.83
    rpg = max((float(runs_scored) + float(runs_allowed)) / games, MIN_RUNS_PER_GAME)
    return rpg ** 0.287


def pythagorean(runs_scored: float, runs_allowed: float, games: int = 0) -> float | None:
    """
    Expected winning percentage from runs scored and allowed.

    Used in preference to actual win-loss because it is the more predictive of
    the two: a team's record contains luck in one-run games that its run
    differential does not, and the question here is what the team is, not what
    it has been.

    None when there is nothing to compute from — an unplayed season is not a
    .500 team, and returning .500 would let a caller treat "no information" as
    "evenly matched".
    """
    rs, ra = float(runs_scored or 0), float(runs_allowed or 0)
    if rs <= 0 and ra <= 0:
        return None
    exp = pythagenpat_exponent(rs, ra, games)
    denom = rs ** exp + ra ** exp
    if denom <= 0:
        return None
    return (rs ** exp) / denom


def log5(p_a: float, p_b: float) -> float | None:
    """
    Probability A beats B, given each side's talent against a .500 opponent.

    Bill James's log5. The intuition worth keeping: two .600 teams playing each
    other produce a .500 game, and a .600 against a .400 is not .600 — it is
    .692, because the opponent's weakness compounds the favourite's strength.

    None rather than a guess when either input is missing, and .500 when both
    sides are perfect or hopeless, which is where the formula is undefined.
    """
    if p_a is None or p_b is None:
        return None
    a, b = float(p_a), float(p_b)
    denom = a + b - 2.0 * a * b
    if denom <= 0:
        return 0.5
    return (a - a * b) / denom


def apply_home_field(p: float | None, is_home: bool,
                     home_win_pct: float = HOME_FIELD_WIN_PCT) -> float | None:
    """
    Tilt a neutral-site probability toward the home side.

    Applied through log5 against the home advantage itself rather than by
    adding a flat few points. Adding is wrong at the extremes: a .950 favourite
    cannot gain three points of probability, and a flat term would happily push
    it past 1.0.
    """
    if p is None:
        return None
    edge = home_win_pct if is_home else (1.0 - home_win_pct)
    return log5(p, 1.0 - edge)


def win_probability(
    team_runs_scored: float, team_runs_allowed: float, team_games: int,
    opp_runs_scored: float, opp_runs_allowed: float, opp_games: int,
    is_home: bool,
    home_win_pct: float = HOME_FIELD_WIN_PCT,
) -> float | None:
    """
    The whole baseline: both teams' Pythagorean talent, log5, home field.

    Returns None if either side cannot be evaluated, because a moneyline
    priced against half a model is worse than no number at all — that is the
    failure the prop board's "NO LINE" state exists to avoid.
    """
    p_team = pythagorean(team_runs_scored, team_runs_allowed, team_games)
    p_opp = pythagorean(opp_runs_scored, opp_runs_allowed, opp_games)
    if p_team is None or p_opp is None:
        return None
    return apply_home_field(log5(p_team, p_opp), is_home, home_win_pct)


def implied_edge(model_p: float | None, market_p: float | None) -> float | None:
    """
    Model probability minus the de-vigged market's, in probability points.

    Deliberately returns the gap and nothing else. It does not decide whether
    the gap is worth acting on, because on this market nobody has yet measured
    what a plausible gap even looks like — the equivalent of
    MAX_PLAUSIBLE_EDGE_TB_PROB does not exist here and must not be invented.
    """
    if model_p is None or market_p is None:
        return None
    return (float(model_p) - float(market_p)) * 100.0


def summarise(model_p: float | None, market_p: float | None = None) -> dict[str, Any]:
    """A row's worth of numbers, for logging or rendering."""
    return {
        "model_win_prob": None if model_p is None else round(float(model_p), 4),
        "market_win_prob": None if market_p is None else round(float(market_p), 4),
        "edge_points": (None if (model_p is None or market_p is None)
                        else round(implied_edge(model_p, market_p), 2)),
    }
