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

    # The posted batting order, hydrated by get_game_previews(). Carried through
    # so a prop can be checked against who is actually starting -- see
    # lineup_status(). MLB publishes these roughly 2-4 hours before first pitch,
    # so an empty list means "not announced yet" far more often than it means
    # "nobody is playing", and the two must not be conflated.
    lineups = raw_game.get("lineups", {}) or {}
    our_players = lineups.get("homePlayers" if is_home else "awayPlayers") or []
    opp_players = lineups.get("awayPlayers" if is_home else "homePlayers") or []

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
        # Empty set + posted False is "not announced"; posted True with a player
        # absent is "benched tonight". Only the second is worth flagging.
        "lineup_posted": bool(our_players),
        "our_lineup_ids": {p["id"] for p in our_players if p.get("id") is not None},
        "opp_lineup_ids": {p["id"] for p in opp_players if p.get("id") is not None},
        # The array *is* the batting order -- MLB returns it in slot sequence
        # and carries no explicit slot field. Position in the order is most of
        # what decides how many plate appearances a hitter gets, and a 1.5
        # total-bases line lives or dies on that: leadoff to ninth is roughly
        # half a PA, against a market where the whole edge is a few points.
        "our_lineup_order": {
            p["id"]: i for i, p in enumerate(our_players, start=1)
            if p.get("id") is not None
        },
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


# Three states, and the distinction is the whole point of this check.
LINEUP_IN = "in"              # lineup posted, player is starting
LINEUP_OUT = "out"            # lineup posted, player is not in it
LINEUP_UNPOSTED = "unposted"  # no lineup yet -- says nothing either way


def lineup_status(previews: list[dict[str, Any]], player_id: Any) -> str:
    """
    Is this player in tonight's posted batting order?

    A hitter carried a live +117 total-bases prop on 2026-07-27 while not in the
    posted lineup, and nothing on the page flagged it. A prop on someone who
    never bats is not a bad bet, it is a void one, and the page should say so.

    Returns LINEUP_UNPOSTED unless a lineup is actually published. Three of the
    four daily builds run before MLB posts one, so treating "no lineup yet" as
    "not starting" would flag the entire board every morning -- louder than the
    bug it is meant to catch, and it would train the reader to ignore the badge
    by the time it means something.

    A doubleheader is checked across both games: a player rested in game one and
    starting the nightcap is starting, and the prop does not say which game it
    is for.
    """
    if player_id is None or not previews:
        return LINEUP_UNPOSTED

    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return LINEUP_UNPOSTED

    posted = [p for p in previews if p and p.get("lineup_posted")]
    if not posted:
        return LINEUP_UNPOSTED

    for p in posted:
        if pid in (p.get("our_lineup_ids") or set()):
            return LINEUP_IN
    return LINEUP_OUT


def lineup_slot(previews: list[dict[str, Any]], player_id: Any) -> int | None:
    """
    Where in the batting order, or None if unknown.

    None covers both "no lineup posted yet" and "posted, and not in it" --
    neither is a slot. Callers wanting to tell those apart ask lineup_status().
    """
    if player_id is None or not previews:
        return None
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return None
    for p in previews:
        slot = ((p or {}).get("our_lineup_order") or {}).get(pid)
        if slot:
            return int(slot)
    return None


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

# Below this, a rate is a coincidence rather than a description. Two innings of
# shutout relief is an ERA of 0.00 and says nothing about the pitcher.
MIN_IP_FOR_RATES = 10.0


def innings_to_decimal(ip: float | str | None) -> float:
    """
    Convert MLB's innings notation to real innings.

    "80.2" means eighty and two *thirds*, not eighty point two. Treating it as a
    decimal understated Jake Bennett's K/9 as 6.85 on the matchup page while the
    strikeout model — which aggregates ip_outs — published 6.81 for the same
    pitcher on the models page.
    """
    if ip in (None, "", "-"):
        return 0.0
    try:
        value = float(ip)
    except (TypeError, ValueError):
        return 0.0
    whole = int(value)
    outs = round((value - whole) * 10)
    # Guard against a malformed ".4" or worse rather than inventing an inning.
    if outs not in (0, 1, 2):
        return float(value)
    return whole + outs / 3.0


