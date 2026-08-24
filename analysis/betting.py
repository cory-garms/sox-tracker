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
from client.odds_api_client import (
    MARKET_H2H,
    _parse_player_lines,
    parse_player_lines_by_book,
    parse_two_way_by_book,
)
from data import odds_history
from data.opponent import opponent_k_factor
from client.odds_math import (
    american_to_decimal,
    consensus_probability,
    early_win_token_ev,
    no_vig_probability,
    profit_boost_ev,
)
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
# season rate. No longer used by the strikeout projection, which regresses
# toward the league instead (see MARCEL_PRIOR_IP); kept because the retired
# blend is still measured as a baseline in analysis/k_projections.py, and a
# baseline you stop measuring is one you can silently regress past.
L5_REGRESSION_INNINGS = 60.0

# Innings of league-average prior mixed into a pitcher's own rate. Pitcher
# strikeout rate is generally taken to stabilise near 70 batters faced, roughly
# 17-25 innings; 25 is the conservative end, and is chosen rather than fitted
# because fitting it on the same starts it is evaluated against is how a
# backtest starts flattering itself.
MARCEL_PRIOR_IP = 25.0

# The model's own measured error bar, in strikeouts.
#
# Re-measured 2026-08-04 by scripts/backtest_league_k.py over 2,347 held-out
# starts by 201 starters - the whole league, not one team. Project each start
# from only the starts before it, then decompose the residual: total RMSE
# 2.27 K, of which 2.23 K is the irreducible Poisson scatter a perfect
# projection would still show. The rest is the model being wrong.
#
# Why the number fell from 1.39, and why that is not the model improving:
# 1.39 was measured on 73 Boston starts, where the standard error is +/-0.41 K.
# Its 95% interval spans 0.57-2.21, which contains the value measured here for
# the same model (0.68 K). The old constant was mostly small-sample noise. The
# league-wide test has SE +/-0.12 K, which is what makes any of this decidable.
#
# What changed in the model, measured as a paired bootstrap over the same
# starts (95% CI on the MSE gap, K^2):
#
#   the last-5 term earned nothing        blend vs season     [-0.018, +0.058]
#   regression to the league mean helps   blend vs marcel     [+0.114, +0.308]
#   the opponent factor helps             marcel vs +opp      [+0.016, +0.121]
#   the change as a whole                 blend vs marcel+opp [+0.167, +0.383]
#
# So the shipped model is Marcel + opponent factor. Note the second line
# especially: the opponent adjustment was previously recorded here as measuring
# "no help". That was a limit of a 73-start test, not a property of the
# adjustment, exactly as the note it replaced suspected.
#
# Re-measured 2026-08-23, same script, now over 3,001 held-out starts by 216
# starters as the season has filled in: marcel+opp 0.366 K (SE +/-0.179),
# against 0.45 measured on 2,347 starts three weeks earlier. Rounded to 0.37.
# The two intervals overlap heavily, so this is the same quantity measured
# better, not the model improving.
#
# ⚠️ Lowering this floor makes the page speak MORE, and the published record
# does not yet support that. analysis/scoring.py over our own 24 graded
# strikeout predictions reports AUC 0.415 and a recalibration slope of -0.319 —
# the ordering is backwards on that sample. Those measure different things:
# 0.366 K is projection accuracy over 3,001 starts, the AUC is probability
# discrimination over 24. The large sample wins on the question it answers, and
# the small one is a warning that the *probability* layer may be the weak part
# rather than the projection. See the Track Record page; revisit when n is
# past ~100.
MODEL_ERROR_K = 0.37

# Floor: an edge must clear the model's own error before it counts as a signal.
# A gap smaller than the model's typical miss is indistinguishable from zero,
# and calling a side on it would be dressing up noise as a read.
MIN_EDGE_K = MODEL_ERROR_K

# Ceiling: above this the disagreement is a bug report rather than a betting
# edge. A liquid market does not misprice a starter's strikeout line by this
# much, so when the model claims it has, the model is what's broken.
MAX_PLAUSIBLE_EDGE_K = 1.5

