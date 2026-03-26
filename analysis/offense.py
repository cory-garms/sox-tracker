"""
Offensive analytics — team and player.

Day 2: team aggregates, leaderboard, lineup slots.
Day 3: BABIP, Statcast overlay, platoon splits, hot/cold, career context.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Team-level aggregates
# ---------------------------------------------------------------------------

def team_offense_summary(batting: pd.DataFrame, games: pd.DataFrame) -> dict:
    """
    Return team-level offensive stats for the season.

    Keys: avg, obp, slg, ops, r_per_g, hr, sb, bb_pct, k_pct, babip
    """
    if batting.empty:
        return {}

    g       = len(games[games["status"] == "Final"])
    ab      = int(batting["ab"].sum())
    h       = int(batting["h"].sum())
    bb      = int(batting["bb"].sum())
    ibb     = int(batting["ibb"].sum())
    hbp     = int(batting["hbp"].sum())
    sf      = int(batting["sac_fly"].sum())
    so      = int(batting["so"].sum())
    pa      = int(batting["pa"].sum())
    hr      = int(batting["hr"].sum())
    sb      = int(batting["sb"].sum())
    doubles = int(batting["doubles"].sum())
    triples = int(batting["triples"].sum())

    avg   = h / ab if ab > 0 else 0.0
    obp_d = ab + bb + hbp + sf
    obp   = (h + bb + hbp) / obp_d if obp_d > 0 else 0.0
    tb    = h + doubles + 2 * triples + 3 * hr
    slg   = tb / ab if ab > 0 else 0.0

    babip_num = h - hr
    babip_den = ab - so - hr + sf
    babip     = babip_num / babip_den if babip_den > 0 else 0.0

    r_per_g = games[games["status"] == "Final"]["runs_scored"].mean() if g > 0 else 0.0

    return dict(
        avg=round(avg, 3), obp=round(obp, 3), slg=round(slg, 3), ops=round(obp + slg, 3),
        babip=round(babip, 3),
        r_per_g=round(r_per_g, 2),
        hr=hr, sb=sb, h=h, ab=ab, pa=pa,
        bb_pct=round(bb / pa * 100, 1) if pa > 0 else 0.0,
        k_pct=round(so / pa * 100, 1) if pa > 0 else 0.0,
    )


# ---------------------------------------------------------------------------
# Player season totals
# ---------------------------------------------------------------------------

def player_season_totals(batting: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate game-log rows into season totals per player.
    Includes BABIP; recomputes rate stats from counting totals for accuracy.
    """
    if batting.empty:
        return pd.DataFrame()

    agg = batting.groupby("player_id").agg(
        player_name=("player_name", "first"),
        g          =("game_pk",    "count"),
        ab         =("ab",         "sum"),
        pa         =("pa",         "sum"),
        h          =("h",          "sum"),
        doubles    =("doubles",    "sum"),
        triples    =("triples",    "sum"),
        hr         =("hr",         "sum"),
        rbi        =("rbi",        "sum"),
        r          =("r",          "sum"),
        bb         =("bb",         "sum"),
        ibb        =("ibb",        "sum"),
        so         =("so",         "sum"),
        hbp        =("hbp",        "sum"),
        sb         =("sb",         "sum"),
        cs         =("cs",         "sum"),
        sac_bunt   =("sac_bunt",   "sum"),
        sac_fly    =("sac_fly",    "sum"),
        gidp       =("gidp",       "sum"),
    ).reset_index()

    agg["avg"]    = (agg["h"] / agg["ab"]).where(agg["ab"] > 0, 0.0).round(3)
    obp_d         = agg["ab"] + agg["bb"] + agg["hbp"] + agg["sac_fly"]
    agg["obp"]    = ((agg["h"] + agg["bb"] + agg["hbp"]) / obp_d).where(obp_d > 0, 0.0).round(3)
    tb            = agg["h"] + agg["doubles"] + 2 * agg["triples"] + 3 * agg["hr"]
    agg["slg"]    = (tb / agg["ab"]).where(agg["ab"] > 0, 0.0).round(3)
    agg["ops"]    = (agg["obp"] + agg["slg"]).round(3)
    agg["bb_pct"] = (agg["bb"] / agg["pa"] * 100).where(agg["pa"] > 0, 0.0).round(1)
    agg["k_pct"]  = (agg["so"] / agg["pa"] * 100).where(agg["pa"] > 0, 0.0).round(1)

    # BABIP = (H - HR) / (AB - SO - HR + SF)
    babip_n       = agg["h"] - agg["hr"]
    babip_d       = agg["ab"] - agg["so"] - agg["hr"] + agg["sac_fly"]
    agg["babip"]  = (babip_n / babip_d).where(babip_d > 0, 0.0).round(3)

    return agg.sort_values("ops", ascending=False).reset_index(drop=True)


