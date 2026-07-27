"""
Sportsbook odds conversion math — pure functions, no I/O.

Shared by every odds provider so the conversion logic lives in exactly one place.
"""

from __future__ import annotations

import math


def _clean_odds(odds: int | float) -> float | None:
    """
    Coerce an odds value to a usable float, or None if it isn't one.

    float("nan") converts without raising and then poisons every downstream
    comparison — nan < 0 is False, so a NaN would silently sail through as a
    positive price and yield a NaN probability. Reject non-finite values here.
    """
    try:
        value = float(odds)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(value) or value == 0:
        return None
    return value


def american_to_implied_prob(odds: int | float) -> float:
    """
    Convert American odds (e.g. -115 or +130) to implied probability (0.0-1.0).

    Note this is the *vigged* probability — the book's margin is baked in, so a
    two-sided market's implied probabilities sum to >1. Use no_vig_probability()
    when you need a fair baseline.
    """
    value = _clean_odds(odds)
    if value is None:
        return 0.50
    if value < 0:
        return abs(value) / (abs(value) + 100.0)
    return 100.0 / (value + 100.0)


def american_to_decimal(odds: int | float) -> float:
    """Convert American odds to a decimal payout multiplier (+100 -> 2.0)."""
    value = _clean_odds(odds)
    if value is None:
        return 2.0
    if value > 0:
        return (value / 100.0) + 1.0
    return (100.0 / abs(value)) + 1.0


def no_vig_probability(odds_a: int | float, odds_b: int | float) -> tuple[float, float]:
    """
    Strip the bookmaker's margin from a two-sided market.

    Given both sides' American odds, return (prob_a, prob_b) normalised to sum
    to 1.0 — the book's own fair estimate of each outcome. This is the honest
    benchmark to measure a model against; comparing to a single vigged side
    systematically understates edge.
    """
    p_a = american_to_implied_prob(odds_a)
    p_b = american_to_implied_prob(odds_b)
    total = p_a + p_b
    if total <= 0:
        return (0.50, 0.50)
    return (p_a / total, p_b / total)


def calculate_ev(model_prob: float, american_odds: int | float) -> float:
    """
    Expected value percentage of a unit stake.

        EV = (model_prob * decimal_odds) - 1

    Returns a percentage (8.0 == +8% EV). Only meaningful when `american_odds`
    are *real book odds* and `model_prob` comes from something independent of
    those odds — running this against a self-derived line yields a number that
    looks like an edge but measures nothing.
    """
    return round(((model_prob * american_to_decimal(american_odds)) - 1.0) * 100.0, 2)


# ---------------------------------------------------------------------------
# Consensus pricing
# ---------------------------------------------------------------------------

def consensus_probability(quotes: list[tuple[int | float, int | float]]) -> float | None:
    """
    Fair probability of a side from several books' two-sided quotes.

    `quotes` is [(side_odds, other_side_odds), ...] — one pair per book. Each
    book is de-vigged on its own before the books are combined, because a book
    with a fat margin would otherwise drag the average toward its own price
    rather than its own opinion.

    The median is used rather than the mean: one book posting a stale or
    erroneous number should not move the benchmark that number is measured
    against. Returns None when fewer than two books are supplied, since a
    "consensus" of one is just that book's opinion wearing a different hat.
    """
    fair = [no_vig_probability(side, other)[0] for side, other in quotes]
    if len(fair) < 2:
        return None
    fair.sort()
    mid = len(fair) // 2
    if len(fair) % 2:
        return fair[mid]
    return (fair[mid - 1] + fair[mid]) / 2.0


# ---------------------------------------------------------------------------
# Promotions
#
# These matter because they are the only source of positive expectation on this
# page that does not require a model to be right. Both functions take a *fair*
# probability — supply the market consensus, not a projection, or the number
# they return measures the projection's error rather than the promotion's value.
# ---------------------------------------------------------------------------

def profit_boost_ev(fair_prob: float, american_odds: int | float, boost_pct: float = 50.0) -> float:
    """
    EV percentage of a unit stake on a bet carrying a profit boost.

    A profit boost multiplies winnings, not the stake, so the payout becomes
    1 + (1 + b)(d - 1) and the whole expression rearranges to

        EV_boost = (1 + b) * EV_raw + b * (1 - p)

    which is the useful form: a boost pays (1 + b) times whatever edge the bet
    already had, plus a term that grows as the probability *falls*. That second
    term dominates, and it is why a boost belongs on the longest fairly-priced
    selection available rather than the safest one — at a fair price a 50% boost
    on an even-money bet returns +25%, and the same boost on a +400 dog returns
    +40%.
    """
    b = boost_pct / 100.0
    raw = (fair_prob * american_to_decimal(american_odds)) - 1.0
    return round(((1.0 + b) * raw + b * (1.0 - fair_prob)) * 100.0, 2)


def early_win_token_ev(
    fair_prob: float, american_odds: int | float, lift: float
) -> float:
    """
    EV percentage of a unit stake on a moneyline carrying an "early win" token
    (the bet is graded a winner as soon as the team leads by the trigger margin,
    and otherwise settles normally).

    The token's value is an *additive* bump in win probability — the measured
    P(ever led by the margin OR won) minus P(won) — so its EV contribution is
    `lift * decimal_odds`. Like a profit boost it is therefore worth more on
    longer prices, and for the same reason.

    `lift` must come from a measurement over real games, not a guess: see
    scripts/measure_early_win_lift.py, which walks half-inning linescores.
    Season-average *rates* must not be substituted for it — a team's own
    P(ever up 2) is anchored to the schedule it happened to play, whereas the
    lift transfers across price levels.
    """
    return round(
        (((fair_prob + lift) * american_to_decimal(american_odds)) - 1.0) * 100.0, 2
    )
