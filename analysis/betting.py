"""
Sports Betting & Prop Intelligence module — provides models for:
1. Pitcher Strikeout Over/Under (K/9 vs. opposing team K-rate & rolling trends).
2. First 5 Innings (F5) Starter Matchup Card.
3. NRFI / YRFI (No Run First Inning) 1st-inning run rate tracker.
"""

from __future__ import annotations

import logging
import math
import unicodedata
from typing import Any, TYPE_CHECKING
import pandas as pd

import config
from client.mlb_client import MLBClient
from client.odds_math import american_to_decimal, no_vig_probability
from analysis.matchup import fetch_game_preview, starter_season_summary

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


def pitcher_strikeout_model(
    pitching: pd.DataFrame,
    batting: pd.DataFrame,
    games: pd.DataFrame,
    client: MLBClient | None = None,
    odds_client: "OddsAPIClient | None" = None,
    team_id: int = config.TEAM_ID,
    season: int = config.SEASON,
    min_starts: int = MIN_STARTS_FOR_PROP,
) -> pd.DataFrame:
    """
    Strikeout prop model for the team's starting pitchers.

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
    if starters.empty:
        return pd.DataFrame()

    # One request for the whole slate, not one per pitcher.
    book_lines: dict[str, dict] = {}
    if odds_client is not None and odds_client.configured:
        try:
            event = odds_client.find_event(config.TEAMS.get(
                _ID_TO_ABBR.get(team_id, ""), {}).get("name", config.TEAM_NAME))
            if event:
                book_lines = odds_client.pitcher_strikeout_lines(event["id"])
        except Exception as e:                      # provider down / quota spent
            log.warning("Could not fetch strikeout prop lines: %s", e)

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

            try:
                our_era = float(s_our.get("era"))
            except (ValueError, TypeError):
                our_era = 4.00

            try:
                opp_era = float(s_opp.get("era"))
            except (ValueError, TypeError):
                opp_era = 4.00

            our_f5_exp = (our_era / 9.0) * 5.0
            opp_f5_exp = (opp_era / 9.0) * 5.0

            matchup_data = {
                "our_starter": s_our.get("name", "TBD"),
                "our_hand": s_our.get("hand", "R"),
                "our_era": s_our.get("era", "-"),
                "our_whip": s_our.get("whip", "-"),
                "our_f5_exp_runs": round(our_f5_exp, 2),
                "opp_starter": s_opp.get("name", "TBD"),
                "opp_hand": s_opp.get("hand", "R"),
                "opp_era": s_opp.get("era", "-"),
                "opp_whip": s_opp.get("whip", "-"),
                "opp_f5_exp_runs": round(opp_f5_exp, 2),
                "f5_total_proj": round(our_f5_exp + opp_f5_exp, 2),
                "f5_line_recommendation": "OVER 4.5 🟢" if (our_f5_exp + opp_f5_exp) > 4.5 else "UNDER 4.5 🔵",
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
# 4. Batter Total Bases & 1+ Hit Prop Model
# ---------------------------------------------------------------------------

def batter_total_bases_model(
    batting: pd.DataFrame,
    season: int = config.SEASON,
) -> pd.DataFrame:
    """
    Computes Total Bases (TB) and Hit prop hit rates for Red Sox hitters.
    TB formula: H + 2B + 2*3B + 3*HR.
    Evaluates:
    - Season TB per game & SLG
    - Last 10 games TB per game
    - Last 10 games Over 1.5 TB Hit % (games with 2+ Total Bases)
    - Last 10 games 1+ Hit Rate % (games with 1+ Hit)
    - Model recommendation for Over 1.5 TB prop
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

        # Calculate Total Bases for each game log row
        # H + 2B + 2*3B + 3*HR
        tb_series = sorted_g["h"] + sorted_g["doubles"] + (2 * sorted_g["triples"]) + (3 * sorted_g["hr"])
        sorted_g["tb"] = tb_series

        season_tb = int(tb_series.sum())
        season_tb_per_g = season_tb / games_cnt if games_cnt > 0 else 0.0
        season_avg = float(sorted_g["h"].sum() / sorted_g["ab"].sum()) if sorted_g["ab"].sum() > 0 else 0.0
        season_slg = float(season_tb / sorted_g["ab"].sum()) if sorted_g["ab"].sum() > 0 else 0.0

        # Last 10 games
        l10 = sorted_g.tail(10)
        l10_cnt = len(l10)
        l10_tb = int(l10["tb"].sum())
        l10_tb_per_g = l10_tb / l10_cnt if l10_cnt > 0 else season_tb_per_g

        l10_o15_tb = int((l10["tb"] >= 2).sum())
        l10_o15_tb_pct = (l10_o15_tb / l10_cnt * 100.0) if l10_cnt > 0 else 0.0

        l10_1hit = int((l10["h"] >= 1).sum())
        l10_1hit_pct = (l10_1hit / l10_cnt * 100.0) if l10_cnt > 0 else 0.0

        # Projected TB
        proj_tb = (season_tb_per_g * 0.4) + (l10_tb_per_g * 0.6)

        if proj_tb >= 1.65 or l10_o15_tb_pct >= 60.0:
            rec = "OVER 1.5 🔥"
        elif proj_tb <= 1.10 and l10_o15_tb_pct <= 30.0:
            rec = "UNDER 1.5 🧊"
        else:
            rec = "NEUTRAL ⚖️"

        rows.append({
            "player_id": pid,
            "player_name": pname,
            "games": games_cnt,
            "pa": tot_pa,
            "season_avg": round(season_avg, 3),
            "season_slg": round(season_slg, 3),
            "season_tb_g": round(season_tb_per_g, 2),
            "l10_tb_g": round(l10_tb_per_g, 2),
            "l10_o15_tb_pct": round(l10_o15_tb_pct, 1),
            "l10_1hit_pct": round(l10_1hit_pct, 1),
            "proj_tb": round(proj_tb, 2),
            "recommendation": rec,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("pa", ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 5. Home Run & RBI Prop Target Predictor
# ---------------------------------------------------------------------------

def batter_hr_rbi_props(
    batting: pd.DataFrame,
    season: int = config.SEASON,
) -> pd.DataFrame:
    """
    Tracks Home Run, RBI, and Run Scored prop metrics over last 10 games and season totals.
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

        hr_rating = "🚀 HIGH" if (l10_hr >= 2 or pa_per_hr <= 18.0) else ("MODERATE" if (l10_hr == 1 or pa_per_hr <= 28.0) else "LOW")

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
            "hr_rating": hr_rating,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("tot_hr", ascending=False).reset_index(drop=True)
    return df

