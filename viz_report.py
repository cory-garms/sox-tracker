"""
CLI entry point — generate charts and the interactive HTML dashboard.

Usage:
    python viz_report.py                          # BOS 2026, all charts
    python viz_report.py --team BOS --season 2025
    python viz_report.py --png                    # also export PNGs (requires kaleido)
    python viz_report.py --history                # include historical win% chart
    python viz_report.py --open                   # open dashboard in browser when done
"""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich import box

import config
from config import TEAMS
from data.fetcher import Fetcher

console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate MLB team dashboard charts.")
    parser.add_argument("--team",    default=config.TEAM_ABBR)
    parser.add_argument("--season",  type=int, default=config.SEASON)
    parser.add_argument("--png",     action="store_true",
                        help="Export static PNG images (requires: pip install kaleido)")
    parser.add_argument("--history", action="store_true",
                        help="Fetch + render historical win%% bar chart")
    parser.add_argument("--pace",    nargs="+", type=int, metavar="YEAR",
                        help="Years to overlay on pace comparison chart (e.g. --pace 2018 2004)")
    parser.add_argument("--open",    action="store_true",
                        help="Open the dashboard in the default browser when done")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    abbr = args.team.upper()
    if abbr not in TEAMS:
        console.print(f"[red]Unknown team '{abbr}'. Run `python fetch.py --list-teams`.[/red]")
        sys.exit(1)

    team_info = TEAMS[abbr]
    team_id   = team_info["id"]
    team_name = team_info["name"]
    season    = args.season

    fetcher = Fetcher(team_id=team_id, season=season)
    try:
        games    = fetcher.load("games")
        batting  = fetcher.load("batting")
        pitching = fetcher.load("pitching")
        fielding = fetcher.load("fielding")
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    console.rule(f"[bold cyan]{team_name} — {season} Viz Report[/bold cyan]")

    output_files: list[str] = []

    # -----------------------------------------------------------------------
    # Main dashboard
    # -----------------------------------------------------------------------
    with console.status("[bold green]Building dashboard…[/bold green]"):
        from viz.dashboard import build
        dash_path = build(
            games=games, batting=batting, pitching=pitching, fielding=fielding,
            team_name=team_name, team_abbr=abbr, season=season,
        )
    console.print(f"[green]Dashboard[/green] → [cyan]{dash_path}[/cyan]")
    output_files.append(str(dash_path))

    # -----------------------------------------------------------------------
    # Historical win% chart
    # -----------------------------------------------------------------------
    if args.history:
        with console.status("[bold green]Fetching historical records…[/bold green]"):
            from analysis.history import fetch_season_records, NOTABLE_SEASONS
            from viz.charts import multi_season_win_pct
            from viz.exports import save_html

            historical = fetch_season_records(team_id)
            if not historical.empty:
                notable = NOTABLE_SEASONS.get(abbr, {})
                fig = multi_season_win_pct(historical, team_name, highlight_seasons=notable)
                hist_path = config.OUTPUT_DIR / f"history_{abbr}.html"
                save_html(fig, hist_path)
                console.print(f"[green]History chart[/green] → [cyan]{hist_path}[/cyan]")
                output_files.append(str(hist_path))

    # -----------------------------------------------------------------------
    # Pace comparison chart
    # -----------------------------------------------------------------------
    if args.pace:
        with console.status("[bold green]Building pace comparison…[/bold green]"):
            from analysis.history import build_pace_comparison
            from viz.charts import pace_comparison_chart
            from viz.exports import save_html

            ref_seasons = build_pace_comparison(games, team_id, args.pace)
            if ref_seasons:
                fig = pace_comparison_chart(games, ref_seasons, team_name)
                pace_path = config.OUTPUT_DIR / f"pace_{abbr}_{season}.html"
                save_html(fig, pace_path)
                console.print(f"[green]Pace chart[/green] → [cyan]{pace_path}[/cyan]")
                output_files.append(str(pace_path))
            else:
                console.print("[yellow]No cached game logs found for requested years "
                              "(fetch them first with fetch.py --season YEAR).[/yellow]")

    # -----------------------------------------------------------------------
    # PNG exports
    # -----------------------------------------------------------------------
    if args.png:
        with console.status("[bold green]Exporting PNGs…[/bold green]"):
            from viz.dashboard import build_png_exports
            pngs = build_png_exports(
                games=games, batting=batting, pitching=pitching,
                team_name=team_name, team_abbr=abbr, season=season,
            )
        for p in pngs:
            console.print(f"[green]PNG[/green] → [cyan]{p}[/cyan]")
            output_files.append(str(p))

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    summary = Table(title="Output Files", box=box.SIMPLE, show_lines=False)
    summary.add_column("File", style="cyan")
    for f in output_files:
        summary.add_row(f)
    console.print(summary)

    if args.open:
        import os
        webbrowser.open(f"file://{os.path.abspath(str(dash_path))}")


if __name__ == "__main__":
    main()
