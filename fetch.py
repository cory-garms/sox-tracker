"""
CLI entry point — fetch and cache all data for a team/season.

Usage:
    python fetch.py                          # BOS 2026 (defaults from config.py)
    python fetch.py --team NYY --season 2025
    python fetch.py --team BOS --refresh     # force re-fetch, ignore cache
    python fetch.py --list-teams             # print all team abbreviations + IDs
"""

from __future__ import annotations

import argparse
import logging
import sys

from rich.console import Console
from rich.table import Table
from rich.logging import RichHandler

import config
from config import TEAMS
from data.fetcher import Fetcher

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


def _print_teams() -> None:
    table = Table(title="MLB Teams", show_lines=True)
    table.add_column("Abbr", style="bold cyan", width=6)
    table.add_column("ID",   style="yellow",    width=6)
    table.add_column("Name", style="white")
    table.add_column("Lg",   style="dim",        width=4)
    table.add_column("Div",  style="dim",        width=8)

    al = {k: v for k, v in TEAMS.items() if v["league"] == "AL"}
    nl = {k: v for k, v in TEAMS.items() if v["league"] == "NL"}

    for abbr, info in sorted(al.items()):
        table.add_row(abbr, str(info["id"]), info["name"], "AL", info["division"])
    for abbr, info in sorted(nl.items()):
        table.add_row(abbr, str(info["id"]), info["name"], "NL", info["division"])

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and cache MLB stats for a team/season."
    )
    parser.add_argument("--team",       default=config.TEAM_ABBR,
                        help=f"Team abbreviation (default: {config.TEAM_ABBR})")
    parser.add_argument("--season",     type=int, default=config.SEASON,
                        help=f"Season year (default: {config.SEASON})")
    parser.add_argument("--refresh",    action="store_true",
                        help="Force re-fetch, ignoring cached data")
    parser.add_argument("--list-teams", action="store_true",
                        help="Print all supported team abbreviations and exit")
    parser.add_argument("--verbose",    action="store_true",
                        help="Show debug-level logging")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    log = logging.getLogger(__name__)

    if args.list_teams:
        _print_teams()
        return

    abbr = args.team.upper()
    if abbr not in TEAMS:
        console.print(f"[red]Unknown team '{abbr}'. Run with --list-teams to see options.[/red]")
        sys.exit(1)

    team_info = TEAMS[abbr]
    team_id   = team_info["id"]
    season    = args.season

    console.rule(f"[bold cyan]{team_info['name']} — {season} Season[/bold cyan]")
    console.print(f"  Team ID : [yellow]{team_id}[/yellow]")
    console.print(f"  Cache   : [dim]{config.CACHE_DIR}[/dim]\n")

    fetcher = Fetcher(team_id=team_id, season=season, force_refresh=args.refresh)

    with console.status("[bold green]Fetching data…[/bold green]"):
        tables = fetcher.fetch_all()

    # Summary
    summary = Table(title="Fetch Summary", show_lines=False)
    summary.add_column("Table",   style="cyan")
    summary.add_column("Rows",    style="yellow", justify="right")
    summary.add_column("Columns", style="dim",    justify="right")

    for name, df in tables.items():
        summary.add_row(name, str(len(df)), str(len(df.columns)))

    console.print(summary)
    console.print("\n[bold green]Done.[/bold green] Run [cyan]python report.py[/cyan] to see the dashboard.")


if __name__ == "__main__":
    main()
