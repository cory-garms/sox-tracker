"""
Sports Betting & Prop Intelligence module — provides models for:
1. Pitcher Strikeout Over/Under (K/9 vs. opposing team K-rate & rolling trends).
2. First 5 Innings (F5) Starter Matchup Card.
3. NRFI / YRFI (No Run First Inning) 1st-inning run rate tracker.
4. Batter Total Bases, priced against the book's own line.

Every model here holds to one rule: a number is only published when something
real stands behind it. A projection is real work; an edge requires a line a
book actually quoted; and a *recommendation* requires the model's error to have
been measured against held-out data and to be smaller than the edge claimed.
Where a model cannot clear that bar it says so instead of picking a side.
"""

from __future__ import annotations

import logging
import math
import unicodedata
from typing import Any, TYPE_CHECKING

import numpy as np
import pandas as pd

import config
from client.mlb_client import MLBClient
from client.odds_math import american_to_decimal, no_vig_probability
from analysis.matchup import (
    fetch_doubleheader_previews,
    fetch_game_preview,
    starter_season_summary,
)

if TYPE_CHECKING:
    from client.odds_api_client import OddsAPIClient

log = logging.getLogger(__name__)

_ID_TO_ABBR: dict[int, str] = {v["id"]: k for k, v in config.TEAMS.items()}


# ---------------------------------------------------------------------------
# 1. Pitcher Strikeout Over/Under Model
# ---------------------------------------------------------------------------

MIN_STARTS_FOR_PROP = 3   # below this the rolling K/9 is noise, not signal

# Innings needed before a rolling K/9 split carries as much weight as the
# season rate. Pitcher strikeout rate is generally taken to stabilise somewhere
# around 60 IP; five starts is roughly half that, so a five-start split gets
# roughly a third of the weight rather than the 60% it used to be handed.
L5_REGRESSION_INNINGS = 60.0

# The model's own measured error bar, in strikeouts.
#
# Measured by walk-forward backtest over the 2026 cached starts: project each
# start from only the starts before it, then decompose the residual. Total RMSE
# was 2.63 K, of which 2.20 K is the irreducible Poisson scatter a perfect
# projection would still show. The rest — 1.43 K — is the model being wrong.
MODEL_ERROR_K = 1.43

# Floor: an edge must clear the model's own error before it counts as a signal.
# A gap smaller than the model's typical miss is indistinguishable from zero,
# and calling a side on it would be dressing up noise as a read.
MIN_EDGE_K = MODEL_ERROR_K

# Ceiling: above this the disagreement is a bug report rather than a betting
# edge. A liquid market does not misprice a starter's strikeout line by this
# much, so when the model claims it has, the model is what's broken.
MAX_PLAUSIBLE_EDGE_K = 1.5

# Note what those two lines mean together: the floor and the ceiling are almost
# the same number. Any edge big enough to clear this model's noise is already
# big enough to be implausible, so in practice it recommends nothing — which is
# the honest description of a model with a ±1.43 K error. The band is written as
# two named constants rather than hardcoded off, so that when an opponent K-rate
# adjustment (roadmap.md item 1) shrinks MODEL_ERROR_K, recommendations resume
# on their own — but only once the accuracy has been re-measured to justify it.


def _innings(frame: pd.DataFrame) -> float:
    """
    Total innings pitched, in real thirds.

    The `ip` column is baseball notation: 6.1 means six and one *third*, not
    six and one tenth. Summing that column as a decimal silently loses a third
    of an inning on every partial start — across this team's 2026 starts it
    understated the total by 13.5 IP, inflating every K/9 by ~2.7%. `ip_outs`
    is the unambiguous field, so derive innings from it and only fall back to
    the notation column if it is missing.
    """
    if "ip_outs" in frame.columns:
        return float(frame["ip_outs"].sum()) / 3.0
    return float(frame["ip"].sum())


def _poisson_over_push(mean: float, line: float) -> tuple[float, float]:
    """
    (P(strikeouts > line), P(strikeouts == line)) for a Poisson count.

    Strikeouts in a start are a count of independent-ish events, which makes
    Poisson the standard first approximation for this prop. It replaces the
    hand-picked "0.12 win probability per strikeout of edge" sensitivity the
    model used to carry — that constant was never fitted to anything, so the
    EV it produced had no defensible magnitude.

    Poisson assumes variance equals the mean. Real strikeout counts are a
    little overdispersed because innings pitched varies from start to start,
    so this runs slightly overconfident at the tails. It is an approximation,
    not a calibrated model, and the EV should be read as indicative.

    The push term is only non-zero on whole-number lines; books usually post
    half-points, where a push is impossible.
    """
    mean = max(float(mean), 1e-9)
    floor_line = math.floor(line)

    # Direct summation — strikeout counts are small, so this is exact and cheap.
    term = math.exp(-mean)          # P(X == 0)
    cdf = term
    for k in range(1, floor_line + 1):
        term *= mean / k            # P(X == k)
        cdf += term

    p_push = term if float(line).is_integer() else 0.0
    p_over = max(0.0, 1.0 - cdf)
    return p_over, p_push


def _prop_ev(p_win: float, p_push: float, american_odds: int) -> float:
    """
    Expected value percentage of a unit stake, accounting for pushes.

    Reduces to the plain (prob * decimal_odds - 1) form when p_push is 0.
    """
    profit = american_to_decimal(american_odds) - 1.0
    p_lose = max(0.0, 1.0 - p_win - p_push)
    return round((p_win * profit - p_lose) * 100.0, 2)


