"""
Historical trends and multi-season comparisons — Day 5.

Covers:
  - Season-over-season W-L and win% (configurable year range)
  - Current season pace overlaid on notable/championship seasons
  - All-time records within reach
  - Head-to-head historical records vs. rivals
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from client.mlb_client import MLBClient
from config import CACHE_DIR, HISTORY_START, TEAMS

log = logging.getLogger(__name__)

# Notable seasons for Red Sox (and a few other franchises) — used as chart overlays
NOTABLE_SEASONS: dict[str, dict[int, str]] = {
    "BOS": {2004: "WS Champs", 2007: "WS Champs", 2013: "WS Champs",
            2018: "WS Champs (108W)", 2011: "Collapse", 1986: "WS Loss"},
    "NYY": {1998: "125W", 2009: "WS Champs", 1927: "Murderers Row"},
    "LAD": {2020: "WS Champs", 2017: "104W", 2022: "111W"},
}


# ---------------------------------------------------------------------------
# Season records fetch
# ---------------------------------------------------------------------------

def fetch_season_records(
    team_id: int,
    start_year: int = HISTORY_START,
    end_year: int | None = None,
    client: MLBClient | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch end-of-season W-L records for every year from start_year to end_year.

    Results are cached as history_{team_id}.parquet (refreshed if force_refresh).

    Returns: season, wins, losses, win_pct, run_diff, div_rank, games_back
    """
    import datetime
    cache_path = CACHE_DIR / f"history_{team_id}.parquet"
    end_year   = end_year or datetime.date.today().year

    if cache_path.exists() and not force_refresh:
        df = pd.read_parquet(cache_path)
        # Supplement with any seasons missing from the cache
        cached_years = set(df["season"].tolist())
        missing = [y for y in range(start_year, end_year + 1) if y not in cached_years]
        if not missing:
            return df.sort_values("season").reset_index(drop=True)
        extra = _fetch_years(team_id, missing, client or MLBClient())
        df    = pd.concat([df, extra], ignore_index=True).drop_duplicates("season")
        df.to_parquet(cache_path, index=False)
        return df.sort_values("season").reset_index(drop=True)

    years = list(range(start_year, end_year + 1))
    df    = _fetch_years(team_id, years, client or MLBClient())
    if not df.empty:
        df.to_parquet(cache_path, index=False)
    return df.sort_values("season").reset_index(drop=True)


def _fetch_years(team_id: int, years: list[int], client: MLBClient) -> pd.DataFrame:
    rows: list[dict] = []
    for year in years:
        try:
            standings = client.get_standings(year)
        except Exception as e:
            log.warning("Could not fetch standings for %d: %s", year, e)
            continue

        for div_block in standings:
            for tr in div_block.get("teamRecords", []):
                if tr.get("team", {}).get("id") != team_id:
                    continue
                lr = tr.get("leagueRecord", {})
                w  = lr.get("wins", 0)
                l  = lr.get("losses", 0)
                rows.append(dict(
                    season    = year,
                    wins      = w,
                    losses    = l,
                    win_pct   = float(lr.get("pct", 0) or 0),
                    run_diff  = tr.get("runDifferential", 0),
                    div_rank  = int(tr.get("divisionRank", 0)),
                    games_back= str(tr.get("gamesBack", "-")),
                ))
                break

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Records within reach
# ---------------------------------------------------------------------------

def records_within_reach(
    current_games: pd.DataFrame,
    historical: pd.DataFrame,
    team_abbr: str,
) -> list[dict]:
    """
    Compare current season to franchise bests and flag records within striking distance.

    Returns list of dicts: {record, current, franchise_best, holder_season, gap}
    """
    if historical.empty or current_games.empty:
        return []

    finished = current_games[current_games["status"] == "Final"]
    w  = int((finished["result"] == "W").sum())
    l  = int((finished["result"] == "L").sum())
    g  = w + l

    from analysis.standings import pace_projection
    proj_w, _ = pace_projection(w, l)

    records: list[dict] = []

    # Most wins in a season
    best_season = historical.loc[historical["wins"].idxmax()]
    records.append(dict(
        record="Most wins in a season",
        current=proj_w,
        franchise_best=int(best_season["wins"]),
        holder_season=int(best_season["season"]),
        gap=int(best_season["wins"]) - proj_w,
    ))

    # Best win% season
    best_pct = historical.loc[historical["win_pct"].idxmax()]
    proj_pct = round(w / g, 3) if g > 0 else 0.0
    records.append(dict(
        record="Best win% season",
        current=f"{proj_pct:.3f}",
        franchise_best=f"{best_pct['win_pct']:.3f}",
        holder_season=int(best_pct["season"]),
        gap=None,
    ))

    # Worst wins (context)
    worst_season = historical.loc[historical["wins"].idxmin()]
    records.append(dict(
        record="Fewest wins (franchise worst)",
        current=proj_w,
        franchise_best=int(worst_season["wins"]),
        holder_season=int(worst_season["season"]),
        gap=None,
    ))

    return records


