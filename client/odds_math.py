"""
Sportsbook odds conversion math — pure functions, no I/O.

Shared by every odds provider so the conversion logic lives in exactly one place.
"""

from __future__ import annotations


def american_to_implied_prob(odds: int | float) -> float:
    """
    Convert American odds (e.g. -115 or +130) to implied probability (0.0-1.0).

    Note this is the *vigged* probability — the book's margin is baked in, so a
    two-sided market's implied probabilities sum to >1. Use no_vig_probability()
    when you need a fair baseline.
    """
    try:
        odds = float(odds)
    except (ValueError, TypeError):
        return 0.50
    if odds == 0:
        return 0.50
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 100.0 / (odds + 100.0)


def american_to_decimal(odds: int | float) -> float:
    """Convert American odds to a decimal payout multiplier (+100 -> 2.0)."""
    try:
        odds = float(odds)
    except (ValueError, TypeError):
        return 2.0
    if odds == 0:
        return 2.0
    if odds > 0:
        return (odds / 100.0) + 1.0
    return (100.0 / abs(odds)) + 1.0


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