def probable_starters(
    client: MLBClient | None,
    team_id: int = config.TEAM_ID,
    date_str: str | None = None,
) -> list[dict[str, Any]]:
    """
    The team's probable starting pitcher(s) for `date_str`.

    Returns a list, not a single pitcher, because a doubleheader has two — and
    quietly dropping the second game's starter is exactly the class of
    doubleheader bug this repo has already been bitten by.

    Empty when no client is available, the lookup fails, or the probable is
    still listed as TBD. Callers should say so rather than guessing at a name.
    """
    if client is None or not date_str:
        return []
    try:
        previews = fetch_doubleheader_previews(client, team_id, date_str)
    except Exception as e:                      # network down, schedule missing
        log.warning("Could not read probable starters for %s: %s", date_str, e)
        return []

    starters: list[dict[str, Any]] = []
    for preview in previews:
        prob = (preview or {}).get("our_probable") or {}
        pid = prob.get("id")
        if pid:
            starters.append({"id": int(pid), "name": prob.get("name", "TBD")})
    return starters


def _match_prop_line(player_name: str, book_lines: dict[str, dict]) -> dict | None:
    """
    Look a pitcher up in the book's prop map. Exact match first, then a
    surname+initial fallback since books and MLB spell accents differently
    (e.g. "Jovani Moran" vs "Jovani Morán").
    """
    if not book_lines:
        return None
    if player_name in book_lines:
        return book_lines[player_name]

    def _key(n: str) -> str:
        parts = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower().split()
        return f"{parts[0][:1]}.{parts[-1]}" if parts else ""

    target = _key(player_name)
    for book_name, entry in book_lines.items():
        if _key(book_name) == target:
            return entry
    return None


MARKET_K = "pitcher_strikeouts"
MARKET_TB = "batter_total_bases"


def fetch_book_lines(
    odds_client: "OddsAPIClient | None",
    team_id: int = config.TEAM_ID,
) -> dict[str, Any]:
    """
    One trip to the odds provider for the whole page.

    Returns ``{"event": {...} | None, "pitcher_strikeouts": {...},
    "batter_total_bases": {...}}`` — the parsed line maps each model needs,
    plus the event they came from.

    Each model used to look the event up and fetch its own market, which meant
    repeating the lookup and left nowhere to log the snapshot from. The odds
    history log (data/odds_history.py) wants exactly this payload, so the fetch
    happens once, here, and the result is handed to whoever needs it.

    Never raises. A provider outage, a spent quota or a missing key degrades the
    page to projections-only, which every caller already handles.

    Cost: one API credit per market, so two per build.
    """
    empty: dict[str, Any] = {"event": None, MARKET_K: {}, MARKET_TB: {}}
    if odds_client is None or not getattr(odds_client, "configured", False):
        return empty

    try:
        team_name = config.TEAMS.get(
            _ID_TO_ABBR.get(team_id, ""), {}
        ).get("name", config.TEAM_NAME)
        event = odds_client.find_event(team_name)
    except Exception as e:                          # provider down / quota spent
        log.warning("Could not reach the odds provider: %s", e)
        return empty
    if not event:
        log.info("No upcoming event found for team %s", team_id)
        return empty

    out: dict[str, Any] = {"event": event, MARKET_K: {}, MARKET_TB: {}}
    for market, fetch in (
        (MARKET_K, odds_client.pitcher_strikeout_lines),
        (MARKET_TB, odds_client.batter_total_base_lines),
    ):
        try:
            out[market] = fetch(event["id"]) or {}
        except Exception as e:
            log.warning("Could not fetch %s lines: %s", market, e)
    return out


