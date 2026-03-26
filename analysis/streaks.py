"""
Streak, slump, and pattern detection — fully implemented in Day 3.

Covers:
  - Team win/loss streak (current + season longest)
  - Streak timeline for charting
  - Series results (sweep / split / series loss)
  - Player hitting streaks + hitless streaks
  - Walk-off win detection
  - Monthly record splits
  - Back-to-back game performance
"""

from __future__ import annotations

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box

from config import TEAMS

_ID_TO_ABBR: dict[int, str] = {v["id"]: k for k, v in TEAMS.items()}


# ---------------------------------------------------------------------------
# Team win/loss streaks
# ---------------------------------------------------------------------------

def current_streak(games: pd.DataFrame) -> tuple[str, int]:
    """
    Return (type, length) for the current streak.
    type = 'W' or 'L', length = consecutive games.
    Returns ('', 0) if no games played.
    """
    finished = games[games["status"] == "Final"].sort_values("game_date")
    if finished.empty:
        return ("", 0)
    results = finished["result"].tolist()
    last    = results[-1]
    count   = sum(1 for _ in iter(lambda r=iter(reversed(results)): next(r), None)
                  if _ == last)
    # simpler loop:
    count = 0
    for r in reversed(results):
        if r == last:
            count += 1
        else:
            break
    return (last, count)


def longest_streak(games: pd.DataFrame, streak_type: str = "W") -> int:
    """Longest win or loss streak in the season."""
    finished = games[games["status"] == "Final"].sort_values("game_date")
    best = current = 0
    for result in finished["result"]:
        current = (current + 1) if result == streak_type else 0
        best = max(best, current)
    return best


def streak_timeline(games: pd.DataFrame) -> pd.DataFrame:
    """
    Per-game streak value: positive = win streak length, negative = loss streak.
    Useful for charting momentum over the season.
    """
    finished = games[games["status"] == "Final"].sort_values("game_date").copy()
    values = []
    current = 0
    for result in finished["result"]:
        if result == "W":
            current = max(current + 1, 1)
        else:
            current = min(current - 1, -1)
        values.append(current)
    finished = finished.reset_index(drop=True)
    finished["streak_value"] = values
    return finished[["game_date", "game_num", "result", "runs_scored", "runs_allowed", "streak_value"]]


# ---------------------------------------------------------------------------
# Series results
# ---------------------------------------------------------------------------

def series_results(games: pd.DataFrame) -> pd.DataFrame:
    """
    Group consecutive games against the same opponent into series.

    Returns a DataFrame with one row per series:
        opponent_id, opponent_abbr, series_start, series_end,
        games, wins, losses, outcome
    outcome: 'Sweep' | 'Split' | 'Series Loss'
    """
    finished = games[games["status"] == "Final"].sort_values("game_date").reset_index(drop=True)
    if finished.empty:
        return pd.DataFrame()

    # Assign a series_id that increments when the opponent changes
    finished["series_id"] = (
        finished["opponent_id"] != finished["opponent_id"].shift()
    ).cumsum()

    rows = []
    for sid, grp in finished.groupby("series_id"):
        opp_id = int(grp["opponent_id"].iloc[0])
        w      = int((grp["result"] == "W").sum())
        l      = int((grp["result"] == "L").sum())
        g      = w + l

        if w == g:
            outcome = "Sweep"
        elif l == g:
            outcome = "Series Loss"
        else:
            outcome = "Split"

        rows.append({
            "opponent_id":   opp_id,
            "opponent_abbr": _ID_TO_ABBR.get(opp_id, str(opp_id)),
            "series_start":  grp["game_date"].min(),
            "series_end":    grp["game_date"].max(),
            "games":         g,
            "wins":          w,
            "losses":        l,
            "outcome":       outcome,
        })

    return pd.DataFrame(rows)


