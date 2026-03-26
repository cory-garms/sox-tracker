"""
Standings & season overview analysis — Day 2.

Covers:
  - Current W-L, win%, run differential, Pythagorean record
  - Games back, division rank
  - Home/away, day/night, vs-division, vs-league splits
  - Rolling 7/15-game win% trend
  - Live division standings with pace projections
"""

from __future__ import annotations

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich import box

from client.mlb_client import MLBClient
from config import TEAMS


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

# Build {team_id: team_info} from config for fast lookups
_ID_TO_TEAM: dict[int, dict] = {v["id"]: {**v, "abbr": k} for k, v in TEAMS.items()}


def _division_peer_ids(team_id: int) -> set[int]:
    """Return IDs of all other teams in the same division as team_id."""
    me = _ID_TO_TEAM.get(team_id, {})
    my_league   = me.get("league")
    my_division = me.get("division")
    return {
        info["id"]
        for info in _ID_TO_TEAM.values()
        if info["id"] != team_id
        and info["league"]   == my_league
        and info["division"] == my_division
    }


def _league_peer_ids(team_id: int) -> set[int]:
    """Return IDs of all teams in the same league (excluding self)."""
    me = _ID_TO_TEAM.get(team_id, {})
    my_league = me.get("league")
    return {
        info["id"]
        for info in _ID_TO_TEAM.values()
        if info["id"] != team_id and info["league"] == my_league
    }


# ---------------------------------------------------------------------------
# Pythagorean win expectation
# ---------------------------------------------------------------------------

def pythagorean_record(
    runs_scored: int, runs_allowed: int, games: int, exp: float = 1.83
) -> tuple[int, int]:
    """Return (expected_wins, expected_losses) via Pythagorean expectation."""
    if runs_scored + runs_allowed == 0:
        return 0, 0
    pct = runs_scored ** exp / (runs_scored ** exp + runs_allowed ** exp)
    w = round(pct * games)
    return w, games - w


def pace_projection(wins: int, losses: int, total_games: int = 162) -> tuple[int, int]:
    """Project final W-L based on current win rate."""
    played = wins + losses
    if played == 0:
        return 0, 0
    w = round((wins / played) * total_games)
    return w, total_games - w


# ---------------------------------------------------------------------------
# Season record (from games cache)
# ---------------------------------------------------------------------------

def season_record(games: pd.DataFrame) -> dict:
    """
    Full season record dict from the cached games table.

    Keys: wins, losses, win_pct, games_played,
          run_diff, runs_scored, runs_allowed,
          pyth_wins, pyth_losses,
          home_w, home_l, away_w, away_l,
          day_w, day_l, night_w, night_l,
          last_7_w, last_7_l, last_15_w, last_15_l
    """
    f = games[games["status"] == "Final"].copy()
    if f.empty:
        return {}

    def wl(df: pd.DataFrame) -> tuple[int, int]:
        return int((df["result"] == "W").sum()), int((df["result"] == "L").sum())

    w, l   = wl(f)
    g      = w + l
    rs     = int(f["runs_scored"].sum())
    ra     = int(f["runs_allowed"].sum())
    pyth_w, pyth_l = pythagorean_record(rs, ra, g)
    hw, hl = wl(f[f["is_home"] == True])
    aw, al = wl(f[f["is_home"] == False])
    dw, dl = wl(f[f["day_night"] == "D"])
    nw, nl = wl(f[f["day_night"] == "N"])
    l7w, l7l   = wl(f.tail(7))
    l15w, l15l = wl(f.tail(15))

    return dict(
        wins=w, losses=l, games_played=g,
        win_pct=w / g if g > 0 else 0.0,
        run_diff=rs - ra, runs_scored=rs, runs_allowed=ra,
        r_per_g=round(rs / g, 2) if g > 0 else 0.0,
        ra_per_g=round(ra / g, 2) if g > 0 else 0.0,
        pyth_wins=pyth_w, pyth_losses=pyth_l,
        home_w=hw, home_l=hl,
        away_w=aw, away_l=al,
        day_w=dw, day_l=dl,
        night_w=nw, night_l=nl,
        last_7_w=l7w, last_7_l=l7l,
        last_15_w=l15w, last_15_l=l15l,
    )


def opponent_splits(games: pd.DataFrame, team_id: int) -> dict:
    """
    Win-loss records split by opponent category:
      vs_div  — same division
      vs_lg   — same league, different division
      vs_inter — interleague
    """
    f       = games[games["status"] == "Final"].copy()
    div_ids = _division_peer_ids(team_id)
    lg_ids  = _league_peer_ids(team_id) - div_ids

    def wl(df):
        return int((df["result"] == "W").sum()), int((df["result"] == "L").sum())

    div_w, div_l   = wl(f[f["opponent_id"].isin(div_ids)])
    lg_w, lg_l     = wl(f[f["opponent_id"].isin(lg_ids)])
    inter_w, inter_l = wl(f[~f["opponent_id"].isin(div_ids | lg_ids)])

    return dict(
        div_w=div_w, div_l=div_l,
        lg_w=lg_w, lg_l=lg_l,
        inter_w=inter_w, inter_l=inter_l,
    )