def starter_season_summary(
    client: MLBClient,
    pitcher_id: int | None,
    season: int = 2026,
) -> dict[str, Any]:
    """
    Fetch starter season stats (ERA, WHIP, K/9, BB/9, IP, W-L).

    Rates are withheld below MIN_IP_FOR_RATES and the sample is reported
    instead: the page previously showed an opposing starter at "ERA 0.00,
    WHIP 0.50" off 2.0 innings, which reads as the best pitcher in baseball.
    """
    if not pitcher_id:
        return {"name": "TBD", "era": "-", "whip": "-", "k9": "-", "bb9": "-", "ip": 0, "w": 0, "l": 0}

    info = client.get_player_info(pitcher_id)
    name = info.get("fullName", f"Pitcher {pitcher_id}")
    hand = info.get("pitchHand", {}).get("code", "R")

    stat = client.get_player_season_stats(pitcher_id, season, group="pitching")
    if not stat:
        return {"name": name, "hand": hand, "era": "-", "whip": "-", "k9": "-", "bb9": "-", "ip": 0, "w": 0, "l": 0}

    raw_ip = stat.get("inningsPitched", 0) or 0
    ip = innings_to_decimal(raw_ip)
    so = int(stat.get("strikeOuts", 0) or 0)
    bb = int(stat.get("baseOnBalls", 0) or 0)

    thin = ip < MIN_IP_FOR_RATES
    k9 = round((so * 9.0 / ip), 2) if ip > 0 else 0.0
    bb9 = round((bb * 9.0 / ip), 2) if ip > 0 else 0.0

    return {
        "name": name,
        "hand": hand,
        "w": int(stat.get("wins", 0) or 0),
        "l": int(stat.get("losses", 0) or 0),
        # A rate off a handful of innings is noise wearing a decimal point.
        "era": "-" if thin else str(stat.get("era", "-")),
        "whip": "-" if thin else str(stat.get("whip", "-")),
        "k9": "-" if thin or ip <= 0 else f"{k9:.2f}",
        "bb9": "-" if thin or ip <= 0 else f"{bb9:.2f}",
        # Displayed as written by MLB (80.2 = 80 2/3), which is what a reader
        # expects to see; the decimal form is only for the arithmetic above.
        "ip": raw_ip,
        "ip_decimal": ip,
        "thin_sample": thin,
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
    active_pitcher_names: list[str] | set[str] | None = None,
    role_window_days: int = 30,
) -> pd.DataFrame:
    """
    Calculates pitch count history over the last `days` prior to ref_date_str.
    Categorizes availability: FRESH, MODERATE, HEAVY.

    Who counts as a bullpen arm is decided by *recent usage*, not by the roster
    and not by the season as a whole:

    - The roster cannot answer it. MLB tags every pitcher on the 26-man with
      position_group "SP", so it cannot tell a closer from a Sunday starter.
    - The full season cannot answer it either, because roles move in both
      directions. Brayan Bello opened 2026 in the rotation and has pitched
      only in relief since July; a season-long rule that asked "has he ever
      relieved?" would equally have kept a reliever who was *promoted* into
      the rotation in July.

    So role is read from a trailing `role_window_days` window: more relief
    appearances than starts in that window makes a bullpen arm. A pitcher who
    has not appeared at all in the window (injured, or simply rested) falls
    back to his season-long split rather than silently vanishing.

    Pitch counts include starts. A swingman who started two days ago spent that
    availability just as surely as if he had come out of the pen, and for a
    rotation arm a start is the single biggest thing making him unavailable
    tonight.

    `active_pitcher_names` narrows the result to the active roster; it never
    adds anyone whose usage does not make him a reliever.
    """
    if pitching.empty:
        return pd.DataFrame()

    work = pitching.copy()
    work["game_date"] = pd.to_datetime(work["game_date"])
    ref_dt = pd.to_datetime(ref_date_str)

    def _relief_majority(frame: pd.DataFrame) -> set[str]:
        if frame.empty:
            return set()
        by_role = frame.groupby("player_name")["is_starter"].agg(
            starts="sum", appearances="count",
        )
        return set(by_role.index[(by_role["appearances"] - by_role["starts"]) > by_role["starts"]])

    recent = work[work["game_date"] > ref_dt - pd.Timedelta(days=role_window_days)]
    bullpen_arms = _relief_majority(recent)

    # Anyone who has not pitched inside the window has no recent role to read.
    rested = set(work["player_name"].dropna().unique()) - set(recent["player_name"].dropna().unique())
    bullpen_arms |= _relief_majority(work[work["player_name"].isin(rested)])

    if active_pitcher_names is not None:
        bullpen_arms &= set(active_pitcher_names)

    if not bullpen_arms:
        return pd.DataFrame()

    def _pitches_on(offset: int) -> dict[str, int]:
        day = ref_dt - pd.Timedelta(days=offset)
        return work[work["game_date"] == day].groupby("player_name")["pitches"].sum().to_dict()

    p_d1, p_d2, p_d3 = _pitches_on(1), _pitches_on(2), _pitches_on(3)

    all_relievers = sorted(bullpen_arms)

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
