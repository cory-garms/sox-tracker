"""
Defensive analytics — team and player.

Day 2: team summary, per-player fielding totals, catcher basics.
Day 4: Statcast OAA, catcher framing, DP analysis, enhanced output.
"""

from __future__ import annotations

import logging

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Team fielding summary
# ---------------------------------------------------------------------------

def team_fielding_summary(fielding: pd.DataFrame, games: pd.DataFrame) -> dict:
    """
    Team-level: total errors, fielding%, DP turned, errors per game.
    """
    if fielding.empty:
        return {}

    total_po = int(fielding["putouts"].sum())
    total_a  = int(fielding["assists"].sum())
    total_e  = int(fielding["errors"].sum())
    total_dp = int(fielding["dp"].sum())
    total_ch = total_po + total_a + total_e
    fp       = (total_po + total_a) / total_ch if total_ch > 0 else 1.0

    g_played = len(games[games["status"] == "Final"])
    e_per_g  = round(total_e / g_played, 2) if g_played > 0 else 0.0

    return dict(
        fielding_pct=round(fp, 4),
        errors=total_e,
        errors_per_game=e_per_g,
        dp=total_dp,
        putouts=total_po,
        assists=total_a,
    )


def errors_by_position(fielding: pd.DataFrame) -> pd.Series:
    """Total errors per position, sorted descending."""
    if fielding.empty:
        return pd.Series(dtype=int)
    return fielding.groupby("position")["errors"].sum().sort_values(ascending=False)


# ---------------------------------------------------------------------------
# Player fielding totals
# ---------------------------------------------------------------------------