def series_summary(games: pd.DataFrame) -> dict:
    """
    Aggregate series outcomes for the season:
        total_series, sweeps, splits, series_losses,
        sweep_pct, series_win_pct
    """
    df = series_results(games)
    if df.empty:
        return {}

    total    = len(df)
    sweeps   = int((df["outcome"] == "Sweep").sum())
    splits   = int((df["outcome"] == "Split").sum())
    losses   = int((df["outcome"] == "Series Loss").sum())
    # A series win = won more games than lost in the series
    series_w = int((df["wins"] > df["losses"]).sum())

    return dict(
        total_series=total,
        sweeps=sweeps, splits=splits, series_losses=losses,
        sweep_pct=round(sweeps / total * 100, 1) if total > 0 else 0.0,
        series_win_pct=round(series_w / total * 100, 1) if total > 0 else 0.0,
    )


# ---------------------------------------------------------------------------
# Player hitting streaks
# ---------------------------------------------------------------------------

def player_hitting_streak(batting: pd.DataFrame, player_id: int) -> int:
    """Current consecutive-games-with-a-hit streak."""
    player = batting[batting["player_id"] == player_id].sort_values("game_date")
    streak = 0
    for h in reversed(player["h"].tolist()):
        if h > 0:
            streak += 1
        else:
            break
    return streak


