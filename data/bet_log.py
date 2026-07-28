"""
A record of what was bet, at what price, against what the model thought.

Why this exists. Both models on this page currently decline to call sides,
because each measured its own error and found it as large as the entire spread
of opinion it could demonstrate. There is no route from that state to a model
that *can* speak except measurement, and results are the noisiest possible way
to measure: a 55%-correct model and a coin flip are indistinguishable over an
evening, a week, or most months.

Closing line value is the standard escape from that problem. If a disagreement
with the opening line predicts which way the line then moves, the disagreement
carried information — and that verdict arrives per bet, at the close, instead of
after a season of results. So every row here stores three things: the price taken,
the model's probability at that moment, and (filled in later) the closing price.

Nothing in this module places a bet or knows whether money was involved. A row
with stake=0 is a paper bet and grades exactly like any other, which is the
point: the log should be able to measure an idea before it costs anything.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import config
from data import odds_history

log = logging.getLogger(__name__)

BET_LOG_PATH: Path = config.CACHE_DIR / "bet_log.parquet"

COLUMNS = [
    "placed_at",        # ISO-8601 UTC, when the row was written
    "event_id",         # ties the row to odds_history for line movement
    "game_date",
    "market",           # pitcher_strikeouts | batter_total_bases | h2h | ...
    "selection",        # player or team
    "side",             # Over | Under | Moneyline
    "line",             # None for a moneyline
    "price",            # American odds actually taken
    "book",
    "stake",            # 0.0 for a paper bet — it still grades
    "promo",            # "", "boost_50", "early_win_2run", ...
    "model_prob",       # what our model said, or NaN when it declined
    "consensus_prob",   # what the rest of the market said
    "closing_price",    # filled in by grade_from_history()
    "result",           # win | loss | push | void, filled in on settlement
    "notes",
]

_DTYPES: dict[str, str] = {
    "line": "float64",
    "price": "float64",
    "stake": "float64",
    "model_prob": "float64",
    "consensus_prob": "float64",
    "closing_price": "float64",
}


def _empty() -> pd.DataFrame:
    frame = pd.DataFrame(columns=COLUMNS)
    return frame.astype({k: v for k, v in _DTYPES.items() if k in frame.columns})


def load_log(path: Path | None = None) -> pd.DataFrame:
    """Every bet ever logged, or an empty frame with the right columns."""
    target = path or BET_LOG_PATH
    if not target.exists():
        return _empty()
    try:
        return pd.read_parquet(target)
    except Exception as e:                        # corrupt file beats no file
        log.warning("Could not read the bet log at %s: %s", target, e)
        return _empty()


def record_bet(
    selection: str,
    market: str,
    side: str,
    price: float,
    *,
    line: float | None = None,
    stake: float = 0.0,
    promo: str = "",
    book: str = "DraftKings",
    event_id: str = "",
    game_date: str = "",
    model_prob: float | None = None,
    consensus_prob: float | None = None,
    notes: str = "",
    path: Path | None = None,
) -> pd.DataFrame:
    """
    Append one bet and return the whole log.

    Appending rather than overwriting is deliberate and matches odds_history:
    the price you took is not reconstructible after the fact, so a row that is
    lost is lost permanently. Duplicate rows are allowed — betting the same
    selection twice at two prices is a real thing that happens, and silently
    collapsing them would misstate the position.
    """
    target = path or BET_LOG_PATH
    row = {
        "placed_at": datetime.now(timezone.utc).isoformat(),
        "event_id": event_id,
        "game_date": game_date,
        "market": market,
        "selection": selection,
        "side": side,
        "line": float(line) if line is not None else float("nan"),
        "price": float(price),
        "book": book,
        "stake": float(stake),
        "promo": promo,
        "model_prob": float(model_prob) if model_prob is not None else float("nan"),
        "consensus_prob": (
            float(consensus_prob) if consensus_prob is not None else float("nan")
        ),
        "closing_price": float("nan"),
        "result": "",
        "notes": notes,
    }
    frame = pd.concat([load_log(target), pd.DataFrame([row])], ignore_index=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, index=False)
    return frame


def grade_from_history(
    history: pd.DataFrame, path: Path | None = None
) -> pd.DataFrame:
    """
    Fill `closing_price` from the last odds snapshot taken before first pitch.

    "Closing" here means the latest price this repo actually observed, which is
    only as close to the real close as the build schedule allows — currently the
    last scheduled build lands roughly 90 minutes before a typical first pitch.
    That is a known understatement of CLV and is the reason a post-first-pitch
    build is worth adding; it is recorded here rather than hidden so the number
    is read with the right amount of trust.
    """
    frame = load_log(path)
    if frame.empty or history is None or history.empty:
        return frame

    for idx, bet in frame.iterrows():
        # Deliberately no "already graded, skip" guard. The last *pre-game*
        # snapshot keeps improving as first pitch approaches - a capture 34
        # minutes out is not a close, and one 13 minutes out is a better one -
        # and then stops improving forever the moment the game starts, because
        # no further pre-game snapshot can exist. Always recomputing therefore
        # converges on the true close and is idempotent afterwards, whereas
        # skipping graded rows froze whichever early snapshot happened to land
        # first and quietly presented it as final.
        rows = history[
            (history["event_id"] == bet["event_id"])
            & (history["market"] == bet["market"])
            & (history["player"] == bet["selection"])
        ]
        if rows.empty:
            continue
        rows = odds_history.pre_game_only(rows).sort_values("captured_at")
        # The last *pre-game* snapshot, not simply the last one. Once
        # scripts/capture_close.py runs near first pitch, a delayed runner can
        # land after the game has started, and an in-play price is a different
        # market entirely — recording one as the close would quietly invert the
        # CLV of every bet on that game.
        if rows.empty:
            continue
        latest = rows.iloc[-1]
        side = str(bet["side"]).lower()
        close = latest["under_odds"] if side == "under" else latest["over_odds"]
        if pd.notna(close):
            frame.at[idx, "closing_price"] = float(close)

    target = path or BET_LOG_PATH
    if not frame.empty:
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(target, index=False)
    return frame


def clv_summary(frame: pd.DataFrame | None = None) -> dict[str, Any]:
    """
    Beat-the-close rate and average CLV in probability points.

    CLV is measured in implied probability rather than in odds because odds are
    not linear: -110 to -120 and +200 to +190 are not the same move, and
    averaging them as prices would weight the long ones out of all proportion.

    `n` is the number that decides whether the rest of this dict means anything.
    Twenty settled bets is an anecdote; the sign of a mean CLV over fewer than
    that should not be read as evidence in either direction.
    """
    from client.odds_math import american_to_implied_prob

    frame = load_log() if frame is None else frame
    graded = frame[frame["closing_price"].notna() & frame["price"].notna()]
    if graded.empty:
        return {"n": 0, "beat_close_pct": None, "mean_clv_points": None}

    taken = graded["price"].map(american_to_implied_prob)
    closed = graded["closing_price"].map(american_to_implied_prob)
    # Lower implied probability at the price you took = you got the better of it.
    clv = (closed - taken) * 100.0
    return {
        "n": int(len(graded)),
        "beat_close_pct": round(float((clv > 0).mean() * 100.0), 1),
        "mean_clv_points": round(float(clv.mean()), 2),
    }