def rolling_win_pct(games: pd.DataFrame, window: int = 10) -> pd.Series:
    """Rolling win% over a sliding window, indexed by game_date."""
    f = games[games["status"] == "Final"].copy()
    f["win_flag"] = (f["result"] == "W").astype(int)
    return f.set_index("game_date")["win_flag"].rolling(window).mean()


# ---------------------------------------------------------------------------
# Live standings from the API
# ---------------------------------------------------------------------------

def fetch_division_standings(team_id: int, season: int) -> list[dict]:
    """
    Pull live standings for the division containing team_id.

    Returns list of dicts (one per team), sorted by division rank:
        team_id, team_name, wins, losses, win_pct, gb,
        run_diff, streak, last_10, div_rank, pace_w, pace_l
    """
    client = MLBClient()
    all_records = client.get_standings(season)
    rows: list[dict] = []

    for division_block in all_records:
        team_records = division_block.get("teamRecords", [])
        # Check if our team is in this division block
        ids_in_block = {tr.get("team", {}).get("id") for tr in team_records}
        if team_id not in ids_in_block:
            continue

        for tr in team_records:
            lr     = tr.get("leagueRecord", {})
            tid    = tr.get("team", {}).get("id")
            w      = lr.get("wins", 0)
            l      = lr.get("losses", 0)
            played = w + l
            pw, pl = pace_projection(w, l)

            streak_info = tr.get("streak", {})
            streak_str  = streak_info.get("streakCode", "-")   # e.g. "W3" or "L1"

            last10 = tr.get("records", {}).get("splitRecords", [])
            l10_str = "-"
            for sr in last10:
                if sr.get("type") == "lastTen":
                    l10_str = f"{sr['wins']}-{sr['losses']}"
                    break

            rows.append(dict(
                team_id   = tid,
                team_name = tr.get("team", {}).get("name", ""),
                wins      = w,
                losses    = l,
                win_pct   = float(lr.get("pct", 0)),
                gb        = tr.get("gamesBack", "-"),
                run_diff  = tr.get("runDifferential", 0),
                streak    = streak_str,
                last_10   = l10_str,
                div_rank  = int(tr.get("divisionRank", 0)),
                pace_w    = pw,
                pace_l    = pl,
            ))
        break  # found our division, no need to continue

    return sorted(rows, key=lambda r: r["div_rank"])


# ---------------------------------------------------------------------------
# Rich terminal output
# ---------------------------------------------------------------------------

def print_overview(
    console: Console,
    games: pd.DataFrame,
    team_info: dict,
    batting: pd.DataFrame | None = None,
    pitching: pd.DataFrame | None = None,
    fielding: pd.DataFrame | None = None,
) -> None:
    """Print the full season overview panel."""
    from analysis.streaks import current_streak

    rec = season_record(games)
    if not rec:
        console.print("[yellow]No completed games found in cache.[/yellow]")
        return

    team_id = team_info["id"]
    w, l    = rec["wins"], rec["losses"]
    rd      = rec["run_diff"]
    rd_str  = f"[green]+{rd}[/green]" if rd >= 0 else f"[red]{rd}[/red]"
    proj_w, proj_l = pace_projection(w, l)
    streak_type, streak_len = current_streak(games)

    streak_color = "green" if streak_type == "W" else "red"
    streak_label = f"[{streak_color}]{streak_type}{streak_len}[/{streak_color}]"

    # --- Record table ---
    rec_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    rec_table.add_column("Metric", style="cyan",  min_width=18)
    rec_table.add_column("Value",  style="white", justify="right")

    rec_table.add_row("Record",          f"[bold]{w}-{l}[/bold]  ({rec['win_pct']:.3f})")
    rec_table.add_row("Streak",          streak_label)
    rec_table.add_row("Run Diff",        rd_str)
    rec_table.add_row("R/G  |  RA/G",   f"{rec['r_per_g']}  |  {rec['ra_per_g']}")
    rec_table.add_row("Pythagorean",     f"{rec['pyth_wins']}-{rec['pyth_losses']}")
    rec_table.add_row("162-Game Pace",   f"[bold]{proj_w}-{proj_l}[/bold]")

    # --- Splits table ---
    splits = opponent_splits(games, team_id)
    split_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    split_table.add_column("Split",  style="cyan",  min_width=14)
    split_table.add_column("W-L",    style="white", justify="right")

    split_table.add_row("Home",      f"{rec['home_w']}-{rec['home_l']}")
    split_table.add_row("Away",      f"{rec['away_w']}-{rec['away_l']}")
    split_table.add_row("Day",       f"{rec['day_w']}-{rec['day_l']}")
    split_table.add_row("Night",     f"{rec['night_w']}-{rec['night_l']}")
    split_table.add_row("vs Div",    f"{splits['div_w']}-{splits['div_l']}")
    split_table.add_row("vs League", f"{splits['lg_w']}-{splits['lg_l']}")
    split_table.add_row("Interleague",f"{splits['inter_w']}-{splits['inter_l']}")
    split_table.add_row("Last 7",    f"{rec['last_7_w']}-{rec['last_7_l']}")
    split_table.add_row("Last 15",   f"{rec['last_15_w']}-{rec['last_15_l']}")

    console.print(Panel(
        Columns([rec_table, split_table], equal=False, expand=False),
        title=f"[bold cyan]{team_info['name']} — Season Overview[/bold cyan]",
        border_style="cyan",
    ))

    # --- Inline team offense/pitching/defense summaries ---
    if batting is not None and not batting.empty:
        from analysis.offense import team_offense_summary
        off = team_offense_summary(batting, games)
        if off:
            _print_team_offense_row(console, off)

    if pitching is not None and not pitching.empty:
        from analysis.pitching import team_pitching_split
        pit = team_pitching_split(pitching)
        if pit:
            _print_team_pitching_row(console, pit)

    if fielding is not None and not fielding.empty:
        from analysis.defense import team_fielding_summary
        dfs = team_fielding_summary(fielding, games)
        if dfs:
            _print_team_defense_row(console, dfs)