def all_hitting_streaks(batting: pd.DataFrame, min_pa: int = 1) -> pd.DataFrame:
    """
    For every player: current hitting streak, current hitless streak,
    and longest hitting streak of the season.

    min_pa: minimum PA in a game to count as a "game played" for streak purposes.
    """
    rows = []
    for pid, grp in batting.groupby("player_id"):
        # Only count games where player actually batted
        played = grp[grp["pa"] >= min_pa].sort_values("game_date")
        if played.empty:
            continue

        h_list = played["h"].tolist()
        name   = played["player_name"].iloc[0]

        # Current hitting streak (from end)
        hit_streak = 0
        for h in reversed(h_list):
            if h > 0:
                hit_streak += 1
            else:
                break

        # Current hitless streak (from end, only if not currently on a hit streak)
        hitless_streak = 0
        if hit_streak == 0:
            for h in reversed(h_list):
                if h == 0:
                    hitless_streak += 1
                else:
                    break

        # Longest hitting streak this season
        longest = cur = 0
        for h in h_list:
            cur = (cur + 1) if h > 0 else 0
            longest = max(longest, cur)

        # Multi-HR games
        multi_hr = int((played["hr"] >= 2).sum())

        rows.append({
            "player_id":      int(pid),
            "player_name":    name,
            "g":              len(played),
            "hitting_streak": hit_streak,
            "hitless_streak": hitless_streak,
            "longest_streak": longest,
            "multi_hr_games": multi_hr,
        })

    return (
        pd.DataFrame(rows)
        .sort_values("hitting_streak", ascending=False)
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Walk-off detection
# ---------------------------------------------------------------------------

def walk_off_games(games: pd.DataFrame) -> pd.DataFrame:
    """
    Identify probable walk-off wins.

    Strategy:
      - Extra-inning home wins (innings > 9) = confirmed walk-off.
      - 9-inning home wins where runs_scored > runs_allowed = possible walk-off
        (we can't distinguish without inning-by-inning scoring, so we flag all
        home wins and note that extra-inning ones are confirmed).

    Returns subset of games with 'walk_off_type' column:
      'Confirmed' (extra innings) | 'Possible' (9 innings)
    """
    finished = games[games["status"] == "Final"].copy()
    home_wins = finished[(finished["is_home"] == True) & (finished["result"] == "W")]

    home_wins = home_wins.copy()
    home_wins["walk_off_type"] = home_wins["innings"].apply(
        lambda inn: "Confirmed" if inn > 9 else "Possible"
    )
    return home_wins[["game_date", "opponent_id", "runs_scored", "runs_allowed",
                       "innings", "walk_off_type"]].reset_index(drop=True)


def walk_off_losses(games: pd.DataFrame) -> pd.DataFrame:
    """Identify away losses in extra innings (confirmed walk-off losses)."""
    finished = games[games["status"] == "Final"].copy()
    return finished[
        (finished["is_home"] == False)
        & (finished["result"] == "L")
        & (finished["innings"] > 9)
    ][["game_date", "opponent_id", "runs_scored", "runs_allowed", "innings"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Monthly splits
# ---------------------------------------------------------------------------

def monthly_record(games: pd.DataFrame) -> pd.DataFrame:
    """W-L record and win% by calendar month."""
    finished = games[games["status"] == "Final"].copy()
    finished["month"] = pd.to_datetime(finished["game_date"]).dt.to_period("M")
    grouped = (
        finished.groupby("month")
        .apply(lambda df: pd.Series({
            "wins":   int((df["result"] == "W").sum()),
            "losses": int((df["result"] == "L").sum()),
            "rs":     int(df["runs_scored"].sum()),
            "ra":     int(df["runs_allowed"].sum()),
        }))
        .reset_index()
    )
    g = grouped["wins"] + grouped["losses"]
    grouped["win_pct"]  = (grouped["wins"] / g).where(g > 0, 0.0).round(3)
    grouped["run_diff"] = grouped["rs"] - grouped["ra"]
    return grouped


# ---------------------------------------------------------------------------
# Back-to-back performance
# ---------------------------------------------------------------------------

def back_to_back_record(games: pd.DataFrame) -> dict:
    """
    W-L record in the second game of back-to-back series
    (games played on consecutive calendar days).
    """
    finished = games[games["status"] == "Final"].sort_values("game_date").copy()
    finished["prev_date"] = pd.to_datetime(finished["game_date"]).shift(1)
    finished["curr_date"] = pd.to_datetime(finished["game_date"])
    finished["is_b2b"]    = (finished["curr_date"] - finished["prev_date"]).dt.days == 1

    b2b = finished[finished["is_b2b"]]
    if b2b.empty:
        return {"b2b_w": 0, "b2b_l": 0, "b2b_pct": 0.0}

    w = int((b2b["result"] == "W").sum())
    l = int((b2b["result"] == "L").sum())
    return {
        "b2b_w": w, "b2b_l": l,
        "b2b_pct": round(w / (w + l), 3) if (w + l) > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Rich terminal output
# ---------------------------------------------------------------------------

def print_streaks(
    console: Console,
    games: pd.DataFrame,
    batting: pd.DataFrame,
    pitching: pd.DataFrame,
) -> None:
    """Print streak / pattern dashboard."""

    # --- Current streak + season bests ---
    streak_type, streak_len = current_streak(games)
    longest_w = longest_streak(games, "W")
    longest_l = longest_streak(games, "L")
    b2b       = back_to_back_record(games)

    streak_color = "green" if streak_type == "W" else ("red" if streak_type == "L" else "white")
    streak_label = f"[bold {streak_color}]{streak_type}{streak_len}[/bold {streak_color}]" if streak_type else "—"

    info_t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    info_t.add_column("Metric", style="cyan",  min_width=22)
    info_t.add_column("Value",  style="white", justify="right")
    info_t.add_row("Current Streak",     streak_label)
    info_t.add_row("Longest Win Streak", f"[green]{longest_w}[/green]")
    info_t.add_row("Longest Loss Streak",f"[red]{longest_l}[/red]")
    info_t.add_row("Back-to-Back",       f"{b2b['b2b_w']}-{b2b['b2b_l']} ({b2b['b2b_pct']:.3f})")
    console.print(info_t)

    # --- Monthly record ---
    monthly = monthly_record(games)
    if not monthly.empty:
        m_t = Table(title="Monthly Record", box=box.SIMPLE, show_lines=False)
        m_t.add_column("Month",    style="cyan")
        m_t.add_column("W",        style="green",  justify="right")
        m_t.add_column("L",        style="red",    justify="right")
        m_t.add_column("Win%",     style="white",  justify="right")
        m_t.add_column("RS",       style="yellow", justify="right")
        m_t.add_column("RA",       style="yellow", justify="right")
        m_t.add_column("Diff",     style="cyan",   justify="right")
        for _, row in monthly.iterrows():
            rd    = int(row["run_diff"])
            rd_s  = f"+{rd}" if rd > 0 else str(rd)
            rd_col= "green" if rd > 0 else ("red" if rd < 0 else "white")
            m_t.add_row(
                str(row["month"]),
                str(row["wins"]), str(row["losses"]),
                f"{row['win_pct']:.3f}",
                str(int(row["rs"])), str(int(row["ra"])),
                f"[{rd_col}]{rd_s}[/{rd_col}]",
            )
        console.print(m_t)

    # --- Series results ---
    series = series_results(games)
    if not series.empty:
        ss = series_summary(games)
        console.print(
            f"Series record: [green]{ss['sweeps']}[/green] sweeps  "
            f"[dim]{ss['splits']}[/dim] splits  "
            f"[red]{ss['series_losses']}[/red] series losses  "
            f"([bold]{ss['series_win_pct']:.0f}%[/bold] series win rate)"
        )

        sr_t = Table(title="Series Results", box=box.SIMPLE, show_lines=False)
        sr_t.add_column("Opponent", style="cyan",  min_width=6)
        sr_t.add_column("Dates",    style="dim",   min_width=22)
        sr_t.add_column("W",        style="green", justify="right")
        sr_t.add_column("L",        style="red",   justify="right")
        sr_t.add_column("Result",   style="bold",  justify="left")

        outcome_style = {"Sweep": "bold green", "Split": "white", "Series Loss": "bold red"}
        for _, row in series.iterrows():
            date_range = (
                row["series_start"] if row["series_start"] == row["series_end"]
                else f"{row['series_start']} – {row['series_end']}"
            )
            style  = outcome_style.get(row["outcome"], "white")
            sr_t.add_row(
                row["opponent_abbr"], date_range,
                str(row["wins"]), str(row["losses"]),
                f"[{style}]{row['outcome']}[/{style}]",
            )
        console.print(sr_t)

    # --- Player hitting streaks ---
    if not batting.empty:
        streaks_df = all_hitting_streaks(batting)
        active     = streaks_df[streaks_df["hitting_streak"] > 0]
        slumping   = streaks_df[streaks_df["hitless_streak"] >= 5].sort_values(
            "hitless_streak", ascending=False
        )

        if not active.empty:
            hs_t = Table(title="Active Hitting Streaks", box=box.SIMPLE, show_lines=False)
            hs_t.add_column("Player",       style="cyan",  min_width=20)
            hs_t.add_column("Streak",       style="bold green", justify="right")
            hs_t.add_column("Season Best",  style="dim",   justify="right")
            hs_t.add_column("Multi-HR Gms", style="yellow",justify="right")
            for _, row in active.iterrows():
                hs_t.add_row(
                    row["player_name"],
                    str(row["hitting_streak"]),
                    str(row["longest_streak"]),
                    str(row["multi_hr_games"]),
                )
            console.print(hs_t)

        if not slumping.empty:
            sl_t = Table(title="Current Slumps (≥5 hitless games)", box=box.SIMPLE, show_lines=False)
            sl_t.add_column("Player",       style="cyan",  min_width=20)
            sl_t.add_column("Hitless",      style="bold red", justify="right")
            sl_t.add_column("Season Best",  style="dim",   justify="right")
            for _, row in slumping.iterrows():
                sl_t.add_row(
                    row["player_name"],
                    str(row["hitless_streak"]),
                    str(row["longest_streak"]),
                )
            console.print(sl_t)

    # --- Walk-off wins ---
    wos = walk_off_games(games)
    if not wos.empty:
        confirmed_wos = wos[wos["walk_off_type"] == "Confirmed"]
        wo_t = Table(
            title=f"Walk-off Wins ({len(wos)} total · {len(confirmed_wos)} confirmed extra-inning)",
            box=box.SIMPLE, show_lines=False,
        )
        wo_t.add_column("Date",         style="dim",    min_width=11)
        wo_t.add_column("Opponent",     style="cyan",   min_width=6)
        wo_t.add_column("Score",        style="white",  justify="right")
        wo_t.add_column("Inn",          style="dim",    justify="right")
        wo_t.add_column("Type",         style="bold",   justify="left")
        for _, row in wos.sort_values("game_date").iterrows():
            opp   = _ID_TO_ABBR.get(int(row["opponent_id"]), str(int(row["opponent_id"])))
            score = f"{int(row['runs_scored'])}-{int(row['runs_allowed'])}"
            wtype = ("[green]Confirmed[/green]" if row["walk_off_type"] == "Confirmed"
                     else "[dim]Possible[/dim]")
            wo_t.add_row(row["game_date"], opp, score, str(int(row["innings"])), wtype)
        console.print(wo_t)