def batting_leaderboard(
    batting: pd.DataFrame,
    sort_by: str = "ops",
    min_pa: int = 50,
    top_n: int = 15,
) -> pd.DataFrame:
    """Season leaderboard, filtered to >= min_pa PA, sorted by sort_by."""
    totals = player_season_totals(batting)
    if totals.empty:
        return totals
    valid = {"avg", "obp", "slg", "ops", "hr", "rbi", "sb", "bb_pct", "k_pct", "babip"}
    col   = sort_by if sort_by in valid else "ops"
    return (
        totals[totals["pa"] >= min_pa]
        .sort_values(col, ascending=(col in ("k_pct",)))
        .head(top_n)
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Statcast overlay
# ---------------------------------------------------------------------------

def enrich_with_statcast(
    totals: pd.DataFrame,
    season: int,
    team_abbr: str,
) -> pd.DataFrame:
    """
    Join Baseball Savant Statcast data onto player season totals.

    Adds columns: exit_velocity_avg, barrel_batted_rate, hard_hit_percent,
                  xba, xslg, xwoba, xobp  (NaN when not available).
    """
    try:
        from client.savant_client import SavantClient
        savant_df = SavantClient().get_batter_statcast(season, team_abbr=team_abbr)
    except Exception as e:
        log.warning("Statcast fetch failed: %s", e)
        return totals

    if savant_df.empty or "player_id" not in savant_df.columns:
        return totals

    stat_cols = [
        "player_id", "exit_velocity_avg", "barrel_batted_rate",
        "hard_hit_percent", "xba", "xslg", "xwoba", "xobp",
    ]
    available = [c for c in stat_cols if c in savant_df.columns]
    merged = totals.merge(savant_df[available], on="player_id", how="left")
    return merged


# ---------------------------------------------------------------------------
# Platoon splits
# ---------------------------------------------------------------------------

def fetch_platoon_splits(
    player_ids: list[int],
    season: int,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Fetch vs-LHP / vs-RHP splits for a list of player IDs via the MLB Stats API.
    Results are cached as platoon_{season}.parquet.

    Returns: player_id, hand, ab, h, hr, bb, so, avg, obp, slg, ops
    """
    from client.mlb_client import MLBClient
    from config import CACHE_DIR

    cache_path = (cache_dir or CACHE_DIR) / f"platoon_{season}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    client = MLBClient()
    rows: list[dict] = []

    for pid in player_ids:
        try:
            data = client._get(
                f"/people/{pid}/stats",
                {
                    "stats": "statSplits",
                    "group": "hitting",
                    "season": season,
                    "sitCodes": "vl,vr",
                    "sportId": 1,
                },
            )
        except Exception as e:
            log.warning("Platoon fetch failed for player %d: %s", pid, e)
            continue

        for stat_block in data.get("stats", []):
            for split in stat_block.get("splits", []):
                sit  = split.get("split", {})
                code = sit.get("code", "")
                if code not in ("vl", "vr"):
                    continue

                s = split.get("stat", {})
                ab = int(s.get("atBats", 0))

                rows.append({
                    "player_id": pid,
                    "hand":      "vs LHP" if code == "vl" else "vs RHP",
                    "ab":        ab,
                    "h":         int(s.get("hits", 0)),
                    "hr":        int(s.get("homeRuns", 0)),
                    "bb":        int(s.get("baseOnBalls", 0)),
                    "so":        int(s.get("strikeOuts", 0)),
                    "avg":       float(s.get("avg", 0) or 0),
                    "obp":       float(s.get("obp", 0) or 0),
                    "slg":       float(s.get("slg", 0) or 0),
                    "ops":       float(s.get("ops", 0) or 0),
                })

    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_parquet(cache_path, index=False)
    return df


def platoon_table(batting: pd.DataFrame, season: int) -> pd.DataFrame:
    """
    Return platoon splits for all players in the batting log.
    Uses cached fetch if available.
    """
    player_ids = batting["player_id"].dropna().unique().tolist()
    splits = fetch_platoon_splits([int(p) for p in player_ids], season)
    if splits.empty:
        return pd.DataFrame()

    # Attach player names
    name_map = batting.groupby("player_id")["player_name"].first().reset_index()
    splits = splits.merge(name_map, on="player_id", how="left")
    return splits.sort_values(["player_name", "hand"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Hot / cold tracker
# ---------------------------------------------------------------------------

def rolling_slash(
    batting: pd.DataFrame,
    player_id: int,
    window: int = 7,
) -> pd.DataFrame:
    """Rolling AVG/OBP/SLG/OPS over last `window` games for one player."""
    player = (
        batting[batting["player_id"] == player_id]
        .sort_values("game_date")
        .reset_index(drop=True)
    )
    if player.empty:
        return pd.DataFrame()

    rows = []
    for i in range(len(player)):
        w   = player.iloc[max(0, i - window + 1): i + 1]
        ab  = int(w["ab"].sum())
        h   = int(w["h"].sum())
        bb  = int(w["bb"].sum())
        hbp = int(w["hbp"].sum())
        sf  = int(w["sac_fly"].sum())
        tb  = int(
            w["h"].sum() + w["doubles"].sum()
            + 2 * w["triples"].sum() + 3 * w["hr"].sum()
        )
        avg  = h / ab if ab > 0 else 0.0
        obpd = ab + bb + hbp + sf
        obp  = (h + bb + hbp) / obpd if obpd > 0 else 0.0
        slg  = tb / ab if ab > 0 else 0.0
        rows.append({
            "game_date": player.iloc[i]["game_date"],
            "avg": round(avg, 3), "obp": round(obp, 3),
            "slg": round(slg, 3), "ops": round(obp + slg, 3),
        })

    return pd.DataFrame(rows).set_index("game_date")


def hot_cold_summary(
    batting: pd.DataFrame,
    windows: list[int] | None = None,
    min_pa_season: int = 50,
) -> pd.DataFrame:
    """
    For each qualified player: season OPS, last-7-game OPS, last-15-game OPS, delta, label.
    label = HOT (delta7 >= +0.100), COLD (delta7 <= -0.100), or blank.
    """
    if windows is None:
        windows = [7, 15]

    season = player_season_totals(batting)
    if season.empty:
        return pd.DataFrame()

    qualified = season[season["pa"] >= min_pa_season]
    rows = []

    for _, srow in qualified.iterrows():
        pid   = srow["player_id"]
        entry = {"player_id": pid, "player_name": srow["player_name"], "season_ops": srow["ops"]}

        for w in windows:
            rs = rolling_slash(batting, pid, w)
            entry[f"last_{w}_ops"] = rs["ops"].iloc[-1] if not rs.empty else srow["ops"]

        delta = round(entry[f"last_{windows[0]}_ops"] - srow["ops"], 3)
        entry["delta"] = delta
        entry["label"] = "HOT" if delta >= 0.100 else ("COLD" if delta <= -0.100 else "")
        rows.append(entry)

    return (
        pd.DataFrame(rows)
        .sort_values("delta", ascending=False)
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Lineup slot production
# ---------------------------------------------------------------------------

def lineup_slot_production(batting: pd.DataFrame) -> pd.DataFrame:
    """Aggregate OPS, HR, RBI, R, BB%, K% by batting order slot (1–9)."""
    if batting.empty:
        return pd.DataFrame()

    slots = batting[batting["batting_order"].between(1, 9)].copy()
    agg   = slots.groupby("batting_order").agg(
        pa      =("pa",      "sum"), ab     =("ab",      "sum"),
        h       =("h",       "sum"), doubles=("doubles", "sum"),
        triples =("triples", "sum"), hr     =("hr",      "sum"),
        rbi     =("rbi",     "sum"), r      =("r",       "sum"),
        bb      =("bb",      "sum"), hbp    =("hbp",     "sum"),
        sac_fly =("sac_fly", "sum"), so     =("so",      "sum"),
    ).reset_index()

    agg["avg"]    = (agg["h"] / agg["ab"]).where(agg["ab"] > 0, 0.0).round(3)
    obp_d         = agg["ab"] + agg["bb"] + agg["hbp"] + agg["sac_fly"]
    agg["obp"]    = ((agg["h"] + agg["bb"] + agg["hbp"]) / obp_d).where(obp_d > 0, 0.0).round(3)
    tb            = agg["h"] + agg["doubles"] + 2 * agg["triples"] + 3 * agg["hr"]
    agg["slg"]    = (tb / agg["ab"]).where(agg["ab"] > 0, 0.0).round(3)
    agg["ops"]    = (agg["obp"] + agg["slg"]).round(3)
    agg["bb_pct"] = (agg["bb"] / agg["pa"] * 100).where(agg["pa"] > 0, 0.0).round(1)
    agg["k_pct"]  = (agg["so"] / agg["pa"] * 100).where(agg["pa"] > 0, 0.0).round(1)
    return agg


# ---------------------------------------------------------------------------
# Career context
# ---------------------------------------------------------------------------

def fetch_career_context(
    player_ids: list[int],
    season: int,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    For each player: career AVG/OBP/SLG/OPS + current season vs career delta.
    Uses MLB Stats API career stats endpoint.  Cached per season.

    Returns: player_id, career_avg, career_obp, career_slg, career_ops,
             career_hr, career_g, season_vs_career_ops
    """
    from client.mlb_client import MLBClient
    from config import CACHE_DIR

    cache_path = (cache_dir or CACHE_DIR) / f"career_{season}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    client = MLBClient()
    rows: list[dict] = []

    for pid in player_ids:
        try:
            data = client._get(
                f"/people/{pid}/stats",
                {"stats": "career", "group": "hitting", "sportId": 1},
            )
        except Exception as e:
            log.warning("Career fetch failed for player %d: %s", pid, e)
            continue

        splits = data.get("stats", [{}])[0].get("splits", [])
        if not splits:
            continue
        s = splits[0].get("stat", {})
        rows.append({
            "player_id":  pid,
            "career_g":   int(s.get("gamesPlayed", 0)),
            "career_avg": float(s.get("avg", 0) or 0),
            "career_obp": float(s.get("obp", 0) or 0),
            "career_slg": float(s.get("slg", 0) or 0),
            "career_ops": float(s.get("ops", 0) or 0),
            "career_hr":  int(s.get("homeRuns", 0)),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_parquet(cache_path, index=False)
    return df


def career_context_table(batting: pd.DataFrame, season: int) -> pd.DataFrame:
    """
    Merge season totals with career stats to show each player's
    current season OPS delta vs. career OPS.
    """
    season_totals = player_season_totals(batting)
    player_ids    = season_totals["player_id"].dropna().astype(int).tolist()
    career        = fetch_career_context(player_ids, season)

    if career.empty:
        return season_totals

    merged = season_totals.merge(career, on="player_id", how="left")
    merged["ops_vs_career"] = (merged["ops"] - merged["career_ops"]).round(3)
    return merged


# ---------------------------------------------------------------------------
# Rich terminal output
# ---------------------------------------------------------------------------

def print_offense(
    console: Console,
    batting: pd.DataFrame,
    games: pd.DataFrame,
    roster: pd.DataFrame,
    season: int | None = None,
    team_abbr: str | None = None,
    show_statcast: bool = True,
    show_platoon: bool = True,
    show_career: bool = True,
) -> None:
    """
    Print full offensive dashboard:
      1. Team summary row
      2. Batting leaderboard (with BABIP + optional Statcast)
      3. Hot / cold tracker
      4. Lineup slot production
      5. Platoon splits
      6. Career context (OPS vs. career)
    """
    off = team_offense_summary(batting, games)
    if not off:
        console.print("[yellow]No batting data.[/yellow]")
        return

    # 1. Team summary
    team_t = Table(title="Team Offense — Season", box=box.SIMPLE_HEAVY, show_lines=False)
    for col in ("AVG", "OBP", "SLG", "OPS", "BABIP", "R/G", "HR", "SB", "BB%", "K%"):
        team_t.add_column(col, style="white", justify="right")
    team_t.add_row(
        f"{off['avg']:.3f}", f"{off['obp']:.3f}",
        f"{off['slg']:.3f}", f"[bold]{off['ops']:.3f}[/bold]",
        f"{off['babip']:.3f}",
        f"{off['r_per_g']:.2f}", str(off["hr"]), str(off["sb"]),
        f"{off['bb_pct']:.1f}%", f"{off['k_pct']:.1f}%",
    )
    console.print(team_t)

    # 2. Batting leaderboard
    lb = batting_leaderboard(batting, min_pa=50)
    if show_statcast and season and team_abbr:
        lb = enrich_with_statcast(lb, season, team_abbr)

    has_statcast = "exit_velocity_avg" in lb.columns and lb["exit_velocity_avg"].notna().any()

    lb_t = Table(
        title="Batting Leaderboard  (min 50 PA · sorted by OPS)",
        box=box.SIMPLE, show_lines=False,
    )
    lb_t.add_column("Player",  style="cyan",       min_width=20)
    lb_t.add_column("G",       style="dim",         justify="right")
    lb_t.add_column("PA",      style="dim",         justify="right")
    lb_t.add_column("AVG",     style="white",       justify="right")
    lb_t.add_column("OBP",     style="white",       justify="right")
    lb_t.add_column("SLG",     style="white",       justify="right")
    lb_t.add_column("OPS",     style="bold white",  justify="right")
    lb_t.add_column("BABIP",   style="dim",         justify="right")
    lb_t.add_column("HR",      style="yellow",      justify="right")
    lb_t.add_column("RBI",     style="yellow",      justify="right")
    lb_t.add_column("SB",      style="green",       justify="right")
    lb_t.add_column("BB%",     style="dim",         justify="right")
    lb_t.add_column("K%",      style="dim",         justify="right")
    if has_statcast:
        lb_t.add_column("EV",  style="cyan",        justify="right")
        lb_t.add_column("Brl%",style="cyan",        justify="right")
        lb_t.add_column("xBA", style="cyan",        justify="right")
        lb_t.add_column("xwOBA",style="cyan",       justify="right")

    for _, row in lb.iterrows():
        cells = [
            row["player_name"], str(row["g"]), str(row["pa"]),
            f"{row['avg']:.3f}", f"{row['obp']:.3f}",
            f"{row['slg']:.3f}", f"{row['ops']:.3f}",
            f"{row['babip']:.3f}",
            str(int(row["hr"])), str(int(row["rbi"])), str(int(row["sb"])),
            f"{row['bb_pct']:.1f}%", f"{row['k_pct']:.1f}%",
        ]
        if has_statcast:
            ev   = row.get("exit_velocity_avg")
            brl  = row.get("barrel_batted_rate")
            xba  = row.get("xba")
            xwoba= row.get("xwoba")
            cells += [
                f"{ev:.1f}" if pd.notna(ev) else "-",
                f"{brl:.1f}" if pd.notna(brl) else "-",
                f"{xba:.3f}" if pd.notna(xba) else "-",
                f"{xwoba:.3f}" if pd.notna(xwoba) else "-",
            ]
        lb_t.add_row(*cells)
    console.print(lb_t)

    # 3. Hot / cold
    hc = hot_cold_summary(batting, windows=[7, 15], min_pa_season=50)
    if not hc.empty:
        hc_t = Table(title="Hot / Cold Tracker", box=box.SIMPLE, show_lines=False)
        hc_t.add_column("Player",    style="cyan",  min_width=20)
        hc_t.add_column("Ssn OPS",   style="white", justify="right")
        hc_t.add_column("L7 OPS",    style="white", justify="right")
        hc_t.add_column("L15 OPS",   style="white", justify="right")
        hc_t.add_column("Δ (7)",     style="bold",  justify="right")
        hc_t.add_column("",          style="bold",  justify="left")

        for _, row in hc.iterrows():
            delta = row["delta"]
            d_col  = "green" if delta >= 0.100 else ("red" if delta <= -0.100 else "white")
            d_str  = f"[{d_col}]{delta:+.3f}[/{d_col}]"
            label  = (
                "[bold green]🔥 HOT[/bold green]" if row["label"] == "HOT"
                else "[bold red]🧊 COLD[/bold red]" if row["label"] == "COLD"
                else ""
            )
            hc_t.add_row(
                row["player_name"],
                f"{row['season_ops']:.3f}",
                f"{row['last_7_ops']:.3f}",
                f"{row['last_15_ops']:.3f}",
                d_str, label,
            )
        console.print(hc_t)

    # 4. Lineup slot production
    slots = lineup_slot_production(batting)
    if not slots.empty:
        slot_t = Table(title="Production by Lineup Slot", box=box.SIMPLE, show_lines=False)
        for col, sty, just in [
            ("Slot","cyan","right"),("PA","dim","right"),
            ("AVG","white","right"),("OBP","white","right"),
            ("SLG","white","right"),("OPS","bold white","right"),
            ("HR","yellow","right"),("RBI","yellow","right"),
            ("BB%","dim","right"),("K%","dim","right"),
        ]:
            slot_t.add_column(col, style=sty, justify=just)
        for _, row in slots.iterrows():
            slot_t.add_row(
                str(int(row["batting_order"])), str(int(row["pa"])),
                f"{row['avg']:.3f}", f"{row['obp']:.3f}",
                f"{row['slg']:.3f}", f"{row['ops']:.3f}",
                str(int(row["hr"])), str(int(row["rbi"])),
                f"{row['bb_pct']:.1f}%", f"{row['k_pct']:.1f}%",
            )
        console.print(slot_t)

    # 5. Platoon splits
    if show_platoon and season:
        plat = platoon_table(batting, season)
        if not plat.empty:
            pt = Table(title="Platoon Splits", box=box.SIMPLE, show_lines=False)
            pt.add_column("Player",  style="cyan",  min_width=20)
            pt.add_column("Split",   style="dim",   min_width=8)
            pt.add_column("AB",      style="dim",   justify="right")
            pt.add_column("AVG",     style="white", justify="right")
            pt.add_column("OBP",     style="white", justify="right")
            pt.add_column("SLG",     style="white", justify="right")
            pt.add_column("OPS",     style="bold white", justify="right")
            pt.add_column("HR",      style="yellow",justify="right")
            pt.add_column("BB",      style="dim",   justify="right")
            pt.add_column("SO",      style="dim",   justify="right")
            for _, row in plat.iterrows():
                if int(row.get("ab", 0)) < 10:
                    continue
                pt.add_row(
                    str(row.get("player_name", "")),
                    str(row["hand"]),
                    str(int(row.get("ab", 0))),
                    f"{float(row.get('avg', 0)):.3f}",
                    f"{float(row.get('obp', 0)):.3f}",
                    f"{float(row.get('slg', 0)):.3f}",
                    f"{float(row.get('ops', 0)):.3f}",
                    str(int(row.get("hr", 0))),
                    str(int(row.get("bb", 0))),
                    str(int(row.get("so", 0))),
                )
            console.print(pt)

    # 6. Career context
    if show_career and season:
        ctx = career_context_table(batting, season)
        if "career_ops" in ctx.columns and ctx["career_ops"].notna().any():
            cc_t = Table(title="Season vs. Career OPS", box=box.SIMPLE, show_lines=False)
            cc_t.add_column("Player",       style="cyan",  min_width=20)
            cc_t.add_column("Career G",     style="dim",   justify="right")
            cc_t.add_column("Career OPS",   style="white", justify="right")
            cc_t.add_column("Season OPS",   style="white", justify="right")
            cc_t.add_column("Δ vs Career",  style="bold",  justify="right")
            cc_t.add_column("Career HR",    style="yellow",justify="right")

            ctx_sorted = ctx[ctx["career_ops"].notna()].sort_values("ops_vs_career", ascending=False)
            for _, row in ctx_sorted.head(15).iterrows():
                delta  = row.get("ops_vs_career", 0)
                d_col  = "green" if delta > 0 else "red"
                cc_t.add_row(
                    row["player_name"],
                    str(int(row.get("career_g", 0))),
                    f"{float(row.get('career_ops', 0)):.3f}",
                    f"{row['ops']:.3f}",
                    f"[{d_col}]{delta:+.3f}[/{d_col}]",
                    str(int(row.get("career_hr", 0))),
                )
            console.print(cc_t)