# ---------------------------------------------------------------------------
# Head-to-head history
# ---------------------------------------------------------------------------

def head_to_head_history(
    team_id: int,
    rival_ids: list[int],
    start_year: int = 2010,
    end_year: int | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Season-by-season W-L vs each rival, fetched from cached game logs.

    Reads from the games cache files already built by the Fetcher.
    Returns: season, opponent_id, wins, losses, win_pct
    """
    import datetime
    end_year = end_year or datetime.date.today().year
    rows: list[dict] = []

    for year in range(start_year, end_year + 1):
        cache_path = CACHE_DIR / f"games_{team_id}_{year}.parquet"
        if not cache_path.exists():
            continue
        games = pd.read_parquet(cache_path)
        finished = games[games["status"] == "Final"]
        for rid in rival_ids:
            vs = finished[finished["opponent_id"] == rid]
            if vs.empty:
                continue
            w = int((vs["result"] == "W").sum())
            l = int((vs["result"] == "L").sum())
            rows.append(dict(
                season=year, opponent_id=rid,
                wins=w, losses=l,
                win_pct=round(w / (w + l), 3) if (w + l) > 0 else 0.0,
            ))

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Pace comparison data builder
# ---------------------------------------------------------------------------

def build_pace_comparison(
    current_games: pd.DataFrame,
    team_id: int,
    reference_years: list[int],
) -> dict[int, pd.DataFrame]:
    """
    Load game logs for each reference year from cache and return as
    {year: games_df} dict for use in pace_comparison_chart().
    Only loads years that have a cached games file.
    """
    result: dict[int, pd.DataFrame] = {}
    for year in reference_years:
        path = CACHE_DIR / f"games_{team_id}_{year}.parquet"
        if path.exists():
            result[year] = pd.read_parquet(path)
        else:
            log.info("No cached games for %d — skipping pace comparison", year)
    return result


# ---------------------------------------------------------------------------
# Rich terminal output
# ---------------------------------------------------------------------------

def print_history(console, team_id: int, team_abbr: str, season: int,
                  current_games: pd.DataFrame) -> None:
    """Print historical context panel."""
    from rich.table import Table
    from rich import box

    historical = fetch_season_records(team_id)
    if historical.empty:
        console.print("[yellow]No historical data cached.[/yellow]")
        return

    # Season records table (last 10 seasons)
    recent = historical.tail(15).sort_values("season", ascending=False)
    t = Table(title=f"Season Records ({recent['season'].min()}–{recent['season'].max()})",
              box=box.SIMPLE, show_lines=False)
    t.add_column("Season",  style="cyan",  justify="right")
    t.add_column("W",       style="green", justify="right")
    t.add_column("L",       style="red",   justify="right")
    t.add_column("Win%",    style="white", justify="right")
    t.add_column("RunDiff", style="cyan",  justify="right")
    t.add_column("Div",     style="dim",   justify="right")

    notable = NOTABLE_SEASONS.get(team_abbr, {})
    for _, row in recent.iterrows():
        yr     = int(row["season"])
        note   = f"  ★ {notable[yr]}" if yr in notable else ""
        rd     = int(row.get("run_diff", 0))
        rd_str = f"+{rd}" if rd > 0 else str(rd)
        t.add_row(
            f"[bold]{yr}[/bold]{note}", str(row["wins"]), str(row["losses"]),
            f"{row['win_pct']:.3f}", rd_str, str(int(row.get("div_rank", 0))),
        )
    console.print(t)

    # Records within reach
    records = records_within_reach(current_games, historical, team_abbr)
    if records:
        r_t = Table(title="Franchise Records Context", box=box.SIMPLE, show_lines=False)
        r_t.add_column("Record",          style="cyan",  min_width=28)
        r_t.add_column("Current Pace",    style="white", justify="right")
        r_t.add_column("Franchise Best",  style="yellow",justify="right")
        r_t.add_column("Season",          style="dim",   justify="right")
        for rec in records:
            r_t.add_row(
                rec["record"], str(rec["current"]),
                str(rec["franchise_best"]), str(rec["holder_season"]),
            )
        console.print(r_t)
