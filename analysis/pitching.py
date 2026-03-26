"""
Pitching analytics — rotation and bullpen.

Day 2: team-level splits, starter/bullpen totals, rotation + bullpen tables.
Day 4: FIP, pitch efficiency, rest tracker, bullpen role classification,
        overuse alerts, quality-start correlation, ace correlation,
        pitcher decision streaks.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _era(er: int, ip_outs: int) -> float:
    return round(er * 27 / ip_outs, 2) if ip_outs > 0 else 0.0


def _whip(h: int, bb: int, ip_outs: int) -> float:
    ip = ip_outs / 3
    return round((h + bb) / ip, 3) if ip > 0 else 0.0


def _k9(so: int, ip_outs: int) -> float:
    ip = ip_outs / 3
    return round(so * 9 / ip, 2) if ip > 0 else 0.0


def _bb9(bb: int, ip_outs: int) -> float:
    ip = ip_outs / 3
    return round(bb * 9 / ip, 2) if ip > 0 else 0.0


def _ip_display(ip_outs: int) -> str:
    whole = ip_outs // 3
    frac  = ip_outs % 3
    return f"{whole}.{frac}" if frac else str(whole)


# ---------------------------------------------------------------------------
# FIP  (Fielding Independent Pitching)
# ---------------------------------------------------------------------------

def compute_fip(
    er: int, hr: int, bb: int, hbp: int, so: int, ip_outs: int,
    league_constant: float = 3.20,
) -> float:
    """
    FIP = ((13*HR + 3*(BB+HBP) - 2*K) / IP) + constant
    league_constant ≈ league ERA for the season (~3.1–3.3 in modern game).
    """
    ip = ip_outs / 3
    return round((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + league_constant, 2) if ip > 0 else 0.0


# ---------------------------------------------------------------------------
# Starter season totals  (Day 2, enhanced Day 4)
# ---------------------------------------------------------------------------

def starter_season_totals(pitching: pd.DataFrame) -> pd.DataFrame:
    """
    Season totals per starting pitcher.  Includes FIP and P/IP efficiency.

    Columns: player_id, player_name, gs, w, l, ip_str, era, fip, whip,
             k_per_9, bb_per_9, hr_per_9, p_per_ip, avg_game_score,
             quality_start_pct, qs
    """
    if pitching.empty:
        return pd.DataFrame()

    starters = pitching[pitching["is_starter"] == True].copy()
    if starters.empty:
        return pd.DataFrame()

    agg = starters.groupby("player_id").agg(
        player_name    =("player_name", "first"),
        gs             =("game_pk",     "count"),
        w              =("win",         "sum"),
        l              =("loss",        "sum"),
        ip_outs        =("ip_outs",     "sum"),
        h              =("h",           "sum"),
        er             =("er",          "sum"),
        bb             =("bb",          "sum"),
        so             =("so",          "sum"),
        hr             =("hr",          "sum"),
        hbp            =("hbp",         "sum"),
        pitches        =("pitches",     "sum"),
        game_score_sum =("game_score",  "sum"),
    ).reset_index()

    # Quality starts: ip_outs >= 18 (6 IP) AND er <= 3
    qs_counts = (
        starters[(starters["ip_outs"] >= 18) & (starters["er"] <= 3)]
        .groupby("player_id")
        .size()
        .reset_index(name="qs")
    )
    agg = agg.merge(qs_counts, on="player_id", how="left")
    agg["qs"] = agg["qs"].fillna(0).astype(int)

    agg["era"]               = agg.apply(lambda r: _era(r["er"], r["ip_outs"]), axis=1)
    agg["fip"]               = agg.apply(
        lambda r: compute_fip(r["er"], r["hr"], r["bb"], r["hbp"], r["so"], r["ip_outs"]), axis=1
    )
    agg["whip"]              = agg.apply(lambda r: _whip(r["h"], r["bb"], r["ip_outs"]), axis=1)
    agg["k_per_9"]           = agg.apply(lambda r: _k9(r["so"], r["ip_outs"]), axis=1)
    agg["bb_per_9"]          = agg.apply(lambda r: _bb9(r["bb"], r["ip_outs"]), axis=1)
    agg["hr_per_9"]          = agg.apply(
        lambda r: round(r["hr"] * 27 / r["ip_outs"], 2) if r["ip_outs"] > 0 else 0.0, axis=1
    )
    agg["avg_game_score"]    = (agg["game_score_sum"] / agg["gs"]).round(1)
    agg["quality_start_pct"] = (agg["qs"] / agg["gs"] * 100).round(1)
    agg["ip_str"]            = agg["ip_outs"].apply(_ip_display)
    # Pitch efficiency: pitches per inning
    agg["p_per_ip"]          = (
        (agg["pitches"] / (agg["ip_outs"] / 3))
        .where(agg["ip_outs"] > 0, 0.0)
        .round(1)
    )

    return agg.sort_values("era").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Rotation rest tracker  (Day 4)
# ---------------------------------------------------------------------------

def rotation_rest_tracker(pitching: pd.DataFrame) -> pd.DataFrame:
    """
    For each starter: last start date, days of rest (from today), next projected start.
    Uses a 5-man rotation model (one start every ~5 days).

    Returns: player_id, player_name, last_start, days_rest, next_projected_start
    """
    starters = pitching[pitching["is_starter"] == True].copy()
    if starters.empty:
        return pd.DataFrame()

    last_starts = (
        starters.groupby("player_id")
        .agg(
            player_name =("player_name", "first"),
            last_start  =("game_date",   "max"),
            gs          =("game_pk",     "count"),
        )
        .reset_index()
    )

    today = date.today()
    last_starts["last_start_date"] = pd.to_datetime(last_starts["last_start"]).dt.date
    last_starts["days_rest"] = last_starts["last_start_date"].apply(
        lambda d: (today - d).days
    )
    last_starts["next_projected"] = last_starts["last_start_date"].apply(
        lambda d: str(d + pd.Timedelta(days=5).to_pytimedelta())
    )

    return (
        last_starts[["player_id", "player_name", "last_start", "days_rest", "next_projected", "gs"]]
        .sort_values("days_rest")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Starter rolling ERA trend  (Day 4)
# ---------------------------------------------------------------------------

def starter_rolling_era(pitching: pd.DataFrame, pitcher_id: int, window: int = 5) -> pd.Series:
    """Rolling ERA over last `window` starts for a specific starter."""
    starts = (
        pitching[(pitching["player_id"] == pitcher_id) & (pitching["is_starter"] == True)]
        .sort_values("game_date")
        .reset_index(drop=True)
    )
    if starts.empty:
        return pd.Series(dtype=float)

    eras = []
    for i in range(len(starts)):
        w = starts.iloc[max(0, i - window + 1): i + 1]
        eras.append(_era(int(w["er"].sum()), int(w["ip_outs"].sum())))

    return pd.Series(eras, index=starts["game_date"])


def all_starter_rolling_eras(pitching: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """
    Rolling ERA for every starter over the season.
    Returns long-format DataFrame: player_id, player_name, game_date, rolling_era.
    Useful for the rotation heatmap chart.
    """
    starters = pitching[pitching["is_starter"] == True]
    rows = []
    for pid, grp in starters.groupby("player_id"):
        name  = grp["player_name"].iloc[0]
        grp   = grp.sort_values("game_date").reset_index(drop=True)
        for i in range(len(grp)):
            w = grp.iloc[max(0, i - window + 1): i + 1]
            rows.append({
                "player_id":   pid,
                "player_name": name,
                "game_date":   grp.iloc[i]["game_date"],
                "start_num":   i + 1,
                "rolling_era": _era(int(w["er"].sum()), int(w["ip_outs"].sum())),
                "game_score":  int(grp.iloc[i]["game_score"]),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Quality-start & ace correlation  (Day 4)
# ---------------------------------------------------------------------------

def quality_start_correlation(pitching: pd.DataFrame, games: pd.DataFrame) -> dict:
    """
    Team W-L record in quality starts vs. non-quality starts.
    quality start = starter goes >= 6 IP with <= 3 ER.

    Returns: qs_w, qs_l, qs_win_pct, non_qs_w, non_qs_l, non_qs_win_pct
    """
    starters = pitching[pitching["is_starter"] == True].copy()
    if starters.empty or games.empty:
        return {}

    starters["is_qs"] = (starters["ip_outs"] >= 18) & (starters["er"] <= 3)
    merged = games[games["status"] == "Final"].merge(
        starters[["game_pk", "is_qs"]], on="game_pk", how="left"
    )
    merged["is_qs"] = merged["is_qs"].fillna(False)

    def wl(df):
        return int((df["result"] == "W").sum()), int((df["result"] == "L").sum())

    qs_w, qs_l       = wl(merged[merged["is_qs"] == True])
    non_qs_w, non_qs_l = wl(merged[merged["is_qs"] == False])

    return dict(
        qs_w=qs_w, qs_l=qs_l,
        qs_win_pct=round(qs_w / (qs_w + qs_l), 3) if (qs_w + qs_l) > 0 else 0.0,
        non_qs_w=non_qs_w, non_qs_l=non_qs_l,
        non_qs_win_pct=round(non_qs_w / (non_qs_w + non_qs_l), 3)
            if (non_qs_w + non_qs_l) > 0 else 0.0,
    )


def ace_correlation(pitching: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """
    Per-starter: team W-L in their starts and win%, ordered by win%.
    The "ace effect" = how much the team wins when each starter takes the mound.
    """
    starters = pitching[pitching["is_starter"] == True]
    if starters.empty or games.empty:
        return pd.DataFrame()

    finished = games[games["status"] == "Final"]
    rows = []
    for pid, grp in starters.groupby("player_id"):
        name    = grp["player_name"].iloc[0]
        game_pks = set(grp["game_pk"].tolist())
        team_gs  = finished[finished["game_pk"].isin(game_pks)]
        w   = int((team_gs["result"] == "W").sum())
        l   = int((team_gs["result"] == "L").sum())
        pct = round(w / (w + l), 3) if (w + l) > 0 else 0.0
        rows.append({"player_id": pid, "player_name": name, "gs": len(grp), "w": w, "l": l, "win_pct": pct})

    return pd.DataFrame(rows).sort_values("win_pct", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Pitcher decision streaks  (Day 4)
# ---------------------------------------------------------------------------

def pitcher_decision_streaks(pitching: pd.DataFrame) -> pd.DataFrame:
    """
    For starters: current W/L decision streak and season-best win streak.
    Only counts games where pitcher received a win or loss decision.
    """
    starters = pitching[pitching["is_starter"] == True].copy()
    if starters.empty:
        return pd.DataFrame()

    rows = []
    for pid, grp in starters.groupby("player_id"):
        name = grp["player_name"].iloc[0]
        grp  = grp.sort_values("game_date")

        # Build decision sequence: W / L / None
        decisions = []
        for _, r in grp.iterrows():
            if r["win"]:
                decisions.append("W")
            elif r["loss"]:
                decisions.append("L")

        if not decisions:
            continue

        # Current streak
        last      = decisions[-1]
        cur_streak = 0
        for d in reversed(decisions):
            if d == last:
                cur_streak += 1
            else:
                break

        # Longest win streak
        best_w = cur_w = 0
        for d in decisions:
            cur_w = (cur_w + 1) if d == "W" else 0
            best_w = max(best_w, cur_w)

        rows.append({
            "player_id":    pid,
            "player_name":  name,
            "gs":           len(grp),
            "streak_type":  last,
            "streak_len":   cur_streak,
            "best_w_streak":best_w,
            "w":            int(grp["win"].sum()),
            "l":            int(grp["loss"].sum()),
        })

    return (
        pd.DataFrame(rows)
        .sort_values(["streak_type", "streak_len"], ascending=[True, False])
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Bullpen season totals  (Day 2, enhanced Day 4)
# ---------------------------------------------------------------------------

def bullpen_season_totals(pitching: pd.DataFrame) -> pd.DataFrame:
    """Season totals for all relievers with role classification."""
    if pitching.empty:
        return pd.DataFrame()

    relievers = pitching[pitching["is_starter"] == False].copy()
    if relievers.empty:
        return pd.DataFrame()

    agg = relievers.groupby("player_id").agg(
        player_name =("player_name", "first"),
        g           =("game_pk",     "count"),
        w           =("win",         "sum"),
        l           =("loss",        "sum"),
        sv          =("save",        "sum"),
        hld         =("hold",        "sum"),
        bs          =("blown_save",  "sum"),
        ip_outs     =("ip_outs",     "sum"),
        h           =("h",           "sum"),
        er          =("er",          "sum"),
        bb          =("bb",          "sum"),
        so          =("so",          "sum"),
        hr          =("hr",          "sum"),
        hbp         =("hbp",         "sum"),
        pitches     =("pitches",     "sum"),
    ).reset_index()

    agg["era"]      = agg.apply(lambda r: _era(r["er"], r["ip_outs"]), axis=1)
    agg["fip"]      = agg.apply(
        lambda r: compute_fip(r["er"], r["hr"], r["bb"], r["hbp"], r["so"], r["ip_outs"]), axis=1
    )
    agg["whip"]     = agg.apply(lambda r: _whip(r["h"], r["bb"], r["ip_outs"]), axis=1)
    agg["k_per_9"]  = agg.apply(lambda r: _k9(r["so"], r["ip_outs"]), axis=1)
    agg["bb_per_9"] = agg.apply(lambda r: _bb9(r["bb"], r["ip_outs"]), axis=1)
    agg["ip_str"]   = agg["ip_outs"].apply(_ip_display)
    agg["ip_per_g"] = (agg["ip_outs"] / 3 / agg["g"]).where(agg["g"] > 0, 0.0).round(2)
    agg["role"]     = agg.apply(_classify_role, axis=1)

    return agg.sort_values(["role", "era"]).reset_index(drop=True)


def _classify_role(row) -> str:
    """
    Heuristic role classification:
      Closer    — has saves
      Setup     — holds without many saves, avg IP close to 1
      Long      — high avg IP per appearance (>= 1.5 IP/G)
      Middle    — everything else
    """
    if row["sv"] > 0:
        return "Closer"
    if row["hld"] >= 5 and row["ip_per_g"] <= 1.3:
        return "Setup"
    if row["ip_per_g"] >= 1.5:
        return "Long"
    return "Middle"


# ---------------------------------------------------------------------------
# Bullpen by role  (Day 4)
# ---------------------------------------------------------------------------

def bullpen_role_splits(pitching: pd.DataFrame) -> pd.DataFrame:
    """
    ERA, WHIP, K/9, BB/9 aggregated by role (Closer/Setup/Middle/Long).
    """
    totals = bullpen_season_totals(pitching)
    if totals.empty:
        return pd.DataFrame()

    rows = []
    for role, grp in totals.groupby("role"):
        ip_outs = int(grp["ip_outs"].sum())
        rows.append({
            "role":     role,
            "pitchers": len(grp),
            "g":        int(grp["g"].sum()),
            "ip_str":   _ip_display(ip_outs),
            "era":      _era(int(grp["er"].sum()), ip_outs),
            "whip":     _whip(int(grp["h"].sum()), int(grp["bb"].sum()), ip_outs),
            "k_per_9":  _k9(int(grp["so"].sum()), ip_outs),
            "bb_per_9": _bb9(int(grp["bb"].sum()), ip_outs),
            "sv":       int(grp["sv"].sum()),
            "hld":      int(grp["hld"].sum()),
            "bs":       int(grp["bs"].sum()),
        })

    role_order = {"Closer": 0, "Setup": 1, "Middle": 2, "Long": 3}
    return (
        pd.DataFrame(rows)
        .assign(sort_key=lambda df: df["role"].map(role_order).fillna(9))
        .sort_values("sort_key")
        .drop(columns="sort_key")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Bullpen usage load & overuse alerts  (Day 4)
# ---------------------------------------------------------------------------

def bullpen_usage_load(pitching: pd.DataFrame, days: int = 3) -> pd.DataFrame:
    """Pitches thrown by each reliever in the last `days` days."""
    if pitching.empty:
        return pd.DataFrame()

    relievers = pitching[pitching["is_starter"] == False].copy()
    relievers["game_date"] = pd.to_datetime(relievers["game_date"])
    cutoff = relievers["game_date"].max() - pd.Timedelta(days=days - 1)
    recent = relievers[relievers["game_date"] >= cutoff]

    load = (
        recent.groupby("player_id")
        .agg(
            player_name =("player_name", "first"),
            appearances =("game_pk",     "count"),
            pitches     =("pitches",     "sum"),
            ip_outs     =("ip_outs",     "sum"),
        )
        .reset_index()
        .sort_values("pitches", ascending=False)
    )
    load["ip_str"]  = load["ip_outs"].apply(_ip_display)
    load["heavy"]   = load["appearances"] >= days
    return load


def bullpen_overuse_alerts(pitching: pd.DataFrame, consecutive_days: int = 3) -> pd.DataFrame:
    """
    Find relievers who appeared in `consecutive_days` or more consecutive days.
    Returns: player_id, player_name, streak_days, pitches_in_streak, dates
    """
    if pitching.empty:
        return pd.DataFrame()

    relievers = pitching[pitching["is_starter"] == False].copy()
    relievers["game_date"] = pd.to_datetime(relievers["game_date"])

    alerts = []
    for pid, grp in relievers.groupby("player_id"):
        name  = grp["player_name"].iloc[0]
        dates = sorted(grp["game_date"].dt.date.unique())
        if len(dates) < consecutive_days:
            continue

        # Detect consecutive-day streaks
        best_streak = []
        cur_streak  = [dates[0]]
        for i in range(1, len(dates)):
            if (dates[i] - dates[i - 1]).days == 1:
                cur_streak.append(dates[i])
            else:
                if len(cur_streak) > len(best_streak):
                    best_streak = cur_streak
                cur_streak = [dates[i]]
        if len(cur_streak) > len(best_streak):
            best_streak = cur_streak

        if len(best_streak) >= consecutive_days:
            streak_games = grp[grp["game_date"].dt.date.isin(best_streak)]
            alerts.append({
                "player_id":        pid,
                "player_name":      name,
                "streak_days":      len(best_streak),
                "pitches_in_streak":int(streak_games["pitches"].sum()),
                "streak_start":     str(best_streak[0]),
                "streak_end":       str(best_streak[-1]),
            })

    return pd.DataFrame(alerts).sort_values("streak_days", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Team pitching split  (Day 2, unchanged)
# ---------------------------------------------------------------------------

def team_pitching_split(pitching: pd.DataFrame) -> dict:
    """Team ERA/WHIP/K9/BB9 for starters and bullpen separately."""
    if pitching.empty:
        return {}

    def _agg(df):
        ip_outs = int(df["ip_outs"].sum())
        return dict(
            era    =_era(int(df["er"].sum()), ip_outs),
            whip   =_whip(int(df["h"].sum()), int(df["bb"].sum()), ip_outs),
            k_per_9=_k9(int(df["so"].sum()), ip_outs),
            bb_per_9=_bb9(int(df["bb"].sum()), ip_outs),
        )

    starters  = pitching[pitching["is_starter"] == True]
    relievers = pitching[pitching["is_starter"] == False]
    overall   = _agg(pitching)
    sp_stats  = _agg(starters)
    rp_stats  = _agg(relievers)

    total_gs = len(starters)
    qs       = len(starters[(starters["ip_outs"] >= 18) & (starters["er"] <= 3)])

    return dict(
        era=overall["era"], whip=overall["whip"],
        k_per_9=overall["k_per_9"], bb_per_9=overall["bb_per_9"],
        starter_era=sp_stats["era"], starter_whip=sp_stats["whip"],
        bullpen_era=rp_stats["era"], bullpen_whip=rp_stats["whip"],
        quality_start_pct=round(qs / total_gs * 100, 1) if total_gs > 0 else 0.0,
        saves=int(pitching["save"].sum()),
        blown_saves=int(pitching["blown_save"].sum()),
        holds=int(pitching["hold"].sum()),
    )


# ---------------------------------------------------------------------------
# Rich terminal output
# ---------------------------------------------------------------------------

def print_pitching(
    console: Console,
    pitching: pd.DataFrame,
    games: pd.DataFrame,
    roster: pd.DataFrame,
) -> None:
    """
    Full pitching dashboard:
      1. Team split summary
      2. Quality-start correlation
      3. Rotation table (ERA, FIP, WHIP, K/9, pitch efficiency, avg game score)
      4. Rotation rest tracker
      5. Ace / starter correlation (team W-L per starter)
      6. Pitcher decision streaks
      7. Bullpen by role summary
      8. Bullpen individual table (with role labels)
      9. Bullpen usage load (last 3 days)
     10. Overuse alerts
    """
    split = team_pitching_split(pitching)
    if not split:
        console.print("[yellow]No pitching data.[/yellow]")
        return

    # 1. Team split summary
    split_t = Table(title="Team Pitching — Season", box=box.SIMPLE_HEAVY, show_lines=False)
    for col in ("ERA", "WHIP", "K/9", "BB/9", "SP ERA", "RP ERA", "QS%", "SV", "HLD", "BS"):
        split_t.add_column(col, style="white", justify="right")
    split_t.add_row(
        f"{split['era']:.2f}", f"{split['whip']:.3f}",
        f"{split['k_per_9']:.2f}", f"{split['bb_per_9']:.2f}",
        f"[bold]{split['starter_era']:.2f}[/bold]",
        f"[bold]{split['bullpen_era']:.2f}[/bold]",
        f"{split['quality_start_pct']:.1f}%",
        str(split["saves"]), str(split["holds"]), str(split["blown_saves"]),
    )
    console.print(split_t)

    # 2. Quality-start correlation
    qs_corr = quality_start_correlation(pitching, games)
    if qs_corr:
        qs_t = Table(title="Quality Start Correlation", box=box.SIMPLE, show_lines=False)
        for col in ("Situation", "W", "L", "Win%"):
            qs_t.add_column(col, style="white", justify="right")
        qs_t.add_column("Situation", style="cyan", justify="left", min_width=16)
        qs_t.add_row(
            "Quality Start",
            str(qs_corr["qs_w"]), str(qs_corr["qs_l"]),
            f"[green]{qs_corr['qs_win_pct']:.3f}[/green]",
        )
        qs_t.add_row(
            "Non-QS",
            str(qs_corr["non_qs_w"]), str(qs_corr["non_qs_l"]),
            f"[red]{qs_corr['non_qs_win_pct']:.3f}[/red]",
        )
        # Rebuild properly (rich table column dupe workaround)
        qs_t2 = Table(title="Quality Start Correlation", box=box.SIMPLE, show_lines=False)
        qs_t2.add_column("Situation", style="cyan", min_width=16)
        qs_t2.add_column("W",    style="green",  justify="right")
        qs_t2.add_column("L",    style="red",    justify="right")
        qs_t2.add_column("Win%", style="bold white", justify="right")
        qs_t2.add_row("Quality Start",
            str(qs_corr["qs_w"]), str(qs_corr["qs_l"]),
            f"[bold green]{qs_corr['qs_win_pct']:.3f}[/bold green]")
        qs_t2.add_row("Non-Quality Start",
            str(qs_corr["non_qs_w"]), str(qs_corr["non_qs_l"]),
            f"[bold red]{qs_corr['non_qs_win_pct']:.3f}[/bold red]")
        console.print(qs_t2)

    # 3. Rotation table
    starters = starter_season_totals(pitching)
    if not starters.empty:
        sp_t = Table(title="Rotation", box=box.SIMPLE, show_lines=False)
        for col, sty in [
            ("Pitcher","cyan"),("GS","dim"),("W-L","white"),("IP","dim"),
            ("ERA","bold white"),("FIP","white"),("WHIP","white"),
            ("K/9","green"),("BB/9","yellow"),("HR/9","red"),
            ("P/IP","dim"),("GmSc","dim"),("QS%","dim"),
        ]:
            sp_t.add_column(col, style=sty, justify="right" if col != "Pitcher" else "left")
        for _, row in starters.iterrows():
            era_c = "green" if row["era"] < 3.50 else ("yellow" if row["era"] < 4.50 else "red")
            fip_c = "green" if row["fip"] < 3.50 else ("yellow" if row["fip"] < 4.50 else "red")
            sp_t.add_row(
                row["player_name"], str(row["gs"]),
                f"{int(row['w'])}-{int(row['l'])}", row["ip_str"],
                f"[{era_c}]{row['era']:.2f}[/{era_c}]",
                f"[{fip_c}]{row['fip']:.2f}[/{fip_c}]",
                f"{row['whip']:.3f}",
                f"{row['k_per_9']:.2f}", f"{row['bb_per_9']:.2f}",
                f"{row['hr_per_9']:.2f}", f"{row['p_per_ip']:.1f}",
                f"{row['avg_game_score']:.0f}", f"{row['quality_start_pct']:.0f}%",
            )
        console.print(sp_t)

    # 4. Rotation rest tracker
    rest = rotation_rest_tracker(pitching)
    if not rest.empty:
        rest_t = Table(title="Rotation Rest Tracker", box=box.SIMPLE, show_lines=False)
        rest_t.add_column("Pitcher",         style="cyan",  min_width=20)
        rest_t.add_column("Last Start",      style="dim",   justify="right")
        rest_t.add_column("Days Rest",       style="white", justify="right")
        rest_t.add_column("Next Projected",  style="green", justify="right")
        for _, row in rest.iterrows():
            days  = int(row["days_rest"])
            d_col = "yellow" if days < 4 else ("green" if days <= 5 else "red")
            rest_t.add_row(
                row["player_name"],
                str(row["last_start"]),
                f"[{d_col}]{days}[/{d_col}]",
                str(row["next_projected"]),
            )
        console.print(rest_t)

    # 5. Ace / starter correlation
    ace = ace_correlation(pitching, games)
    if not ace.empty:
        ace_t = Table(title="Team W-L by Starter", box=box.SIMPLE, show_lines=False)
        ace_t.add_column("Starter",  style="cyan",       min_width=20)
        ace_t.add_column("GS",       style="dim",         justify="right")
        ace_t.add_column("W",        style="green",       justify="right")
        ace_t.add_column("L",        style="red",         justify="right")
        ace_t.add_column("Win%",     style="bold white",  justify="right")
        for _, row in ace.iterrows():
            pct_c = "green" if row["win_pct"] >= 0.600 else ("yellow" if row["win_pct"] >= 0.500 else "red")
            ace_t.add_row(
                row["player_name"], str(row["gs"]),
                str(row["w"]), str(row["l"]),
                f"[{pct_c}]{row['win_pct']:.3f}[/{pct_c}]",
            )
        console.print(ace_t)

    # 6. Pitcher decision streaks
    streaks = pitcher_decision_streaks(pitching)
    if not streaks.empty:
        str_t = Table(title="Pitcher Decision Streaks", box=box.SIMPLE, show_lines=False)
        str_t.add_column("Pitcher",      style="cyan",  min_width=20)
        str_t.add_column("W-L",          style="white", justify="right")
        str_t.add_column("Streak",       style="bold",  justify="right")
        str_t.add_column("Best W Streak",style="green", justify="right")
        for _, row in streaks.iterrows():
            s_col = "green" if row["streak_type"] == "W" else "red"
            str_t.add_row(
                row["player_name"],
                f"{row['w']}-{row['l']}",
                f"[{s_col}]{row['streak_type']}{row['streak_len']}[/{s_col}]",
                str(row["best_w_streak"]),
            )
        console.print(str_t)

    # 7. Bullpen by role
    role_splits = bullpen_role_splits(pitching)
    if not role_splits.empty:
        role_t = Table(title="Bullpen by Role", box=box.SIMPLE, show_lines=False)
        for col, sty in [
            ("Role","cyan"),("Arms","dim"),("G","dim"),("IP","dim"),
            ("ERA","bold white"),("WHIP","white"),("K/9","green"),("BB/9","yellow"),
            ("SV","cyan"),("HLD","cyan"),("BS","red"),
        ]:
            role_t.add_column(col, style=sty, justify="right" if col != "Role" else "left")
        for _, row in role_splits.iterrows():
            era_c = "green" if row["era"] < 3.50 else ("yellow" if row["era"] < 4.50 else "red")
            role_t.add_row(
                row["role"], str(row["pitchers"]), str(row["g"]), row["ip_str"],
                f"[{era_c}]{row['era']:.2f}[/{era_c}]",
                f"{row['whip']:.3f}", f"{row['k_per_9']:.2f}", f"{row['bb_per_9']:.2f}",
                str(row["sv"]), str(row["hld"]), str(row["bs"]),
            )
        console.print(role_t)

    # 8. Bullpen individual table
    bullpen = bullpen_season_totals(pitching)
    if not bullpen.empty:
        rp_t = Table(title="Bullpen Individual", box=box.SIMPLE, show_lines=False)
        for col, sty in [
            ("Pitcher","cyan"),("Role","dim"),("G","dim"),("IP","dim"),
            ("ERA","bold white"),("FIP","white"),("WHIP","white"),
            ("K/9","green"),("BB/9","yellow"),("SV","cyan"),("HLD","cyan"),("BS","red"),
        ]:
            rp_t.add_column(col, style=sty, justify="right" if col != "Pitcher" and col != "Role" else "left")
        for _, row in bullpen.iterrows():
            era_c = "green" if row["era"] < 3.50 else ("yellow" if row["era"] < 4.50 else "red")
            rp_t.add_row(
                row["player_name"], row["role"], str(row["g"]), row["ip_str"],
                f"[{era_c}]{row['era']:.2f}[/{era_c}]",
                f"{row['fip']:.2f}", f"{row['whip']:.3f}",
                f"{row['k_per_9']:.2f}", f"{row['bb_per_9']:.2f}",
                str(int(row["sv"])), str(int(row["hld"])), str(int(row["bs"])),
            )
        console.print(rp_t)

    # 9. Bullpen usage load (last 3 days)
    load = bullpen_usage_load(pitching, days=3)
    if not load.empty and load["appearances"].sum() > 0:
        load_t = Table(title="Bullpen Usage — Last 3 Days", box=box.SIMPLE, show_lines=False)
        load_t.add_column("Pitcher",    style="cyan",  min_width=20)
        load_t.add_column("App",        style="white", justify="right")
        load_t.add_column("IP",         style="dim",   justify="right")
        load_t.add_column("Pitches",    style="white", justify="right")
        load_t.add_column("Status",     style="bold",  justify="left")
        for _, row in load.iterrows():
            status = "[red]HEAVY[/red]" if row["heavy"] else "[green]OK[/green]"
            load_t.add_row(
                row["player_name"], str(int(row["appearances"])),
                row["ip_str"], str(int(row["pitches"])), status,
            )
        console.print(load_t)

    # 10. Overuse alerts
    alerts = bullpen_overuse_alerts(pitching, consecutive_days=3)
    if not alerts.empty:
        console.print("\n[bold red]⚠  Bullpen Overuse Alerts[/bold red]")
        for _, row in alerts.iterrows():
            console.print(
                f"  [cyan]{row['player_name']}[/cyan]  —  "
                f"[red]{row['streak_days']} consecutive days[/red]  "
                f"({row['streak_start']} → {row['streak_end']}, "
                f"{row['pitches_in_streak']} pitches)"
            )
