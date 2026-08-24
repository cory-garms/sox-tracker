"""
Closing line value for logged projections.

The one honest scoreboard for a model that has to wait on outcomes. Whether a
projection was *right* takes a game and a lot of them; whether the market moved
toward it is known the moment the line closes, and it is the question the
handbook says to answer before touching a model.

The bet log is the wrong instrument for it here. It holds eleven hand-logged
positions, and the guidance -- accumulate to n approximately 20 -- has been
blocking model work for weeks on that basis. But every priced projection ever
logged already carries the line and the de-vigged price it was quoted against,
and odds_history carries the same market again nearer first pitch. That is 180
distinct priced player-games rather than eleven, on data already on disk.

What this measures is narrower than a bet's CLV and should not be called one:
nobody staked anything, so there is no vig actually paid and no execution.
It measures whether the model's disagreement with the book anticipated the
book's own revision. A model with no information should score zero.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from client.odds_math import no_vig_probability

# Sides the model can take. A projection that agrees with the book exactly has
# no side and is excluded rather than counted as a coin flip.
SIDE_OVER = "over"
SIDE_UNDER = "under"


def _fair_over(row: Any) -> float | None:
    """De-vigged over-probability for one odds row, or None if it is one-sided."""
    over, under = row.get("over_odds"), row.get("under_odds")
    if over is None or under is None or pd.isna(over) or pd.isna(under):
        return None
    return no_vig_probability(over, under)[0]


def model_side(model_over_prob: float, book_over_prob: float) -> str | None:
    """
    Which way the model disagreed with the book, or None if it did not.

    This is the *direction* of the disagreement, not a recommendation. A row the
    board declined to call still has a side, and those rows are most of the
    sample -- excluding them would leave the measurement to the handful of
    projections confident enough to publish, which is the selection trap the
    track record page already documents one layer up.
    """
    if model_over_prob is None or book_over_prob is None:
        return None
    if pd.isna(model_over_prob) or pd.isna(book_over_prob):
        return None
    if model_over_prob == book_over_prob:
        return None
    return SIDE_OVER if model_over_prob > book_over_prob else SIDE_UNDER


def clv_points(side: str, quoted_fair_over: float, closing_fair_over: float) -> float:
    """
    Movement toward the model's side, in probability points.

    Positive means the book revised toward the model between the quote and the
    close: the model saw the revision coming. Signed by side, so an under that
    the market moved toward scores positive exactly as an over does.
    """
    move = (closing_fair_over - quoted_fair_over) * 100.0
    return move if side == SIDE_OVER else -move


def opening_and_closing(odds: pd.DataFrame) -> dict[tuple, tuple]:
    """
    First and last pre-game capture of each player-market, keyed the same way.

    Both ends come from odds_history rather than one from the projection log,
    and that is the whole correctness argument here. predictions_history keeps
    only the *last* pre-game capture per player-game -- latest_per_game, and
    rightly, since scoring wants the most informed projection -- but that is
    the same capture that becomes the close. Reading the quote off the
    projection and the close off the odds compares a price to itself: measured
    that way the archive reports 180 rows whose quote and close agree to four
    decimals, which is not a finding about the model.
    """
    pairs: dict[tuple, tuple] = {}
    if odds is None or odds.empty:
        return pairs

    df = odds.copy()
    df["captured_at"] = df["captured_at"].astype(str)
    if "commence_time" in df.columns:
        commence = df["commence_time"].astype(str)
        df = df[(commence == "") | commence.isna() | (df["captured_at"] < commence)]
    if df.empty:
        return pairs

    df = df.sort_values("captured_at")
    for key, g in df.groupby(["event_id", "market", "player"]):
        if len(g) < 2:
            continue                       # nothing moved because nothing was watched
        pairs[tuple(str(k) for k in key)] = (g.iloc[0], g.iloc[-1])
    return pairs


def attach_clv(predictions: pd.DataFrame, odds: pd.DataFrame) -> pd.DataFrame:
    """
    One row per priced player-game, with the movement the model anticipated.

    The model's over-probability is a function of its projection and the line,
    not of the price, so it is read off the projection log and is the same
    whichever capture it came from. The side is then fixed against the
    *opening* price and the movement measured to the close. Taking the side at
    the close instead would score the model against the number it is being
    tested on.

    Deduped to one row per player-game first: every build logs a snapshot, so
    the raw log holds the same player-game once per build and scoring it raw
    claims a sample several times larger than it is.
    """
    from data import predictions_history as ph

    if predictions is None or predictions.empty or odds is None or odds.empty:
        return pd.DataFrame()

    priced = predictions[predictions["line"].notna()]
    if priced.empty:
        return pd.DataFrame()
    priced = ph.latest_per_game(priced)

    ends = opening_and_closing(odds)
    if not ends:
        return pd.DataFrame()

    out: list[dict[str, Any]] = []
    for r in priced.to_dict(orient="records"):
        key = (str(r.get("event_id")), str(r.get("market")), str(r.get("player")))
        pair = ends.get(key)
        if pair is None:
            continue
        open_row, close_row = pair
        open_fair, close_fair = _fair_over(open_row), _fair_over(close_row)
        if open_fair is None or close_fair is None:
            continue

        # A line that moved is a different market. 4.5 K and 5.5 K are not two
        # prices for one question, and differencing their probabilities would
        # report the line move as though the model had predicted a price.
        line = r.get("line")
        for end in (open_row, close_row):
            if end.get("line") is None or pd.isna(end.get("line")):
                break
            if float(end["line"]) != float(line):
                break
        else:
            side = model_side(r.get("model_over_prob"), open_fair)
            if side is None:
                continue
            out.append({
                "game_date": r.get("game_date"),
                "market": r.get("market"),
                "player": r.get("player"),
                "line": line,
                "model_over_prob": r.get("model_over_prob"),
                "side": side,
                "open_fair_over": round(float(open_fair), 4),
                "close_fair_over": round(float(close_fair), 4),
                "clv_points": round(clv_points(side, float(open_fair), float(close_fair)), 3),
                "opened_at": str(open_row["captured_at"]),
                "closed_at": str(close_row["captured_at"]),
                "model_version": r.get("model_version", ""),
            })
    return pd.DataFrame(out)


def summarise(frame: pd.DataFrame) -> dict[str, Any]:
    """
    Mean movement toward the model, with the interval that says whether to
    believe it.

    The interval is the point. A positive mean on a small sample is what an
    informationless model produces half the time, and the whole reason this
    project keeps a track record page is that a number without one invites
    exactly that reading.
    """
    if frame is None or frame.empty:
        return {"n": 0}

    pts = frame["clv_points"].astype(float)
    n = len(pts)
    mean = float(pts.mean())
    sd = float(pts.std(ddof=1)) if n > 1 else 0.0
    se = sd / (n ** 0.5) if n > 1 else 0.0
    return {
        "n": n,
        "mean_points": round(mean, 3),
        "sd": round(sd, 3),
        "se": round(se, 3),
        # Normal interval: n is in the hundreds here, not the tens.
        "ci_low": round(mean - 1.96 * se, 3),
        "ci_high": round(mean + 1.96 * se, 3),
        "beat_close_pct": round(float((pts > 0).mean()) * 100.0, 1),
        "moved_at_all_pct": round(float((pts != 0).mean()) * 100.0, 1),
    }
