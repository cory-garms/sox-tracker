"""
Lossless migration from Parquet cache files (odds_history.parquet, bet_log.parquet)
into PostgreSQL / SQLite database tables.

Usage:
    python scripts/migrate_parquet_to_db.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Add repo root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from rich.console import Console
from rich.table import Table

import config
from backend.database import get_db_session, init_db
from backend.models import BetLog, OddsSnapshot
from backend.repository import (
    grade_bets_from_snapshots,
    insert_bet,
    insert_odds_snapshots,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("migrate")
console = Console()


def migrate_odds_history(session) -> int:
    """Migrate data/cache/odds_history.parquet into odds_snapshots table."""
    path = config.CACHE_DIR / "odds_history.parquet"
    if not path.exists():
        console.print(f"[yellow]No odds history found at {path}[/yellow]")
        return 0

    df = pd.read_parquet(path)
    if df.empty:
        console.print("[yellow]Odds history parquet is empty.[/yellow]")
        return 0

    rows = df.to_dict(orient="records")
    inserted = insert_odds_snapshots(session, rows)
    console.print(f"[green]✓ Migrated {inserted} new odds snapshots from {len(df)} parquet rows.[/green]")
    return inserted


def migrate_bet_log(session) -> int:
    """Migrate data/cache/bet_log.parquet into bet_log table."""
    path = config.CACHE_DIR / "bet_log.parquet"
    if not path.exists():
        console.print(f"[yellow]No bet log found at {path}[/yellow]")
        return 0

    df = pd.read_parquet(path)
    if df.empty:
        console.print("[yellow]Bet log parquet is empty.[/yellow]")
        return 0

    count = 0
    for r in df.to_dict(orient="records"):
        # Check if already exists based on placed_at and selection to avoid duplicates
        existing = session.query(BetLog).filter_by(
            placed_at=str(r.get("placed_at", "")),
            selection=str(r.get("selection", "")),
            market=str(r.get("market", "")),
        ).first()

        if existing is None:
            insert_bet(session, r)
            count += 1

    console.print(f"[green]✓ Migrated {count} bets from {len(df)} parquet rows.[/green]")
    return count


def main() -> None:
    console.print("[bold cyan]Starting Parquet -> Database Migration for dirtywater...[/bold cyan]")
    init_db()

    with get_db_session() as session:
        odds_count = migrate_odds_history(session)
        bets_count = migrate_bet_log(session)
        graded_count = grade_bets_from_snapshots(session)

        # Verification table
        total_odds = session.query(OddsSnapshot).count()
        total_bets = session.query(BetLog).count()

        table = Table(title="Migration Summary", header_style="bold magenta")
        table.add_column("Table", style="cyan")
        table.add_column("Imported Rows", justify="right")
        table.add_column("Total Rows in DB", justify="right", style="bold green")

        table.add_row("odds_snapshots", str(odds_count), str(total_odds))
        table.add_row("bet_log", str(bets_count), str(total_bets))
        table.add_row("Graded Bets", str(graded_count), str(total_bets))

        console.print(table)
        console.print(f"[bold green]Migration complete! Target: {config.DATABASE_URL}[/bold green]")


if __name__ == "__main__":
    main()