def pitcher_strikeout_model(
    pitching: pd.DataFrame,
    batting: pd.DataFrame,
    games: pd.DataFrame,
    client: MLBClient | None = None,
    book_lines: dict[str, dict] | None = None,
    team_id: int = config.TEAM_ID,
    season: int = config.SEASON,
    min_starts: int = MIN_STARTS_FOR_PROP,
    only_player_ids: set[int] | None = None,
) -> pd.DataFrame:
    """
    Strikeout prop model for the team's starting pitchers.

    `book_lines` is the parsed strikeout market from fetch_book_lines() —
    a map of pitcher name to line and prices. Passing it in rather than
    fetching here keeps every provider call in one place, so the same payload
    can be logged to the odds history.

    `only_player_ids` restricts the table to specific pitchers — in practice
    the probable starter(s) for the day, via probable_starters(). Without it
    every arm that has ever started qualifies, which sweeps in openers and
    long relievers who will not throw tonight and have no prop line.

    Projects strikeouts by blending the season and last-5-start K/9, weighting
    the rolling split by how many innings stand behind it, then applying the
    same blend to innings per start. That projection is compared to the
    *sportsbook's* line.

    Edge and EV are only produced when a real book line is available. Deriving
    the line from the projection (as an earlier version did) makes the edge
    identically zero by construction and the resulting "EV" meaningless, so when
    no line is available this reports the projection and nothing else.

    Projections that disagree with the market by more than MAX_PLAUSIBLE_EDGE_K
    are flagged for review rather than recommended — see the guard below.

    Known gap: there is still no opponent, park, or platoon adjustment
    (roadmap.md item 1), so the projection is a pitcher-only estimate and will
    read high against teams that strike out less than average.
    """
    if pitching.empty:
        return pd.DataFrame()

    starters = pitching[pitching["is_starter"] == True].copy()
    if only_player_ids is not None:
        starters = starters[starters["player_id"].isin(only_player_ids)]
    if starters.empty:
        return pd.DataFrame()

    book_lines = book_lines or {}

    rows = []
    for (pid, pname), group in starters.groupby(["player_id", "player_name"]):
        starts_cnt = len(group)
        if starts_cnt < min_starts:
            continue

        sorted_starts = group.sort_values("game_date", ascending=True)
        tot_ip = _innings(sorted_starts)
        tot_so = int(sorted_starts["so"].sum())

        season_k9 = (tot_so * 9.0 / tot_ip) if tot_ip > 0 else 0.0
        season_avg_ip = tot_ip / starts_cnt if starts_cnt > 0 else 0.0

        # Last 5 starts rolling
        last_5 = sorted_starts.tail(5)
        l5_ip = _innings(last_5)
        l5_so = int(last_5["so"].sum())
        l5_k9 = (l5_so * 9.0 / l5_ip) if l5_ip > 0 else season_k9
        l5_avg_ip = l5_ip / len(last_5) if len(last_5) > 0 else season_avg_ip

        # How much to trust the rolling split, by how many innings are behind
        # it. The old model handed the last five starts a flat 60% weight, which
        # is far too much confidence in ~30 innings.
        l5_weight = l5_ip / (l5_ip + L5_REGRESSION_INNINGS) if l5_ip > 0 else 0.0
        season_weight = 1.0 - l5_weight

        blended_k9 = (season_k9 * season_weight) + (l5_k9 * l5_weight)

        # Blend the workload with the *same* weights. The old model blended K/9
        # but then multiplied by the last-5 innings alone, so a pitcher who was
        # both striking out more and going deeper had both hot streaks
        # multiplied together. That compounding is what produced the 6.50
        # projection against a 4.5 line for a starter averaging 5.0 K a start.
        proj_ip = (season_avg_ip * season_weight) + (l5_avg_ip * l5_weight)

        proj_k = blended_k9 * (proj_ip / 9.0)

        row = {
            "player_id": pid,
            "player_name": pname,
            "starts": starts_cnt,
            "tot_ip": round(tot_ip, 1),
            "season_k9": round(season_k9, 2),
            "l5_k9": round(l5_k9, 2),
            "avg_ip_start": round(proj_ip, 2),
            "blended_k9": round(blended_k9, 2),
            "proj_k": round(proj_k, 2),
            "prop_line": None,
            "line_source": "No line available",
            "line_last_update": None,
            "american_odds": None,
            "edge": None,
            "ev_pct": None,
            "model_over_prob": None,
            "book_over_prob": None,
            "recommendation": "NO LINE ⏳",
            "has_line": False,
            "flagged": False,
        }

        entry = _match_prop_line(pname, book_lines)
        if entry:
            line = float(entry["line"])
            over_odds = entry.get("over_odds")
            under_odds = entry.get("under_odds")
            edge_diff = proj_k - line

            # Fair (de-vigged) probability the book is quoting — the honest
            # benchmark to measure the model against.
            if over_odds is not None and under_odds is not None:
                fair_over, _ = no_vig_probability(over_odds, under_odds)
            else:
                fair_over = None

            p_over, p_push = _poisson_over_push(proj_k, line)
            p_under = max(0.0, 1.0 - p_over - p_push)

            # A disagreement this large is the model reporting its own bug, not
            # an edge a liquid market left lying around. Say so instead of
            # shouting OVER, and withhold the EV entirely — publishing a number
            # we have just declared untrustworthy is the failure mode this
            # whole branch exists to prevent.
            if abs(edge_diff) > MAX_PLAUSIBLE_EDGE_K:
                ev_pct, odds_used, flagged = None, over_odds, True
                rec = f"REVIEW ⚠️ ({edge_diff:+.1f} K vs market)"
            elif edge_diff >= MIN_EDGE_K and over_odds is not None:
                ev_pct = _prop_ev(p_over, p_push, over_odds)
                rec, odds_used, flagged = f"OVER ({ev_pct:+.1f}% EV) 🔥", over_odds, False
            elif edge_diff <= -MIN_EDGE_K and under_odds is not None:
                ev_pct = _prop_ev(p_under, p_push, under_odds)
                rec, odds_used, flagged = f"UNDER ({ev_pct:+.1f}% EV) 🧊", under_odds, False
            else:
                # Not "neutral" — the model has an opinion, it just cannot show
                # that opinion is worth more than its own error bar. Say that
                # rather than implying a coin flip.
                ev_pct, rec, odds_used, flagged = None, "NO CALL ⚖️", over_odds, False

            row.update({
                "prop_line": line,
                "line_source": f"{entry.get('book', 'Book')} 🟢",
                "line_last_update": entry.get("last_update"),
                "american_odds": f"{odds_used:+d}" if odds_used is not None else None,
                "edge": round(edge_diff, 2),
                "ev_pct": ev_pct,
                "model_over_prob": round(p_over, 4),
                "book_over_prob": round(fair_over, 4) if fair_over is not None else None,
                "recommendation": rec,
                "has_line": True,
                "flagged": flagged,
            })

        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("tot_ip", ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 2. First 5 Innings (F5) Starter Matchup Card
# ---------------------------------------------------------------------------

def _prorated_f5_runs(era: Any) -> float | None:
    """
    A starter's ERA prorated to five innings, or None when no ERA is available.

    This is *not* a measured first-five split — the cached box scores carry no
    inning breakdown — and starters are typically worse the third time through
    the order, so it runs optimistic about the fifth inning. Named and returned
    as an estimate for that reason.

    Returning None matters: an unreadable ERA used to fall back to a flat 4.00,
    which put a made-up number on the page in the one situation where the page
    knew nothing.
    """
    try:
        return round((float(era) / 9.0) * 5.0, 2)
    except (ValueError, TypeError):
        return None


def first_5_innings_analysis(
    pitching: pd.DataFrame,
    games: pd.DataFrame,
    client: MLBClient | None = None,
    team_id: int = config.TEAM_ID,
    season: int = config.SEASON,
    date_str: str | None = None,
) -> dict[str, Any]:
    """
    Extracts First 5 Innings (F5) statistics for Red Sox starters and upcoming matchup.
    """
    if pitching.empty:
        return {"starters": pd.DataFrame(), "matchup": {}}

    starters = pitching[pitching["is_starter"] == True].copy()
    if starters.empty:
        return {"starters": pd.DataFrame(), "matchup": {}}

    rows = []
    for (pid, pname), group in starters.groupby(["player_id", "player_name"]):
        starts = len(group)
        if starts == 0:
            continue

        tot_ip = _innings(group)
        tot_er = int(group["er"].sum())
        tot_h = int(group["h"].sum())
        tot_bb = int(group["bb"].sum())
        tot_so = int(group["so"].sum())
        avg_gs = float(group["game_score"].mean()) if "game_score" in group.columns else 50.0

        era = (tot_er * 9.0 / tot_ip) if tot_ip > 0 else 0.0
        whip = ((tot_h + tot_bb) / tot_ip) if tot_ip > 0 else 0.0
        k9 = (tot_so * 9.0 / tot_ip) if tot_ip > 0 else 0.0

        # These are full-start rates prorated to five innings, NOT true
        # first-five splits — the cached box scores have no inning breakdown.
        # Starters tend to be worse the third time through the order, so this
        # runs slightly pessimistic against a real F5 number. Named plainly so
        # nobody reads them as measured F5 splits.
        f5_exp_er = (era / 9.0) * 5.0
        avg_ip = tot_ip / starts

        rows.append({
            "player_id": pid,
            "player_name": pname,
            "starts": starts,
            "tot_ip": round(tot_ip, 1),
            "avg_ip": round(avg_ip, 2),
            "era": round(era, 2),
            "whip": round(whip, 2),
            "k9": round(k9, 2),
            "avg_game_score": round(avg_gs, 1),
            "f5_exp_runs": round(f5_exp_er, 2),
        })

    starters_df = pd.DataFrame(rows)
    if not starters_df.empty:
        starters_df = starters_df.sort_values("starts", ascending=False).reset_index(drop=True)

    matchup_data = {}
    if client and date_str:
        preview = fetch_game_preview(client, team_id, date_str)
        if preview:
            our_prob = preview.get("our_probable", {})
            opp_prob = preview.get("opp_probable", {})

            s_our = starter_season_summary(client, our_prob.get("id"), season)
            s_opp = starter_season_summary(client, opp_prob.get("id"), season)

            our_f5_exp = _prorated_f5_runs(s_our.get("era"))
            opp_f5_exp = _prorated_f5_runs(s_opp.get("era"))
            both = None
            if our_f5_exp is not None and opp_f5_exp is not None:
                both = round(our_f5_exp + opp_f5_exp, 2)

            # No f5_line_recommendation. It used to compare this total against a
            # hardcoded 4.5 that no book had quoted, and the total itself is
            # prorated full-start ERA rather than a measured first-five split —
            # a bet call built on two numbers that were never real. The estimate
            # is still worth showing, labelled as the estimate it is.
            matchup_data = {
                "our_starter": s_our.get("name", "TBD"),
                "our_hand": s_our.get("hand", "R"),
                "our_era": s_our.get("era", "-"),
                "our_whip": s_our.get("whip", "-"),
                "our_f5_exp_runs": our_f5_exp,
                "opp_starter": s_opp.get("name", "TBD"),
                "opp_hand": s_opp.get("hand", "R"),
                "opp_era": s_opp.get("era", "-"),
                "opp_whip": s_opp.get("whip", "-"),
                "opp_f5_exp_runs": opp_f5_exp,
                "f5_total_proj": both,
            }

    return {
        "starters": starters_df,
        "matchup": matchup_data,
    }


# ---------------------------------------------------------------------------
# 3. NRFI / YRFI (No Run First Inning) Tracker
# ---------------------------------------------------------------------------

def _empty_nrfi() -> dict[str, Any]:
    """Zeroed NRFI payload used whenever first-inning data can't be established."""
    return {
        "total_games": 0, "nrfi_count": 0, "yrfi_count": 0,
        "nrfi_pct": 0.0, "home_nrfi_pct": 0.0, "away_nrfi_pct": 0.0,
        "last_10_nrfi": 0.0, "game_logs": pd.DataFrame(), "starter_records": pd.DataFrame(),
        "available": False,
    }


def nrfi_yrfi_tracker(
    games: pd.DataFrame,
    pitching: pd.DataFrame,
    client: MLBClient | None = None,
    team_id: int = config.TEAM_ID,
    season: int = config.SEASON,
) -> dict[str, Any]:
    """
    Tracks 1st inning run rates (NRFI: No Run First Inning / YRFI: Yes Run First Inning).

    Requires an MLBClient — first-inning runs come from each game's linescore.
    Games whose linescore can't be read are excluded from the rate entirely.
    """
    if games.empty:
        return _empty_nrfi()

    completed = games[games["status"] == "Final"].sort_values("game_date").copy()
    if completed.empty:
        return _empty_nrfi()

    # First-inning runs only exist in the linescore — there is no way to derive
    # them from the cached game log. Without a client, report unavailable rather
    # than approximating from full-game totals.
    if client is None:
        log.info("NRFI tracker needs an MLBClient to read linescores; skipping.")
        return _empty_nrfi()

    game_rows = []
    skipped = 0
    for _, g in completed.iterrows():
        gp = int(g["game_pk"])
        opp_id = int(g["opponent_id"])

        try:
            ls = client.get_linescore(gp)
            innings = ls.get("innings", [])
            if not innings:
                skipped += 1
                continue
            f1 = innings[0]
            r1_away = int(f1.get("away", {}).get("runs", 0) or 0)
            r1_home = int(f1.get("home", {}).get("runs", 0) or 0)
        except Exception as e:
            # Dropping the game keeps the rate honest; defaulting to 0 would
            # silently count every failed fetch as a NRFI.
            log.warning("Linescore unavailable for game %s: %s", gp, e)
            skipped += 1
            continue

        tot_r1 = r1_away + r1_home
        is_nrfi = (tot_r1 == 0)

        game_rows.append({
            "game_pk": gp,
            "game_date": g["game_date"],
            "is_home": bool(g["is_home"]),
            "opponent_abbr": _ID_TO_ABBR.get(opp_id, str(opp_id)),
            "r1_away": r1_away,
            "r1_home": r1_home,
            "tot_r1": tot_r1,
            "is_nrfi": is_nrfi,
            "result_str": "NRFI 🚫" if is_nrfi else "YRFI 💥",
        })

    if skipped:
        log.info("NRFI tracker: %d of %d games had no usable linescore",
                 skipped, len(completed))

    logs_df = pd.DataFrame(game_rows)
    if logs_df.empty:
        return _empty_nrfi()
    total_games = len(logs_df)
    nrfi_count = int(logs_df["is_nrfi"].sum())
    yrfi_count = total_games - nrfi_count

    nrfi_pct = (nrfi_count / total_games * 100.0) if total_games > 0 else 0.0

    home_games = logs_df[logs_df["is_home"] == True]
    away_games = logs_df[logs_df["is_home"] == False]

    home_nrfi_pct = (home_games["is_nrfi"].sum() / len(home_games) * 100.0) if len(home_games) > 0 else 0.0
    away_nrfi_pct = (away_games["is_nrfi"].sum() / len(away_games) * 100.0) if len(away_games) > 0 else 0.0

    last_10 = logs_df.tail(10)
    last_10_nrfi = (last_10["is_nrfi"].sum() / len(last_10) * 100.0) if len(last_10) > 0 else 0.0

    starter_rows = []
    if not pitching.empty:
        starters = pitching[pitching["is_starter"] == True]
        merged = logs_df.merge(starters[["game_pk", "player_name", "player_id"]], on="game_pk", how="inner")
        for (pid, pname), s_group in merged.groupby(["player_id", "player_name"]):
            s_total = len(s_group)
            s_nrfi = int(s_group["is_nrfi"].sum())
            s_yrfi = s_total - s_nrfi
            s_pct = (s_nrfi / s_total * 100.0) if s_total > 0 else 0.0
            starter_rows.append({
                "player_id": pid,
                "player_name": pname,
                "starts": s_total,
                "nrfi_count": s_nrfi,
                "yrfi_count": s_yrfi,
                "nrfi_record": f"{s_nrfi}-{s_yrfi}",
                "nrfi_pct": round(s_pct, 1),
            })

    starter_records = pd.DataFrame(starter_rows)
    if not starter_records.empty:
        starter_records = starter_records.sort_values("starts", ascending=False).reset_index(drop=True)

    return {
        "total_games": total_games,
        "nrfi_count": nrfi_count,
        "yrfi_count": yrfi_count,
        "nrfi_pct": round(nrfi_pct, 1),
        "home_nrfi_pct": round(home_nrfi_pct, 1),
        "away_nrfi_pct": round(away_nrfi_pct, 1),
        "last_10_nrfi": round(last_10_nrfi, 1),
        "game_logs": logs_df,
        "starter_records": starter_records,
        "available": True,
    }


# ---------------------------------------------------------------------------
# 4. Batter Total Bases — priced against the book's own line
# ---------------------------------------------------------------------------

MIN_PA_FOR_TB_PROP = 20   # below this the per-PA rates are noise, not signal

# How much prior to regress a hitter's per-PA outcome mix toward the team's own
# rates, in plate appearances. Swept out of sample by walk-forward backtest at
# 0, 25, 50, 100, 200 and 400 PA: every value from 25 to 200 lands within 0.004
# TB of the others (MAE 1.270-1.274) and all of them beat no regression at all
# (1.284). 50 is the lightest prior that collects that improvement, which is the
# right side to err on for a model whose problem is already too little
# separation between hitters. scripts/backtest_batter_tb.py reproduces the sweep.
TB_REGRESSION_PA = 50.0

# The model's own measured error, in probability points, on the question the
# market actually asks: will this hitter clear the total-bases line?
#
# Measured by walk-forward backtest over the 2026 cached starts (project each
# start from only the starts before it, 714 held-out starts). Bootstrapping each
# hitter's own prior sample puts the standard deviation of the model's own
# over-probability at 0.049 — that is how much the number moves on resampling
# the very data it was built from. A reliability check agreed to within its own
# resolution: the measured calibration gap was 0.032 against a sampling-noise
# floor of 0.043, so nothing finer than about four points can even be resolved
# by this test. The floor is the larger of the two.
MODEL_ERROR_TB_PROB = 0.049

# Floor: an edge over the book's de-vigged price must clear the model's own
# error before it counts as a signal.
MIN_EDGE_TB_PROB = MODEL_ERROR_TB_PROB

# Ceiling: past here the disagreement is a bug report, not an edge — and unlike
# the strikeout model's ceiling this one is measured rather than judged. Out of
# sample the model's over-probabilities have a standard deviation of 0.069, and
# a logistic recalibration slope of 0.74 says only about three quarters of that
# spread is real information: 0.74 x 0.069 = 0.051. That is the entire range of
# genuine opinion the model has been shown to hold, so a claimed edge larger
# than it is a claim the model has no standing to make.
MAX_PLAUSIBLE_EDGE_TB_PROB = 0.051

# Note what those two lines mean together, exactly as for strikeouts: the floor
# and the ceiling are almost the same number. Two tenths of a percentage point
# separate them, so the window an edge would have to land in is narrower than
# the rounding on either constant, and in practice the model calls nothing.
# That is unsurprising: it has no opposing-pitcher, park or platoon
# context while the book's price does, and its out-of-sample AUC on "will this
# hitter clear 1.5 bases" is 0.57 against 0.50 for a coin flip. Recommendations
# resume on their own if a sharper model re-measures these constants apart —
# not before, and never by editing them here.

# Bases by hit type, in the order the mix vector carries them.
_TB_BASES = (1, 2, 3, 4)


def _total_bases(frame: pd.DataFrame) -> pd.Series:
    """Total bases per row: H + 2B + 2*3B + 3*HR (`h` already counts each hit)."""
    return frame["h"] + frame["doubles"] + (2 * frame["triples"]) + (3 * frame["hr"])


def _lineup_starts(batting: pd.DataFrame) -> pd.DataFrame:
    """
    Only the games a hitter started.

    A total-bases prop is offered on a hitter who is in the lineup, so the rate
    that matters is per *start*. Averaging over pinch-hit and bench games —
    which the old model did — quietly divided every regular's production by
    games they never batted in, and gave bench players a projection built almost
    entirely from one-plate-appearance cameos.
    """
    if "batting_order" in batting.columns:
        return batting[batting["batting_order"] >= 1]
    return batting[batting["pa"] > 0]


def _per_pa_mix(frame: pd.DataFrame) -> tuple[float, float, float, float] | None:
    """
    Per-plate-appearance probability of a single, double, triple and home run.

    None when there are no plate appearances to divide by.
    """
    pa = float(frame["pa"].sum())
    if pa <= 0:
        return None
    singles = float((frame["h"] - frame["doubles"] - frame["triples"] - frame["hr"]).sum())
    return (
        max(singles, 0.0) / pa,
        float(frame["doubles"].sum()) / pa,
        float(frame["triples"].sum()) / pa,
        float(frame["hr"].sum()) / pa,
    )


def _regress_mix(
    mix: tuple[float, float, float, float],
    pa: float,
    prior_mix: tuple[float, float, float, float] | None,
    prior_pa: float = TB_REGRESSION_PA,
) -> tuple[float, float, float, float]:
    """
    Shrink a hitter's own rates toward the team's, weighting by sample size.

    A hitter with 400 PA keeps almost all of his own shape; one with 40 PA is
    pulled most of the way to the team's. The prior is the team's own measured
    mix, not a made-up league constant.
    """
    if prior_mix is None or prior_pa <= 0:
        return mix
    denom = pa + prior_pa
    return tuple(  # type: ignore[return-value]
        ((m * pa) + (p * prior_pa)) / denom for m, p in zip(mix, prior_mix)
    )


def _pa_distribution(frame: pd.DataFrame) -> dict[int, int]:
    """How often the hitter has had 1, 2, 3... plate appearances in a start."""
    counts = frame.loc[frame["pa"] > 0, "pa"].astype(int).value_counts().to_dict()
    return {int(k): int(v) for k, v in counts.items()}


def _tb_pmf(
    mix: tuple[float, float, float, float],
    pa_counts: dict[int, int],
) -> np.ndarray:
    """
    Distribution of total bases in a start.

    Each plate appearance is one draw from {out, single, double, triple, homer}
    with the hitter's own probabilities, so the total over n appearances is an
    n-fold convolution of that per-PA distribution — and the number of
    appearances is itself uncertain, so the result is mixed over how often the
    hitter has had each count.

    This replaces comparing a point projection to a line, which for total bases
    is close to meaningless: books post 1.5 for nearly every hitter and move the
    *price*, not the number. The question is what probability to put on clearing
    it, so the model has to produce a distribution.

    The independence assumption is the same approximation Poisson is for
    strikeouts: plate appearances within a game share a pitcher, a park and a
    lineup, so real total bases are somewhat more clustered than this. It is a
    first approximation, not a calibrated model.
    """
    total_weight = float(sum(pa_counts.values()))
    if total_weight <= 0:
        return np.array([1.0])

    p_out = max(0.0, 1.0 - sum(mix))
    per_pa = np.array([p_out, *mix], dtype=float)

    max_pa = max(pa_counts)
    out = np.zeros(4 * max_pa + 1)
    current = np.array([1.0])
    for n in range(1, max_pa + 1):
        current = np.convolve(current, per_pa)
        weight = pa_counts.get(n, 0)
        if weight:
            out[: len(current)] += (weight / total_weight) * current
    return out


def _pmf_mean(pmf: np.ndarray) -> float:
    return float((pmf * np.arange(len(pmf))).sum())


def _pmf_over_push(pmf: np.ndarray, line: float) -> tuple[float, float]:
    """(P(total bases > line), P(total bases == line)) — pushes need a whole line."""
    floor_line = int(math.floor(line))
    if floor_line >= len(pmf):
        return 0.0, 0.0
    p_over = float(pmf[floor_line + 1:].sum())
    p_push = float(pmf[floor_line]) if float(line).is_integer() else 0.0
    return p_over, p_push


def project_batter_tb(
    player_starts: pd.DataFrame,
    team_mix: tuple[float, float, float, float] | None = None,
) -> dict[str, Any] | None:
    """
    Project one hitter's total bases in a start, as a full distribution.

    Returns None when there is nothing to project from. The projection is the
    mean of the distribution, so the number on the page and the probability
    behind it can never drift apart.

    Kept separate from the table-building model so that
    scripts/backtest_batter_tb.py measures the code that actually ships, rather
    than a re-implementation of it that could quietly disagree.
    """
    if player_starts.empty:
        return None
    pa = float(player_starts["pa"].sum())
    mix = _per_pa_mix(player_starts)
    pa_counts = _pa_distribution(player_starts)
    if mix is None or not pa_counts:
        return None

    regressed = _regress_mix(mix, pa, team_mix)
    pmf = _tb_pmf(regressed, pa_counts)
    return {
        "pmf": pmf,
        "proj_tb": _pmf_mean(pmf),
        "mix": regressed,
        "pa": pa,
        "starts": len(player_starts),
    }


def batter_total_bases_model(
    batting: pd.DataFrame,
    book_lines: dict[str, dict] | None = None,
    season: int = config.SEASON,
    min_pa: int = MIN_PA_FOR_TB_PROP,
) -> pd.DataFrame:
    """
    Total-bases prop model for the team's hitters, priced against real lines.

    `book_lines` is the parsed batter_total_bases market from
    fetch_book_lines(). Without it the table publishes projections and says no
    line was available — it never invents one. The 1.5 it used to assume was
    exactly that: an invented line, with hand-picked 1.65-projection and
    60%-hit-rate thresholds standing in for an edge nobody had measured.

    With a line, the model compares its own over-probability to the book's
    de-vigged price and reports the gap. It calls a side only when that gap
    clears MIN_EDGE_TB_PROB, the model's own measured error — which, as the
    constants above record, it essentially never does.
    """
    if batting.empty:
        return pd.DataFrame()

    starts = _lineup_starts(batting)
    if starts.empty:
        return pd.DataFrame()

    book_lines = book_lines or {}
    # The regression prior is the team's own per-PA mix, measured from the same
    # frame — nothing imported from outside the data.
    team_mix = _per_pa_mix(starts)

    rows = []
    for (pid, pname), group in starts.groupby(["player_id", "player_name"]):
        tot_pa = int(group["pa"].sum())
        if tot_pa < min_pa:
            continue

        sorted_g = group.sort_values("game_date", ascending=True).copy()
        sorted_g["tb"] = _total_bases(sorted_g)
        starts_cnt = len(sorted_g)

        projection = project_batter_tb(sorted_g, team_mix)
        if projection is None:
            continue

        abs_ = float(sorted_g["ab"].sum())
        season_avg = float(sorted_g["h"].sum()) / abs_ if abs_ > 0 else 0.0
        season_slg = float(sorted_g["tb"].sum()) / abs_ if abs_ > 0 else 0.0
        tb_per_start = float(sorted_g["tb"].sum()) / starts_cnt

        l10 = sorted_g.tail(10)
        l10_cnt = len(l10)
        l10_tb_start = float(l10["tb"].sum()) / l10_cnt if l10_cnt else tb_per_start
        l10_o15_tb_pct = float((l10["tb"] >= 2).sum()) / l10_cnt * 100.0 if l10_cnt else 0.0
        l10_1hit_pct = float((l10["h"] >= 1).sum()) / l10_cnt * 100.0 if l10_cnt else 0.0

        row = {
            "player_id": pid,
            "player_name": pname,
            "starts": starts_cnt,
            "pa": tot_pa,
            "season_avg": round(season_avg, 3),
            "season_slg": round(season_slg, 3),
            "tb_per_start": round(tb_per_start, 2),
            "l10_tb_start": round(l10_tb_start, 2),
            "l10_o15_tb_pct": round(l10_o15_tb_pct, 1),
            "l10_1hit_pct": round(l10_1hit_pct, 1),
            "proj_tb": round(projection["proj_tb"], 2),
            "prop_line": None,
            "line_source": "No line available",
            "line_last_update": None,
            "american_odds": None,
            "model_over_prob": None,
            "book_over_prob": None,
            "prob_edge": None,
            "ev_pct": None,
            "recommendation": "NO LINE ⏳",
            "has_line": False,
            "flagged": False,
        }

        entry = _match_prop_line(pname, book_lines)
        if entry:
            line = float(entry["line"])
            over_odds = entry.get("over_odds")
            under_odds = entry.get("under_odds")

            p_over, p_push = _pmf_over_push(projection["pmf"], line)
            p_under = max(0.0, 1.0 - p_over - p_push)

            if over_odds is not None and under_odds is not None:
                fair_over, _ = no_vig_probability(over_odds, under_odds)
            else:
                fair_over = None

            # The edge lives in probability space, not in bases. Every hitter's
            # line is 1.5; what separates them is the price, so "projection
            # minus line" would rank hitters by quality the book has already
            # charged for.
            edge = (p_over - fair_over) if fair_over is not None else None

            if edge is None:
                ev_pct, odds_used, flagged = None, over_odds, False
                rec = "NO CALL ⚖️"
            elif abs(edge) > MAX_PLAUSIBLE_EDGE_TB_PROB:
                ev_pct, odds_used, flagged = None, over_odds, True
                rec = f"REVIEW ⚠️ ({edge * 100:+.1f} pts vs market)"
            elif edge >= MIN_EDGE_TB_PROB and over_odds is not None:
                ev_pct = _prop_ev(p_over, p_push, over_odds)
                rec, odds_used, flagged = f"OVER ({ev_pct:+.1f}% EV) 🔥", over_odds, False
            elif edge <= -MIN_EDGE_TB_PROB and under_odds is not None:
                ev_pct = _prop_ev(p_under, p_push, under_odds)
                rec, odds_used, flagged = f"UNDER ({ev_pct:+.1f}% EV) 🧊", under_odds, False
            else:
                ev_pct, rec, odds_used, flagged = None, "NO CALL ⚖️", over_odds, False

            row.update({
                "prop_line": line,
                "line_source": f"{entry.get('book', 'Book')} 🟢",
                "line_last_update": entry.get("last_update"),
                "american_odds": f"{odds_used:+d}" if odds_used is not None else None,
                "model_over_prob": round(p_over, 4),
                "book_over_prob": round(fair_over, 4) if fair_over is not None else None,
                "prob_edge": round(edge, 4) if edge is not None else None,
                "ev_pct": ev_pct,
                "recommendation": rec,
                "has_line": True,
                "flagged": flagged,
            })

        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        # Hitters the book actually quoted come first — they are the only rows
        # with anything to price.
        df = df.sort_values(["has_line", "pa"], ascending=[False, False]).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 5. Home Run, RBI and Runs — usage and form
# ---------------------------------------------------------------------------

def batter_hr_rbi_props(
    batting: pd.DataFrame,
    season: int = config.SEASON,
) -> pd.DataFrame:
    """
    Home run, RBI and run-scored rates over the season and the last 10 games.

    Rate stats only. This used to end in a `hr_rating` of HIGH / MODERATE / LOW,
    keyed off "2 homers in the last 10 games" or "one per 18 plate appearances"
    — thresholds nobody measured, rendered as a badge that read like a pick
    against a home-run line the page never fetched. The rates underneath are
    honest usage and form numbers, so they stay; the verdict on top does not.
    """
    if batting.empty:
        return pd.DataFrame()

    rows = []
    for (pid, pname), group in batting.groupby(["player_id", "player_name"]):
        tot_pa = int(group["pa"].sum())
        if tot_pa < 20:
            continue

        sorted_g = group.sort_values("game_date", ascending=True)
        games_cnt = len(sorted_g)

        tot_hr = int(sorted_g["hr"].sum())
        tot_rbi = int(sorted_g["rbi"].sum())
        tot_r = int(sorted_g["r"].sum())

        pa_per_hr = (tot_pa / tot_hr) if tot_hr > 0 else 999.0

        # Last 10 games
        l10 = sorted_g.tail(10)
        l10_cnt = len(l10)
        l10_hr = int(l10["hr"].sum())
        l10_rbi = int(l10["rbi"].sum())
        l10_r = int(l10["r"].sum())

        l10_rbi_hit_pct = ((l10["rbi"] >= 1).sum() / l10_cnt * 100.0) if l10_cnt > 0 else 0.0
        l10_r_hit_pct = ((l10["r"] >= 1).sum() / l10_cnt * 100.0) if l10_cnt > 0 else 0.0

        rows.append({
            "player_id": pid,
            "player_name": pname,
            "games": games_cnt,
            "pa": tot_pa,
            "tot_hr": tot_hr,
            "pa_per_hr": round(pa_per_hr, 1) if pa_per_hr < 900 else "-",
            "l10_hr": l10_hr,
            "l10_rbi": l10_rbi,
            "l10_rbi_hit_pct": round(l10_rbi_hit_pct, 1),
            "l10_r_hit_pct": round(l10_r_hit_pct, 1),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("tot_hr", ascending=False).reset_index(drop=True)
    return df