def _print_team_offense_row(console: Console, off: dict) -> None:
    t = Table(title="Team Offense", box=box.SIMPLE, show_header=True, padding=(0, 1))
    for col in ("AVG", "OBP", "SLG", "OPS", "R/G", "HR", "SB", "BB%", "K%"):
        t.add_column(col, style="white", justify="right")
    t.add_row(
        f"{off.get('avg', 0):.3f}",
        f"{off.get('obp', 0):.3f}",
        f"{off.get('slg', 0):.3f}",
        f"{off.get('ops', 0):.3f}",
        f"{off.get('r_per_g', 0):.2f}",
        str(off.get("hr", 0)),
        str(off.get("sb", 0)),
        f"{off.get('bb_pct', 0):.1f}%",
        f"{off.get('k_pct', 0):.1f}%",
    )
    console.print(t)


def _print_team_pitching_row(console: Console, pit: dict) -> None:
    t = Table(title="Team Pitching", box=box.SIMPLE, show_header=True, padding=(0, 1))
    for col in ("ERA", "WHIP", "K/9", "BB/9", "SP ERA", "RP ERA", "QS%", "SV", "BS"):
        t.add_column(col, style="white", justify="right")
    t.add_row(
        f"{pit.get('era', 0):.2f}",
        f"{pit.get('whip', 0):.3f}",
        f"{pit.get('k_per_9', 0):.2f}",
        f"{pit.get('bb_per_9', 0):.2f}",
        f"{pit.get('starter_era', 0):.2f}",
        f"{pit.get('bullpen_era', 0):.2f}",
        f"{pit.get('quality_start_pct', 0):.1f}%",
        str(pit.get("saves", 0)),
        str(pit.get("blown_saves", 0)),
    )
    console.print(t)


def _print_team_defense_row(console: Console, dfs: dict) -> None:
    t = Table(title="Team Defense", box=box.SIMPLE, show_header=True, padding=(0, 1))
    for col in ("FLD%", "Errors", "E/G", "DP"):
        t.add_column(col, style="white", justify="right")
    t.add_row(
        f"{dfs.get('fielding_pct', 0):.4f}",
        str(dfs.get("errors", 0)),
        f"{dfs.get('errors_per_game', 0):.2f}",
        str(dfs.get("dp", 0)),
    )
    console.print(t)


def print_standings(console: Console, team_id: int, season: int) -> None:
    """Fetch live division standings and render as a rich table."""
    with console.status("[bold green]Fetching standings…[/bold green]"):
        rows = fetch_division_standings(team_id, season)

    if not rows:
        console.print("[yellow]Could not retrieve standings.[/yellow]")
        return

    t = Table(
        title=f"Division Standings — {season}",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
    )
    t.add_column("Team",     style="white",  min_width=22)
    t.add_column("W",        style="green",  justify="right")
    t.add_column("L",        style="red",    justify="right")
    t.add_column("PCT",      style="white",  justify="right")
    t.add_column("GB",       style="yellow", justify="right")
    t.add_column("Diff",     style="cyan",   justify="right")
    t.add_column("L10",      style="dim",    justify="right")
    t.add_column("Streak",   style="dim",    justify="right")
    t.add_column("Pace",     style="dim",    justify="right")

    for row in rows:
        is_us    = row["team_id"] == team_id
        rd       = row["run_diff"]
        rd_str   = f"+{rd}" if rd > 0 else str(rd)
        name_str = f"[bold cyan]{row['team_name']}[/bold cyan]" if is_us else row["team_name"]
        t.add_row(
            name_str,
            str(row["wins"]),
            str(row["losses"]),
            f"{row['win_pct']:.3f}",
            "-" if row["gb"] in ("-", "0.0", 0) else str(row["gb"]),
            rd_str,
            row["last_10"],
            row["streak"],
            f"{row['pace_w']}-{row['pace_l']}",
        )

    console.print(t)
