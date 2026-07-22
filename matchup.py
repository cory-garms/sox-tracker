"""
CLI entry point — Pre-Game Matchup Intelligence Engine.

Usage:
    python matchup.py                          # Today's game (BOS 2026)
    python matchup.py --date 2026-07-21
    python matchup.py --opponent BAL
    python matchup.py --refresh                 # re-fetch latest data
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

import config
from client.mlb_client import MLBClient
from data.fetcher import Fetcher
from analysis.matchup import (
    fetch_game_preview,
    fetch_doubleheader_previews,
    starter_season_summary,
    platoon_recommendations,
    bullpen_availability,
    head_to_head_summary,
)

console = Console()


def print_matchup(
    team_abbr: str = config.TEAM_ABBR,
    season: int = config.SEASON,
    date_str: str = "2026-07-21",
    force_refresh: bool = False,
) -> None:
    """Render rich pre-game matchup preview to terminal."""
    team_id = config.TEAMS.get(team_abbr, {}).get("id", config.TEAM_ID)
    team_name = config.TEAMS.get(team_abbr, {}).get("name", "Boston Red Sox")

    client = MLBClient()
    fetcher = Fetcher(team_id=team_id, season=season, client=client, force_refresh=force_refresh)

    games = fetcher.load("games")
    batting = fetcher.load("batting")
    pitching = fetcher.load("pitching")

    # 1. Fetch game previews (handles doubleheaders)
    previews = fetch_doubleheader_previews(client, team_id, date_str)

    if not previews:
        # Fallback to last played date if no games scheduled today
        if not games.empty:
            date_str = str(games[games["status"] == "Final"].iloc[-1]["game_date"])
            previews = fetch_doubleheader_previews(client, team_id, date_str)

    if not previews:
        console.print(f"[bold red]No games found for date {date_str}.[/bold red]")
        return

    is_doubleheader = len(previews) > 1
    p1 = previews[0]
    opp_abbr = p1.get("opponent_abbr", "BAL")
    opp_id = p1.get("opponent_id", 110)
    opp_name = config.TEAMS.get(opp_abbr, {}).get("name", f"Team {opp_id}")
    is_home = p1.get("is_home", True)
    loc_str = "Fenway Park (Home)" if is_home else f"{p1.get('venue', 'Away')}"

    # 2. Header Panel
    console.print()
    if is_doubleheader:
        header_text = (
            f"[bold white]{team_name}[/bold white]  [bold yellow]vs.[/bold yellow]  [bold cyan]{opp_name}[/bold cyan]  [bold red]⚡ SPLIT DOUBLEHEADER[/bold red]\n"
            f"[dim]Date: {p1.get('game_date', date_str)}  ·  Venue: {loc_str}  ·  Format: Day/Night Split (Game 1 & Game 2)[/dim]"
        )
        console.print(Panel(header_text, title="⚾ SPLIT DOUBLEHEADER INTELLIGENCE REPORT", border_style="bold red", box=box.ROUNDED))
    else:
        header_text = (
            f"[bold white]{team_name}[/bold white]  [bold yellow]vs.[/bold yellow]  [bold cyan]{opp_name}[/bold cyan]\n"
            f"[dim]Date: {p1.get('game_date', date_str)}  ·  Venue: {loc_str}  ·  Status: {p1.get('status', 'Scheduled')}[/dim]"
        )
        console.print(Panel(header_text, title="⚾ PRE-GAME MATCHUP ENGINE", border_style="bold green", box=box.ROUNDED))

    # 3. Probable Starters Comparison Table
    if is_doubleheader:
        p2 = previews[1]
        s1_our = starter_season_summary(client, p1.get("our_probable", {}).get("id"), season)
        s1_opp = starter_season_summary(client, p1.get("opp_probable", {}).get("id"), season)
        s2_our = starter_season_summary(client, p2.get("our_probable", {}).get("id"), season)
        s2_opp = starter_season_summary(client, p2.get("opp_probable", {}).get("id"), season)

        p_table = Table(title="⚾ Doubleheader Probable Starters (Game 1 & Game 2)", box=box.SIMPLE, show_lines=True)
        p_table.add_column("Metric", style="cyan", width=18)
        p_table.add_column(f"G1 {team_abbr}\n({s1_our.get('name', 'TBD')})", style="bold green", justify="center")
        p_table.add_column(f"G1 {opp_abbr}\n({s1_opp.get('name', 'TBD')})", style="bold yellow", justify="center")
        p_table.add_column(f"G2 {team_abbr}\n({s2_our.get('name', 'TBD')})", style="bold green", justify="center")
        p_table.add_column(f"G2 {opp_abbr}\n({s2_opp.get('name', 'TBD')})", style="bold yellow", justify="center")

        p_table.add_row("Throwing Hand", s1_our.get("hand", "R"), s1_opp.get("hand", "R"), s2_our.get("hand", "R"), s2_opp.get("hand", "R"))
        p_table.add_row("Season W-L", f"{s1_our.get('w', 0)}-{s1_our.get('l', 0)}", f"{s1_opp.get('w', 0)}-{s1_opp.get('l', 0)}", f"{s2_our.get('w', 0)}-{s2_our.get('l', 0)}", f"{s2_opp.get('w', 0)}-{s2_opp.get('l', 0)}")
        p_table.add_row("ERA", str(s1_our.get("era", "-")), str(s1_opp.get("era", "-")), str(s2_our.get("era", "-")), str(s2_opp.get("era", "-")))
        p_table.add_row("WHIP", str(s1_our.get("whip", "-")), str(s1_opp.get("whip", "-")), str(s2_our.get("whip", "-")), str(s2_opp.get("whip", "-")))
        p_table.add_row("K / 9", str(s1_our.get("k9", "-")), str(s1_opp.get("k9", "-")), str(s2_our.get("k9", "-")), str(s2_opp.get("k9", "-")))
        p_table.add_row("BB / 9", str(s1_our.get("bb9", "-")), str(s1_opp.get("bb9", "-")), str(s2_our.get("bb9", "-")), str(s2_opp.get("bb9", "-")))
        p_table.add_row("Innings Pitched", str(s1_our.get("ip", 0)), str(s1_opp.get("ip", 0)), str(s2_our.get("ip", 0)), str(s2_opp.get("ip", 0)))
        console.print(p_table)

    else:
        our_prob = p1.get("our_probable", {})
        opp_prob = p1.get("opp_probable", {})
        our_starter_stats = starter_season_summary(client, our_prob.get("id"), season)
        opp_starter_stats = starter_season_summary(client, opp_prob.get("id"), season)

        p_table = Table(title="⚾ Probable Starters Comparison", box=box.SIMPLE, show_lines=True)
        p_table.add_column("Metric", style="cyan", width=22)
        p_table.add_column(f"{team_abbr} Starter ({our_starter_stats.get('name', 'TBD')})", style="bold green", justify="center")
        p_table.add_column(f"{opp_abbr} Starter ({opp_starter_stats.get('name', 'TBD')})", style="bold yellow", justify="center")

        p_table.add_row("Throwing Hand", our_starter_stats.get("hand", "R"), opp_starter_stats.get("hand", "R"))
        p_table.add_row("Season W-L", f"{our_starter_stats.get('w', 0)}-{our_starter_stats.get('l', 0)}", f"{opp_starter_stats.get('w', 0)}-{opp_starter_stats.get('l', 0)}")
        p_table.add_row("ERA", str(our_starter_stats.get("era", "-")), str(opp_starter_stats.get("era", "-")))
        p_table.add_row("WHIP", str(our_starter_stats.get("whip", "-")), str(opp_starter_stats.get("whip", "-")))
        p_table.add_row("K / 9", str(our_starter_stats.get("k9", "-")), str(opp_starter_stats.get("k9", "-")))
        p_table.add_row("BB / 9", str(our_starter_stats.get("bb9", "-")), str(opp_starter_stats.get("bb9", "-")))
        p_table.add_row("Innings Pitched", str(our_starter_stats.get("ip", 0)), str(opp_starter_stats.get("ip", 0)))
        console.print(p_table)

    # 4. Platoon Lineup Recommendations
    g1_opp_hand = starter_season_summary(client, p1.get("opp_probable", {}).get("id"), season).get("hand", "R")
    plat_df = platoon_recommendations(batting, g1_opp_hand, season)

    if not plat_df.empty:
        title_suffix = f"(Game 1 vs {g1_opp_hand}HP)" if is_doubleheader else f"(vs {g1_opp_hand}HP Pitching)"
        plat_table = Table(title=f"💥 {team_abbr} Hitting Advantage {title_suffix}", box=box.SIMPLE)
        plat_table.add_column("Hitter", style="cyan")
        plat_table.add_column("AB", justify="right")
        plat_table.add_column("AVG", justify="right")
        plat_table.add_column("OBP", justify="right")
        plat_table.add_column("SLG", justify="right")
        plat_table.add_column("OPS", style="bold green", justify="right")
        plat_table.add_column("HR", justify="right")
        plat_table.add_column("Platoon Δ (L-R)", justify="right")

        for _, r in plat_df.head(8).iterrows():
            delta_str = f"+{r['ops_delta']:.3f}" if r['ops_delta'] >= 0 else f"{r['ops_delta']:.3f}"
            delta_style = "[green]" if r['ops_delta'] >= 0.050 else ("[red]" if r['ops_delta'] <= -0.050 else "[white]")
            plat_table.add_row(
                r["player_name"],
                str(int(r["ab"])),
                f"{r['avg']:.3f}",
                f"{r['obp']:.3f}",
                f"{r['slg']:.3f}",
                f"{r['ops']:.3f}",
                str(int(r["hr"])),
                f"{delta_style}{delta_str}[/{delta_style}]",
            )
        console.print(plat_table)

    # 5. Bullpen Availability Matrix (with 18-inning Workload note for doubleheaders)
    bp_df = bullpen_availability(pitching, ref_date_str=date_str, days=3)
    if not bp_df.empty:
        bp_title = f"🛡️ {team_abbr} Bullpen Workload Capacity (18-Inning Doubleheader)" if is_doubleheader else f"🛡️ {team_abbr} Bullpen Rest & Availability"
        bp_table = Table(title=bp_title, box=box.SIMPLE)
        bp_table.add_column("Reliever", style="cyan")
        bp_table.add_column("1-Day Ago", justify="right")
        bp_table.add_column("2-Days Ago", justify="right")
        bp_table.add_column("3-Days Ago", justify="right")
        bp_table.add_column("3-Day Total", justify="right")
        bp_table.add_column("Availability", justify="center")

        for _, r in bp_df.iterrows():
            bp_table.add_row(
                r["player_name"],
                str(r["d1_pitches"]),
                str(r["d2_pitches"]),
                str(r["d3_pitches"]),
                str(r["tot_3d"]),
                r["status"],
            )
        console.print(bp_table)

    # 6. Head-to-Head Season Series History
    h2h = head_to_head_summary(games, opp_id)
    h2h_table = Table(title=f"📊 2026 Head-to-Head vs {opp_abbr}", box=box.SIMPLE)
    h2h_table.add_column("Games Played", justify="center")
    h2h_table.add_column("W - L", style="bold green", justify="center")
    h2h_table.add_column("Win%", justify="center")
    h2h_table.add_column("Runs Scored", style="yellow", justify="center")
    h2h_table.add_column("Runs Allowed", style="yellow", justify="center")
    h2h_table.add_column("Run Diff", style="bold blue", justify="center")

    h2h_table.add_row(
        str(h2h["games_played"]),
        f"{h2h['wins']} - {h2h['losses']}",
        f"{h2h['win_pct']:.3f}",
        str(h2h["rs"]),
        str(h2h["ra"]),
        f"{'+' if h2h['diff'] > 0 else ''}{h2h['diff']}",
    )
    console.print(h2h_table)
    console.print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-Game Matchup Intelligence Engine.")
    parser.add_argument("--team", default=config.TEAM_ABBR, help="Team abbreviation (default: BOS)")
    parser.add_argument("--season", type=int, default=config.SEASON, help="Season (default: 2026)")
    parser.add_argument("--opponent", default="BAL", help="Opponent abbreviation (default: BAL)")
    parser.add_argument("--date", default=date.today().strftime("%Y-%m-%d"), help="Game date YYYY-MM-DD (default: today)")
    parser.add_argument("--refresh", action="store_true", help="Force re-fetch cache")
    args = parser.parse_args()

    print_matchup(
        team_abbr=args.team,
        season=args.season,
        date_str=args.date,
        force_refresh=args.refresh,
    )


if __name__ == "__main__":
    main()
