"""
Pre-game matchup analysis module — evaluates upcoming game matchups,
probable pitcher comparisons, platoon advantages, bullpen rest, and head-to-head records.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from typing import Any

from config import TEAMS, TEAM_ID
from client.mlb_client import MLBClient
from analysis.offense import platoon_table, pivoted_platoon_summary


_ID_TO_ABBR: dict[int, str] = {v["id"]: k for k, v in TEAMS.items()}

# First pitch is reported in the team's home timezone regardless of where the
# game is played — a Boston reader wants to know when to turn it on, not what
# the clock says in Seattle.
TEAM_TZ = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Game Preview Metadata
# ---------------------------------------------------------------------------

def _parse_single_preview(
    raw_game: dict[str, Any],
    team_id: int,
    date_str: str,
    game_n: int = 1,
) -> dict[str, Any]:
    """Helper to convert a raw MLB API schedule game dict into a clean preview structure."""
    if not raw_game:
        return {}

    teams = raw_game.get("teams", {})
    home = teams.get("home", {})
    away = teams.get("away", {})

    home_id = home.get("team", {}).get("id")
    away_id = away.get("team", {}).get("id")

    is_home = (home_id == team_id)
    our_side = home if is_home else away
    opp_side = away if is_home else home

    opp_id = opp_side.get("team", {}).get("id")
    opp_abbr = _ID_TO_ABBR.get(opp_id, str(opp_id))

    our_prob_raw = our_side.get("probablePitcher", {})
    opp_prob_raw = opp_side.get("probablePitcher", {})

    our_prob = {
        "id": our_prob_raw.get("id"),
        "name": our_prob_raw.get("fullName", "TBD"),
        "hand": our_prob_raw.get("pitchHand", {}).get("code", "R") if isinstance(our_prob_raw.get("pitchHand"), dict) else "R",
    }

    opp_prob = {
        "id": opp_prob_raw.get("id"),
        "name": opp_prob_raw.get("fullName", "TBD"),
        "hand": opp_prob_raw.get("pitchHand", {}).get("code", "R") if isinstance(opp_prob_raw.get("pitchHand"), dict) else "R",
    }

    status = raw_game.get("status", {}) or {}

    return {
        "game_pk": raw_game.get("gamePk"),
        "game_date": raw_game.get("officialDate", date_str),
        # UTC instant of first pitch. The MLB schedule flags a genuinely
        # undecided start with startTimeTBD, which is not the same as a missing
        # field — carry it so the page can say "TBD" honestly.
        "game_time_utc": raw_game.get("gameDate"),
        "start_time_tbd": bool(status.get("startTimeTBD", False)),
        "game_number": game_n,
        "venue": raw_game.get("venue", {}).get("name", "TBD"),
        "status": raw_game.get("status", {}).get("detailedState", "Scheduled"),
        "is_home": is_home,
        "team_id": team_id,
        "opponent_id": opp_id,
        "opponent_abbr": opp_abbr,
        "our_probable": our_prob,
        "opp_probable": opp_prob,
    }


def format_first_pitch(preview: dict[str, Any]) -> str:
    """
    First pitch as "4:10 PM ET (20:10 UTC)", for a preview from
    _parse_single_preview().

    Returns "TBD" when the schedule says the start time is undecided or the
    field is missing or unparseable — an honest TBD beats a guessed time, and a
    reader planning around this needs to know which one they are looking at.

    UTC is shown alongside because the betting page timestamps its odds in UTC,
    and comparing "lines as of" to first pitch is the whole point of having both.
    """
    if preview.get("start_time_tbd"):
        return "TBD"

    raw = preview.get("game_time_utc")
    if not raw:
        return "TBD"
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return "TBD"

    local = stamp.astimezone(TEAM_TZ)
    # %-I is a GNU extension; it drops the leading zero on the hour.
    return f"{local.strftime('%-I:%M %p')} ET ({stamp.strftime('%H:%M')} UTC)"


def fetch_doubleheader_previews(
    client: MLBClient,
    team_id: int = TEAM_ID,
    date_str: str = "2026-07-22",
) -> list[dict[str, Any]]:
    """Fetch all game previews for a given date (handles split doubleheaders)."""
    raw_games = client.get_game_previews(team_id, date_str)
    return [_parse_single_preview(g, team_id, date_str, i + 1) for i, g in enumerate(raw_games)]


def fetch_game_preview(
    client: MLBClient,
    team_id: int = TEAM_ID,
    date_str: str = "2026-07-22",
) -> dict[str, Any]:
    """Fetch preview details for the first/primary game on a specified date."""
    previews = fetch_doubleheader_previews(client, team_id, date_str)
    return previews[0] if previews else {}


# ---------------------------------------------------------------------------
# Probable Starter Stats Summary
# ---------------------------------------------------------------------------

def starter_season_summary(
    client: MLBClient,
    pitcher_id: int | None,
    season: int = 2026,
) -> dict[str, Any]:
    """Fetch starter season stats (ERA, WHIP, K/9, BB/9, IP, W-L)."""
    if not pitcher_id:
        return {"name": "TBD", "era": "-", "whip": "-", "k9": "-", "bb9": "-", "ip": 0, "w": 0, "l": 0}

    info = client.get_player_info(pitcher_id)
    name = info.get("fullName", f"Pitcher {pitcher_id}")
    hand = info.get("pitchHand", {}).get("code", "R")

    stat = client.get_player_season_stats(pitcher_id, season, group="pitching")
    if not stat:
        return {"name": name, "hand": hand, "era": "-", "whip": "-", "k9": "-", "bb9": "-", "ip": 0, "w": 0, "l": 0}

    ip = float(stat.get("inningsPitched", 0) or 0)
    so = int(stat.get("strikeOuts", 0) or 0)
    bb = int(stat.get("baseOnBalls", 0) or 0)

    era = str(stat.get("era", "-"))
    whip = str(stat.get("whip", "-"))
    k9 = round((so * 9.0 / ip), 2) if ip > 0 else 0.0
    bb9 = round((bb * 9.0 / ip), 2) if ip > 0 else 0.0

    return {
        "name": name,
        "hand": hand,
        "w": int(stat.get("wins", 0) or 0),
        "l": int(stat.get("losses", 0) or 0),
        "era": era,
        "whip": whip,
        "k9": f"{k9:.2f}" if ip > 0 else "-",
        "bb9": f"{bb9:.2f}" if ip > 0 else "-",
        "ip": ip,
    }


# ---------------------------------------------------------------------------
# Platoon Lineup Matchup
# ---------------------------------------------------------------------------

def platoon_recommendations(
    batting: pd.DataFrame,
    opp_hand: str = "R",
    season: int = 2026,
) -> pd.DataFrame:
    """
    Returns Red Sox hitters ranked by performance against opposing starter's hand.
    opp_hand: 'L' or 'R'
    """
    plat = platoon_table(batting, season)
    if plat.empty:
        return pd.DataFrame()

    piv = pivoted_platoon_summary(plat)
    if piv.empty:
        return pd.DataFrame()

    side_prefix = "l_" if opp_hand.upper() == "L" else "r_"
    ops_col = f"{side_prefix}ops"
    ab_col = f"{side_prefix}ab"
    avg_col = f"{side_prefix}avg"
    obp_col = f"{side_prefix}obp"
    slg_col = f"{side_prefix}slg"
    hr_col = f"{side_prefix}hr"

    df = piv.sort_values(ops_col, ascending=False).reset_index(drop=True)
    df["opp_hand"] = f"vs {opp_hand.upper()}HP"

    res = df[["player_name", "opp_hand", ab_col, avg_col, obp_col, slg_col, ops_col, hr_col, "ops_delta"]].copy()
    res.columns = ["player_name", "split", "ab", "avg", "obp", "slg", "ops", "hr", "ops_delta"]
    return res


# ---------------------------------------------------------------------------
# Bullpen Availability Matrix
# ---------------------------------------------------------------------------

def bullpen_availability(
    pitching: pd.DataFrame,
    ref_date_str: str = "2026-07-21",
    days: int = 3,
) -> pd.DataFrame:
    """
    Calculates pitch count history over the last `days` prior to ref_date_str.
    Categorizes availability: FRESH, MODERATE, HEAVY.
    """
    relievers = pitching[pitching["is_starter"] == False].copy()
    if relievers.empty:
        return pd.DataFrame()

    relievers["game_date"] = pd.to_datetime(relievers["game_date"])
    ref_dt = pd.to_datetime(ref_date_str)

    d1 = ref_dt - pd.Timedelta(days=1)
    d2 = ref_dt - pd.Timedelta(days=2)
    d3 = ref_dt - pd.Timedelta(days=3)

    p_d1 = relievers[relievers["game_date"] == d1].groupby("player_name")["pitches"].sum().to_dict()
    p_d2 = relievers[relievers["game_date"] == d2].groupby("player_name")["pitches"].sum().to_dict()
    p_d3 = relievers[relievers["game_date"] == d3].groupby("player_name")["pitches"].sum().to_dict()

    all_relievers = sorted(relievers["player_name"].dropna().unique())
    rows = []
    for name in all_relievers:
        p1 = int(p_d1.get(name, 0))
        p2 = int(p_d2.get(name, 0))
        p3 = int(p_d3.get(name, 0))
        tot_3d = p1 + p2 + p3

        if p1 >= 25 or (p1 > 0 and p2 > 0 and p3 > 0):
            status = "🔴 HEAVY"
        elif p1 > 0 or p2 >= 20:
            status = "🟡 MODERATE"
        else:
            status = "🟢 FRESH"

        rows.append({
            "player_name": name,
            "d1_pitches": p1,
            "d2_pitches": p2,
            "d3_pitches": p3,
            "tot_3d": tot_3d,
            "status": status,
        })

    return pd.DataFrame(rows).sort_values(["tot_3d", "player_name"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Head-to-Head Season Series Summary
# ---------------------------------------------------------------------------

def head_to_head_summary(
    games: pd.DataFrame,
    opponent_id: int,
) -> dict[str, Any]:
    """Returns 2026 season series record and run differential vs opponent_id."""
    opp_games = games[(games["opponent_id"] == opponent_id) & (games["status"] == "Final")].sort_values("game_date")
    if opp_games.empty:
        return {"games_played": 0, "wins": 0, "losses": 0, "win_pct": 0.0, "rs": 0, "ra": 0, "diff": 0}

    wins = int((opp_games["result"] == "W").sum())
    losses = int((opp_games["result"] == "L").sum())
    rs = int(opp_games["runs_scored"].sum())
    ra = int(opp_games["runs_allowed"].sum())
    gp = wins + losses

    return {
        "games_played": gp,
        "wins": wins,
        "losses": losses,
        "win_pct": round(wins / gp, 3) if gp > 0 else 0.0,
        "rs": rs,
        "ra": ra,
        "diff": rs - ra,
        "last_game": opp_games.iloc[-1]["game_date"] if not opp_games.empty else "-",
    }