def player_fielding_totals(fielding: pd.DataFrame) -> pd.DataFrame:
    """
    Season fielding totals per player per position.
    Returns: player_id, player_name, position, g, po, a, e, ch, fielding_pct, dp
    """
    if fielding.empty:
        return pd.DataFrame()

    agg = fielding.groupby(["player_id", "position"]).agg(
        player_name=("player_name", "first"),
        g          =("game_pk",     "count"),
        po         =("putouts",     "sum"),
        a          =("assists",     "sum"),
        e          =("errors",      "sum"),
        dp         =("dp",          "sum"),
    ).reset_index()

    agg["ch"]           = agg["po"] + agg["a"] + agg["e"]
    agg["fielding_pct"] = (
        (agg["po"] + agg["a"]) / agg["ch"]
    ).where(agg["ch"] > 0, 1.0).round(4)

    return agg.sort_values(["position", "e"], ascending=[True, False]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Double play analysis  (Day 4)
# ---------------------------------------------------------------------------

def double_play_analysis(fielding: pd.DataFrame, games: pd.DataFrame) -> dict:
    """
    Team DP totals, DP per game, and per-position DP contributions.

    Returns: total_dp, dp_per_game, dp_by_position (Series)
    """
    if fielding.empty or games.empty:
        return {}

    g_played = len(games[games["status"] == "Final"])
    total_dp = int(fielding["dp"].sum())
    dp_by_pos = fielding.groupby("position")["dp"].sum().sort_values(ascending=False)

    return dict(
        total_dp=total_dp,
        dp_per_game=round(total_dp / g_played, 2) if g_played > 0 else 0.0,
        dp_by_position=dp_by_pos,
    )


# ---------------------------------------------------------------------------
# Catcher-specific stats
# ---------------------------------------------------------------------------

def catcher_stats(fielding: pd.DataFrame) -> pd.DataFrame:
    """
    For each catcher: games, SB-against, CS-against, caught-stealing%, passed balls.
    """
    if fielding.empty:
        return pd.DataFrame()

    catchers = fielding[fielding["position"] == "C"].copy()
    if catchers.empty:
        return pd.DataFrame()

    agg = catchers.groupby("player_id").agg(
        player_name  =("player_name",  "first"),
        g            =("game_pk",      "count"),
        sb_against   =("sb_against",   "sum"),
        cs_against   =("cs_against",   "sum"),
        passed_balls =("passed_balls", "sum"),
        po           =("putouts",      "sum"),
        e            =("errors",       "sum"),
    ).reset_index()

    attempts = agg["sb_against"] + agg["cs_against"]
    agg["cs_pct"] = (
        (agg["cs_against"] / attempts * 100)
        .where(attempts > 0, 0.0)
        .round(1)
    )

    return agg.sort_values("cs_pct", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Statcast OAA  (Day 4)
# ---------------------------------------------------------------------------

def fetch_oaa(team_abbr: str, season: int) -> pd.DataFrame:
    """
    Outs Above Average from Baseball Savant for all fielders on the team.

    Returns: player_id, player_name, position, oaa, inn, attempts, success_rate_above_avg
    Positive OAA = above average, negative = below.
    """
    from client.savant_client import SavantClient
    try:
        df = SavantClient().get_oaa(season, team_abbr=team_abbr)
        if df.empty:
            log.info("No OAA data returned for %s %d", team_abbr, season)
        return df
    except Exception as e:
        log.warning("OAA fetch failed: %s", e)
        return pd.DataFrame()


def team_oaa_summary(oaa_df: pd.DataFrame) -> dict:
    """
    Aggregate OAA for the full team.
    Returns: total_oaa, above_avg_fielders, below_avg_fielders
    """
    if oaa_df.empty or "outs_above_average" not in oaa_df.columns:
        return {}

    total = float(oaa_df["outs_above_average"].sum())
    above = int((oaa_df["outs_above_average"] > 0).sum())
    below = int((oaa_df["outs_above_average"] < 0).sum())
    return dict(total_oaa=round(total, 1), above_avg=above, below_avg=below)


# ---------------------------------------------------------------------------
# Catcher framing  (Day 4)
# ---------------------------------------------------------------------------

def fetch_catcher_framing(team_abbr: str, season: int) -> pd.DataFrame:
    """
    Catcher framing runs saved/lost from Baseball Savant.

    Returns: player_id, player_name, n_pitches, strike_rate, runs_extra_strikes
    Positive runs_extra_strikes = runs saved (good framing).
    """
    from client.savant_client import SavantClient
    try:
        df = SavantClient().get_catcher_framing(season, team_abbr=team_abbr)
        if df.empty:
            log.info("No framing data returned for %s %d", team_abbr, season)
        return df
    except Exception as e:
        log.warning("Catcher framing fetch failed: %s", e)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Statcast sprint speed  (Day 4)
# ---------------------------------------------------------------------------

def fetch_sprint_speed(team_abbr: str, season: int) -> pd.DataFrame:
    """
    Sprint speed (ft/sec) for all players on the team from Baseball Savant.
    Useful for understanding baserunning and outfield range context.
    """
    from client.savant_client import SavantClient
    try:
        return SavantClient().get_sprint_speed(season, team_abbr=team_abbr)
    except Exception as e:
        log.warning("Sprint speed fetch failed: %s", e)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Rich terminal output
# ---------------------------------------------------------------------------

def print_defense(
    console: Console,
    fielding: pd.DataFrame,
    roster: pd.DataFrame,
    games: pd.DataFrame | None = None,
    team_abbr: str | None = None,
    season: int | None = None,
) -> None:
    """
    Full defensive dashboard:
      1. Team fielding summary
      2. Double play analysis
      3. Errors by position
      4. Per-player fielding table
      5. Catcher breakdown (CS%, passed balls)
      6. Statcast OAA table (if team_abbr + season provided)
      7. Catcher framing table (if team_abbr + season provided)
      8. Sprint speed table (if team_abbr + season provided)
    """
    if fielding.empty:
        console.print("[yellow]No fielding data.[/yellow]")
        return

    # 1. Team summary
    if games is not None:
        summary = team_fielding_summary(fielding, games)
        if summary:
            t = Table(title="Team Defense — Season", box=box.SIMPLE_HEAVY, show_lines=False)
            for col in ("FLD%", "Errors", "E/G", "DP"):
                t.add_column(col, style="white", justify="right")
            t.add_row(
                f"{summary['fielding_pct']:.4f}",
                str(summary["errors"]),
                f"{summary['errors_per_game']:.2f}",
                str(summary["dp"]),
            )
            console.print(t)

    # 2. Double play analysis
    if games is not None:
        dp = double_play_analysis(fielding, games)
        if dp:
            console.print(
                f"Double plays: [bold]{dp['total_dp']}[/bold] total  "
                f"([cyan]{dp['dp_per_game']:.2f}/G[/cyan])"
            )

    # 3. Errors by position
    err_pos = errors_by_position(fielding)
    if not err_pos.empty and err_pos.sum() > 0:
        ep_t = Table(title="Errors by Position", box=box.SIMPLE, show_lines=False)
        ep_t.add_column("Pos",    style="cyan",  min_width=5)
        ep_t.add_column("Errors", style="red",   justify="right")
        for pos, errs in err_pos.items():
            if errs > 0:
                ep_t.add_row(str(pos), str(int(errs)))
        console.print(ep_t)

    # 4. Per-player fielding table
    player_totals = player_fielding_totals(fielding)
    if not player_totals.empty:
        pf_t = Table(title="Player Fielding", box=box.SIMPLE, show_lines=False)
        pf_t.add_column("Player",  style="cyan",  min_width=20)
        pf_t.add_column("Pos",     style="dim",   justify="left",  min_width=4)
        pf_t.add_column("G",       style="dim",   justify="right")
        pf_t.add_column("PO",      style="white", justify="right")
        pf_t.add_column("A",       style="white", justify="right")
        pf_t.add_column("E",       style="red",   justify="right")
        pf_t.add_column("FLD%",    style="white", justify="right")
        pf_t.add_column("DP",      style="yellow",justify="right")
        for _, row in player_totals.iterrows():
            e_val = int(row["e"])
            e_col = "red" if e_val > 3 else ("yellow" if e_val > 0 else "dim")
            pf_t.add_row(
                row["player_name"], str(row["position"]),
                str(int(row["g"])), str(int(row["po"])), str(int(row["a"])),
                f"[{e_col}]{e_val}[/{e_col}]",
                f"{row['fielding_pct']:.4f}", str(int(row["dp"])),
            )
        console.print(pf_t)

    # 5. Catcher breakdown
    catchers = catcher_stats(fielding)
    if not catchers.empty:
        c_t = Table(title="Catchers", box=box.SIMPLE, show_lines=False)
        c_t.add_column("Catcher",  style="cyan",       min_width=20)
        c_t.add_column("G",        style="dim",         justify="right")
        c_t.add_column("SB-Att",   style="white",       justify="right")
        c_t.add_column("CS",       style="green",       justify="right")
        c_t.add_column("CS%",      style="bold white",  justify="right")
        c_t.add_column("PB",       style="red",         justify="right")
        for _, row in catchers.iterrows():
            att = int(row["sb_against"]) + int(row["cs_against"])
            cs_c = "green" if row["cs_pct"] >= 30 else ("yellow" if row["cs_pct"] >= 20 else "red")
            c_t.add_row(
                row["player_name"], str(int(row["g"])),
                str(att), str(int(row["cs_against"])),
                f"[{cs_c}]{row['cs_pct']:.1f}%[/{cs_c}]",
                str(int(row["passed_balls"])),
            )
        console.print(c_t)

    # 6. Statcast OAA
    if team_abbr and season:
        oaa_df = fetch_oaa(team_abbr, season)
        if not oaa_df.empty and "outs_above_average" in oaa_df.columns:
            oaa_summary = team_oaa_summary(oaa_df)
            total_oaa   = oaa_summary.get("total_oaa", 0)
            oaa_col     = "green" if total_oaa > 0 else ("red" if total_oaa < 0 else "white")
            console.print(
                f"Team OAA: [{oaa_col}][bold]{total_oaa:+.1f}[/bold][/{oaa_col}]  "
                f"({oaa_summary.get('above_avg', 0)} above avg, "
                f"{oaa_summary.get('below_avg', 0)} below avg)"
            )

            oaa_t = Table(title="Statcast Outs Above Average (OAA)", box=box.SIMPLE, show_lines=False)
            oaa_t.add_column("Player",   style="cyan",  min_width=20)
            oaa_t.add_column("Pos",      style="dim",   min_width=4)
            oaa_t.add_column("Inn",      style="dim",   justify="right")
            oaa_t.add_column("OAA",      style="bold",  justify="right")
            oaa_t.add_column("Attempts", style="dim",   justify="right")

            name_col   = "player_name" if "player_name" in oaa_df.columns else None
            pos_col    = next((c for c in ("pos", "position", "primary_pos") if c in oaa_df.columns), None)
            inn_col    = next((c for c in ("inn", "innings", "outs_played") if c in oaa_df.columns), None)
            att_col    = next((c for c in ("attempts", "n_opportunities") if c in oaa_df.columns), None)

            for _, row in oaa_df.sort_values("outs_above_average", ascending=False).iterrows():
                oaa_val  = float(row["outs_above_average"])
                oaa_c    = "green" if oaa_val > 0 else ("red" if oaa_val < 0 else "white")
                oaa_t.add_row(
                    str(row[name_col]) if name_col else "-",
                    str(row[pos_col]) if pos_col else "-",
                    str(round(float(row[inn_col]), 1)) if inn_col else "-",
                    f"[{oaa_c}]{oaa_val:+.0f}[/{oaa_c}]",
                    str(int(row[att_col])) if att_col else "-",
                )
            console.print(oaa_t)
        else:
            console.print("[dim]OAA data unavailable (requires active season or Savant access).[/dim]")

    # 7. Catcher framing
    if team_abbr and season:
        framing_df = fetch_catcher_framing(team_abbr, season)
        if not framing_df.empty:
            runs_col = next(
                (c for c in ("runs_extra_strikes", "framing_runs", "strike_rate_added") if c in framing_df.columns),
                None,
            )
            fr_t = Table(title="Catcher Framing (Statcast)", box=box.SIMPLE, show_lines=False)
            fr_t.add_column("Catcher",       style="cyan",  min_width=20)
            fr_t.add_column("Pitches",        style="dim",   justify="right")
            fr_t.add_column("Strike Rate",    style="white", justify="right")
            if runs_col:
                fr_t.add_column("Framing Runs", style="bold", justify="right")

            n_col  = next((c for c in ("n", "pitches_called", "n_pitches") if c in framing_df.columns), None)
            sr_col = next((c for c in ("strike_rate", "called_strike_rate") if c in framing_df.columns), None)
            nm_col = "player_name" if "player_name" in framing_df.columns else None

            for _, row in framing_df.iterrows():
                run_val = float(row[runs_col]) if runs_col else None
                run_c   = "green" if (run_val or 0) > 0 else "red"
                cells   = [
                    str(row[nm_col]) if nm_col else "-",
                    str(int(row[n_col])) if n_col else "-",
                    f"{float(row[sr_col]):.3f}" if sr_col else "-",
                ]
                if runs_col:
                    cells.append(f"[{run_c}]{run_val:+.1f}[/{run_c}]")
                fr_t.add_row(*cells)
            console.print(fr_t)

    # 8. Sprint speed
    if team_abbr and season:
        speed_df = fetch_sprint_speed(team_abbr, season)
        if not speed_df.empty and "sprint_speed" in speed_df.columns:
            spd_t = Table(title="Sprint Speed (ft/sec)", box=box.SIMPLE, show_lines=False)
            spd_t.add_column("Player",        style="cyan",  min_width=20)
            spd_t.add_column("Speed (ft/s)",  style="bold white", justify="right")
            spd_t.add_column("HP→1B (sec)",   style="white", justify="right")

            nm_col  = "player_name" if "player_name" in speed_df.columns else None
            hp1b_col = next((c for c in ("hp_to_1b", "home_to_first") if c in speed_df.columns), None)

            for _, row in speed_df.sort_values("sprint_speed", ascending=False).iterrows():
                spd  = float(row["sprint_speed"])
                # League avg sprint speed ~27 ft/sec; elite ~29+
                spd_c = "green" if spd >= 28.5 else ("yellow" if spd >= 27.0 else "red")
                spd_t.add_row(
                    str(row[nm_col]) if nm_col else "-",
                    f"[{spd_c}]{spd:.1f}[/{spd_c}]",
                    f"{float(row[hp1b_col]):.2f}" if hp1b_col else "-",
                )
            console.print(spd_t)
