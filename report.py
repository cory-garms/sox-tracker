"""
CLI entry point — print the team dashboard to the terminal.

Reads from local cache (run fetch.py first).

Usage:
    python report.py                         # BOS 2026
    python report.py --team NYY --season 2025
    python report.py --section offense       # only print offense section
    python report.py --section pitching
    python report.py --section streaks
    python report.py --section standings
"""

from __future__ import annotations

import argparse
import logging
import sys

from rich.console import Console
from rich.logging import RichHandler

import config
from config import TEAMS
from data.fetcher import Fetcher

console = Console()

SECTIONS = ("overview", "offense", "pitching", "defense", "streaks", "standings")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Print the MLB team dashboard.")
    parser.add_argument("--team",    default=config.TEAM_ABBR)
    parser.add_argument("--season",  type=int, default=config.SEASON)
    parser.add_argument("--section", choices=SECTIONS, default=None,
                        help="Print only one section (default: all)")
    args = parser.parse_args()

    _setup_logging()

    abbr = args.team.upper()
    if abbr not in TEAMS:
        console.print(f"[red]Unknown team '{abbr}'.[/red]")
        sys.exit(1)

    team_info = TEAMS[abbr]
    team_id   = team_info["id"]
    season    = args.season

    fetcher = Fetcher(team_id=team_id, season=season)

    try:
        games    = fetcher.load("games")
        batting  = fetcher.load("batting")
        pitching = fetcher.load("pitching")
        fielding = fetcher.load("fielding")
        roster   = fetcher.load("roster")
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    console.rule(f"[bold cyan]{team_info['name']} — {season}[/bold cyan]")

    sections_to_run = [args.section] if args.section else list(SECTIONS)

    # Lazy imports so individual analysis modules can be developed independently
    for section in sections_to_run:
        if section == "overview":
            from analysis.standings import print_overview
            print_overview(console, games, team_info,
                           batting=batting, pitching=pitching, fielding=fielding)

        elif section == "standings":
            from analysis.standings import print_standings
            print_standings(console, team_id, season)

        elif section == "offense":
            from analysis.offense import print_offense
            print_offense(console, batting, games, roster,
                          season=season, team_abbr=abbr)

        elif section == "pitching":
            from analysis.pitching import print_pitching
            print_pitching(console, pitching, games, roster)

        elif section == "defense":
            from analysis.defense import print_defense
            print_defense(console, fielding, roster, games=games,
                          team_abbr=abbr, season=season)

        elif section == "streaks":
            from analysis.streaks import print_streaks
            print_streaks(console, games, batting, pitching)


if __name__ == "__main__":
    main()