# Note what those two lines mean together. Until 2026-08-04 the floor (1.39)
# and the ceiling (1.5) were nearly the same number, so the band between them
# was empty and the page recommended nothing at all — the honest description of
# a model whose error had never been measured precisely enough to beat. They
# were written as two named constants rather than hardcoded off precisely so
# that a properly re-measured error would reopen the band on its own, without
# anyone having to decide the page should start speaking.
#
# That is what has now happened: 0.45 against a 1.5 ceiling leaves a real band,
# and the page calls sides again for the first time. Nothing about the gating
# logic changed to allow it — only the measurement did. If a future
# re-measurement pushes MODEL_ERROR_K back up toward the ceiling, the page
# should fall silent again by the same mechanism, and that is correct.


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


def _side_call(direction: str, p_win: float, p_push: float, odds: int) -> tuple[str, float]:
    """
    Name a side the model likes -- but only as a bet if the price pays for it.

    Clearing the model's own error bar means it has an opinion. It does not mean
    the opinion is worth money at the number actually quoted, and those are
    different claims. Ranger Suarez projected 4.99 K against a 4.5 line on
    2026-08-24, cleared MIN_EDGE_K, and the board printed
    "OVER (-5.9% EV) 🔥" -- a flame on a bet the same line of code had just
    computed to lose 5.9 cents on the dollar. The model's own over-probability
    was 55.71% against the book's de-vigged 55.88%, so there was no edge to
    have; the K-unit gate simply never looked at the price.

    Negative EV is not a weaker OVER, it is not an OVER. The book has already
    taken that side of the disagreement and charged for it, which is worth
    saying plainly rather than dressing as a pick.
    """
    ev = _prop_ev(p_win, p_push, odds)
    if ev <= 0:
        return f"PRICED OUT ({ev:+.1f}% EV) 🏷️", ev
    return f"{direction} ({ev:+.1f}% EV) {'🔥' if direction == 'OVER' else '🧊'}", ev


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

    out: dict[str, Any] = {"event": event, MARKET_K: {}, MARKET_TB: {}, "by_book": {}}
    for market in (MARKET_K, MARKET_TB):
        try:
            # Parse the payload twice rather than fetching twice: the request
            # already returns every US book at the same one-credit cost, so the
            # consensus benchmark is free and only the parsing differs.
            payload = odds_client.get_event_props(event["id"], markets=market)
            out["by_book"][market] = parse_player_lines_by_book(payload, market)
            out[market] = _parse_player_lines(
                payload, market, book=odds_client.bookmaker
            ) or {}
        except Exception as e:
            log.warning("Could not fetch %s lines: %s", market, e)

    # The moneyline is the third credit. It earns it: an early-win token only
    # applies to a moneyline, so without this the promotion section can only
    # price the promotion it is not being offered.
    try:
        payload = odds_client.get_event_props(event["id"], markets=MARKET_H2H)
        by_book = parse_two_way_by_book(payload, MARKET_H2H)
        out["by_book"][MARKET_H2H] = by_book
        # Single-book view as well, so the moneyline reaches the odds history.
        # Without it a moneyline bet can be logged but never graded, because
        # grading reads the close out of that log.
        needle = odds_client.bookmaker.replace("_", " ").lower()
        out[MARKET_H2H] = {
            team: entry
            for team, books in by_book.items()
            for title, entry in books.items()
            if title.replace("_", " ").lower() == needle
        }
    except Exception as e:
        log.warning("Could not fetch moneyline: %s", e)
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
    opponent_logs: pd.DataFrame | None = None,
    opponent_team_id: int | None = None,
    as_of_date: str | None = None,
    league_k9: float | None = None,
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

    Projects strikeouts by regressing the pitcher's own K/9 toward the league
    mean by how many innings stand behind it (a Marcel-style projection),
    applying the opponent factor, then multiplying by his average innings per
    start. That projection is compared to the *sportsbook's* line.

    `league_k9` is the league starter K/9 the projection regresses toward, from
    data/league_pitching.py. Without it the projection cannot regress and falls
    back to the pitcher's own season rate — measurably worse, so pass it.

    Edge and EV are only produced when a real book line is available. Deriving
    the line from the projection (as an earlier version did) makes the edge
    identically zero by construction and the resulting "EV" meaningless, so when
    no line is available this reports the projection and nothing else.

    Projections that disagree with the market by more than MAX_PLAUSIBLE_EDGE_K
    are flagged for review rather than recommended — see the guard below.

    `opponent_logs` / `opponent_team_id` apply the opponent adjustment: the
    blended K/9 is multiplied by how much the lineup being faced strikes out
    relative to league average, regressed toward the league by sample size (see
    data/opponent.py). Omit them and the projection is pitcher-only, exactly as
    before - which read high against lineups that strike out less than average.

    `as_of_date` bounds the opponent rate to games before that date. It matters
    only in a backtest, and it matters absolutely there: an opponent rate that
    includes the game being projected would let the model see its own future
    and would make the measured error bar optimistic.

    Known gap: still no park or platoon adjustment (roadmap.md item 1). The
    opponent factor is a team-level K rate, not split by pitcher handedness.
    """
    if pitching.empty:
        return pd.DataFrame()

    starters = pitching[pitching["is_starter"] == True].copy()
    if only_player_ids is not None:
        starters = starters[starters["player_id"].isin(only_player_ids)]
    if starters.empty:
        return pd.DataFrame()

    book_lines = book_lines or {}

    # One factor for the whole table: every starter in it faces the same lineup
    # on the same day.
    k_factor = 1.0
    if opponent_logs is not None and opponent_team_id is not None:
        k_factor = opponent_k_factor(opponent_logs, opponent_team_id, before=as_of_date)

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

        # Reported for the page, not used by the projection. A rolling split is
        # what a reader wants to see; it is not what the model should trust.
        last_5 = sorted_starts.tail(5)
        l5_ip = _innings(last_5)
        l5_so = int(last_5["so"].sum())
        l5_k9 = (l5_so * 9.0 / l5_ip) if l5_ip > 0 else season_k9

        # Regress his own rate toward the league by the innings behind it. With
        # no league rate available there is nothing to regress toward, so this
        # degrades to his own season rate rather than inventing a prior.
        if league_k9 and tot_ip > 0:
            regressed_k9_own = ((tot_so * 9.0 + league_k9 * MARCEL_PRIOR_IP)
                                / (tot_ip + MARCEL_PRIOR_IP))
        else:
            regressed_k9_own = season_k9

        # Who he is facing. A league-average lineup leaves this untouched.
        blended_k9 = regressed_k9_own * k_factor

        # Workload is his own season average. It is deliberately NOT blended
        # with the last-5 innings: the old model blended K/9 but multiplied by
        # last-5 innings alone, so a pitcher both striking out more and going
        # deeper had two hot streaks multiplied together. That compounding is
        # what produced a 6.50 projection against a 4.5 line for a starter
        # averaging 5.0 K a start.
        proj_ip = season_avg_ip

        proj_k = blended_k9 * (proj_ip / 9.0)

        row = {
            "player_id": pid,
            "player_name": pname,
            "starts": starts_cnt,
            "tot_ip": round(tot_ip, 1),
            "season_k9": round(season_k9, 2),
            "l5_k9": round(l5_k9, 2),
            "avg_ip_start": round(proj_ip, 2),
            "blended_k9_own": round(regressed_k9_own, 2),
            "opp_k_factor": round(k_factor, 4),
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
                rec, ev_pct = _side_call("OVER", p_over, p_push, over_odds)
                odds_used, flagged = over_odds, False
            elif edge_diff <= -MIN_EDGE_K and under_odds is not None:
                rec, ev_pct = _side_call("UNDER", p_under, p_push, under_odds)
                odds_used, flagged = under_odds, False
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
#
# Re-measured 2026-08-23 over 935 held-out starts (was 714): parameter noise
# 0.0481, calibration gap 0.0250 against a 0.0377 noise floor. The floor is
# still the larger of the two, and barely moved.
MODEL_ERROR_TB_PROB = 0.048

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
#
# Re-measured 2026-08-23 over 935 held-out starts: sd 0.0682, slope 0.710,
# so 0.710 x 0.0682 = 0.048. The ceiling has come down to meet the floor.
MAX_PLAUSIBLE_EDGE_TB_PROB = 0.048

# Note what those two lines mean together, exactly as for strikeouts: the floor
# and the ceiling are now THE SAME NUMBER. Previously two tenths of a point
# separated them; as of the 2026-08-23 re-measurement the window an edge would
# have to land in has closed completely, and in practice the model calls nothing.
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
                rec, ev_pct = _side_call("OVER", p_over, p_push, over_odds)
                odds_used, flagged = over_odds, False
            elif edge <= -MIN_EDGE_TB_PROB and under_odds is not None:
                rec, ev_pct = _side_call("UNDER", p_under, p_push, under_odds)
                odds_used, flagged = under_odds, False
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



# ---------------------------------------------------------------------------
# Market consensus and promotions
# ---------------------------------------------------------------------------

# Minimum number of *other* books before a consensus is treated as a benchmark.
# Two books agreeing is a coincidence as often as a price; the edges that
# survive a wider sample are the ones worth showing.
MIN_CONSENSUS_BOOKS = 3

# Measured 2026-07-27 by scripts/measure_early_win_lift.py over 3,172 team-games
# of regular-season linescores: P(ever led by 2+ OR won) - P(won).
#
#   P(win)                 0.5000     <- exact, which is what validates the walk
#   P(ever led by 2+)      0.5400
#   P(either)              0.6028
#
# It is stored as a *lift* and not as a rate on purpose. A team's own
# P(ever up 2) is anchored to the schedule it happened to play and cannot be
# compared against tonight's price; the lift transfers, because it is the extra
# probability the token buys on top of whatever the market already thinks.
EARLY_WIN_LIFT_2RUN = 0.1028


def consensus_edge_table(
    by_book: dict[str, dict[str, dict[str, Any]]],
    primary_book: str = "DraftKings",
    boost_pct: float = 50.0,
    min_books: int = MIN_CONSENSUS_BOOKS,
) -> pd.DataFrame:
    """
    Price the book we bet at against the rest of the market.

    This is the one section of the page whose edge does not depend on a model
    being right. Every book is de-vigged on its own and the median of the
    *others* becomes the fair benchmark — the primary book is excluded from its
    own benchmark, or a price would be measured partly against itself.

    Returns one row per (player, side) with the raw EV at the primary book's
    price and the EV the same bet would carry under a profit boost. An empty
    frame when nothing has enough books to compare.
    """
    rows: list[dict[str, Any]] = []
    needle = primary_book.replace("_", " ").lower()

    for market, players in (by_book or {}).items():
        for player, books in (players or {}).items():
            primary = next(
                (e for b, e in books.items() if b.replace("_", " ").lower() == needle),
                None,
            )
            if not primary:
                continue
            # A moneyline carries no number, and parse_two_way_by_book already
            # emits each team once with its own price as `over_odds`. Pricing
            # the "under" too would just re-list the opponent's own row.
            is_moneyline = primary.get("line") is None
            sides = (("over_odds", "under_odds"),) if is_moneyline else (
                ("over_odds", "under_odds"), ("under_odds", "over_odds")
            )
            for side, other_side in sides:
                price = primary.get(side)
                if price is None or primary.get(other_side) is None:
                    continue
                # Only books quoting the *same* number are comparable: an over
                # 5.5 and an over 6.5 are different bets, and averaging them
                # would invent a price nobody offers.
                quotes = [
                    (e[side], e[other_side])
                    for b, e in books.items()
                    if b.replace("_", " ").lower() != needle
                    and e.get("line") == primary["line"]
                    and e.get(side) is not None
                    and e.get(other_side) is not None
                ]
                if len(quotes) < min_books:
                    continue
                fair = consensus_probability(quotes)
                if fair is None:
                    continue
                rows.append(
                    {
                        "market": market,
                        "player": player,
                        "line": primary["line"],
                        "side": (
                            "Moneyline" if is_moneyline
                            else "Over" if side == "over_odds" else "Under"
                        ),
                        "price": int(price),
                        "consensus_prob": fair,
                        "n_books": len(quotes),
                        "ev_pct": round(
                            ((fair * american_to_decimal(price)) - 1.0) * 100.0, 2
                        ),
                        "ev_boost_pct": profit_boost_ev(fair, price, boost_pct),
                    }
                )

    if not rows:
        return pd.DataFrame(
            columns=[
                "market", "player", "line", "side", "price", "consensus_prob",
                "n_books", "ev_pct", "ev_boost_pct",
            ]
        )
    return pd.DataFrame(rows).sort_values("ev_pct", ascending=False).reset_index(drop=True)


def promo_comparison(
    fair_prob: float,
    american_odds: int | float,
    boost_pct: float = 50.0,
    lift: float = EARLY_WIN_LIFT_2RUN,
) -> dict[str, float]:
    """
    Value the two promotion types on the same selection so they can be compared
    on one number instead of on intuition.

    Both are worth more on longer prices, for different reasons: a profit boost
    multiplies a payout that is already large, while a token adds a fixed slab
    of probability that is then paid at those same long odds. The comparison is
    therefore price-dependent and has to be recomputed per selection rather than
    settled once.
    """
    raw = round(((fair_prob * american_to_decimal(american_odds)) - 1.0) * 100.0, 2)
    return {
        "raw_ev_pct": raw,
        "boost_ev_pct": profit_boost_ev(fair_prob, american_odds, boost_pct),
        "token_ev_pct": early_win_token_ev(fair_prob, american_odds, lift),
    }


# ---------------------------------------------------------------------------
# What actually moved
# ---------------------------------------------------------------------------

# Below this, a move is not worth a reader's attention. Books re-post prices
# constantly and a fraction of a point is churn, not an opinion changing.
MIN_MOVE_POINTS = 0.8


def biggest_movers(
    history: pd.DataFrame,
    event_id: str,
    top_n: int = 5,
    min_points: float = MIN_MOVE_POINTS,
) -> pd.DataFrame:
    """
    The most significant line movement for one event, ranked.

    Two decisions are doing the work here.

    **Movement is measured in de-vigged probability, not in odds.** A move from
    -110 to -120 and one from +200 to +190 are similar as prices and very
    different as bets, so ranking on odds would order the list by how long the
    prices happened to be. Both sides of every market are stored, so each
    snapshot is de-vigged before the two are differenced — which also means a
    book merely widening its margin does not register as an opinion changing,
    because a wider margin moves both sides and cancels.

    **A line move is not a price move.** 5.5 strikeouts to 6.5 is a different
    bet; -125 to -115 is the same bet repriced. They are not commensurable, so
    line moves are flagged separately and always sort first rather than being
    converted into some shared score that would imply a false equivalence.

    Returns columns: market, player, opened_at, current_at, open_line,
    current_line, open_price, current_price, points, line_moved.
    Empty when nothing has two snapshots or nothing cleared `min_points`.
    """
    cols = ["market", "player", "opened_at", "current_at", "open_line",
            "current_line", "open_price", "current_price", "points", "line_moved"]
    if history is None or history.empty:
        return pd.DataFrame(columns=cols)

    rows_out: list[dict[str, Any]] = []
    # Pre-game only. A build that runs mid-game records in-play prices, and
    # those are a different market - once a lineup has batted, a total-bases
    # price quotes the rest of a game rather than the whole of one. Including
    # them reported 10-point "moves" nobody could have bet.
    scoped = odds_history.pre_game_only(
        history[history["event_id"] == str(event_id)]
    )
    for (market, player), rows in scoped.groupby(["market", "player"], sort=False):
        rows = rows.sort_values("captured_at")
        if len(rows) < 2:
            continue
        first, last = rows.iloc[0], rows.iloc[-1]

        def _devig(row) -> float | None:
            over, under = row["over_odds"], row["under_odds"]
            if pd.isna(over) or pd.isna(under):
                return None
            return no_vig_probability(over, under)[0]

        p_open, p_now = _devig(first), _devig(last)
        if p_open is None or p_now is None:
            continue

        open_line = None if pd.isna(first["line"]) else float(first["line"])
        current_line = None if pd.isna(last["line"]) else float(last["line"])
        line_moved = open_line != current_line
        points = (p_now - p_open) * 100.0

        # A line move is always worth reporting; a price move has to clear the
        # churn floor first.
        if not line_moved and abs(points) < min_points:
            continue

        rows_out.append({
            "market": market,
            "player": player,
            "opened_at": first["captured_at"],
            "current_at": last["captured_at"],
            "open_line": open_line,
            "current_line": current_line,
            "open_price": _safe_price(first["over_odds"]),
            "current_price": _safe_price(last["over_odds"]),
            "points": round(points, 2),
            "line_moved": bool(line_moved),
        })

    if not rows_out:
        return pd.DataFrame(columns=cols)

    frame = pd.DataFrame(rows_out)
    frame["_rank"] = frame["points"].abs()
    # Line moves first, then by magnitude of the repricing.
    frame = frame.sort_values(["line_moved", "_rank"], ascending=[False, False])
    return frame.drop(columns="_rank").head(top_n).reset_index(drop=True)


def _safe_price(value) -> int | None:
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
