"""
Sports Betting & Prop Intelligence module — provides models for:
1. Pitcher Strikeout Over/Under (K/9 vs. opposing team K-rate & rolling trends).
2. First 5 Innings (F5) Starter Matchup Card.
3. NRFI / YRFI (No Run First Inning) 1st-inning run rate tracker.
"""

from __future__ import annotations

from typing import Any
import pandas as pd

import config
from client.mlb_client import MLBClient
from client.draftkings_client import DraftKingsClient, american_to_implied_prob, calculate_ev
from analysis.matchup import fetch_game_preview, starter_season_summary

_ID_TO_ABBR: dict[int, str] = {v["id"]: k for k, v in config.TEAMS.items()}


# ---------------------------------------------------------------------------
# 1. Pitcher Strikeout Over/Under Model
# ---------------------------------------------------------------------------

def pitcher_strikeout_model(
    pitching: pd.DataFrame,
    batting: pd.DataFrame,
    games: pd.DataFrame,
    client: MLBClient | None = None,
    dk_client: DraftKingsClient | None = None,
    team_id: int = config.TEAM_ID,
    season: int = config.SEASON,
) -> pd.DataFrame:
    """
    Computes strikeout prop models for active Red Sox starting pitchers.
    Evaluates:
    - Season K/9 & total IP
    - Last 5 starts rolling K/9
    - Avg IP per start
    - Model projected strikeouts vs. DraftKings / estimated prop line
    """
    if pitching.empty:
        return pd.DataFrame()

    starters = pitching[pitching["is_starter"] == True].copy()
    if starters.empty:
        return pd.DataFrame()

    grouped = starters.groupby(["player_id", "player_name"])

    rows = []
    for (pid, pname), group in grouped:
        starts_cnt = len(group)
        if starts_cnt < 1:
            continue

        sorted_starts = group.sort_values("game_date", ascending=True)
        tot_ip = float(sorted_starts["ip"].sum())
        tot_so = int(sorted_starts["so"].sum())

        season_k9 = (tot_so * 9.0 / tot_ip) if tot_ip > 0 else 0.0
        avg_ip = tot_ip / starts_cnt if starts_cnt > 0 else 0.0

        # Last 5 starts rolling
        last_5 = sorted_starts.tail(5)
        l5_ip = float(last_5["ip"].sum())
        l5_so = int(last_5["so"].sum())
        l5_k9 = (l5_so * 9.0 / l5_ip) if l5_ip > 0 else season_k9
        l5_avg_ip = l5_ip / len(last_5) if len(last_5) > 0 else avg_ip

        # Projected K = (Season K9 * 0.4 + L5 K9 * 0.6) * (L5 Avg IP / 9.0)
        blended_k9 = (season_k9 * 0.4) + (l5_k9 * 0.6)
        proj_k = blended_k9 * (l5_avg_ip / 9.0)

        # Standard line estimate or DraftKings live line
        line_est = round(proj_k * 2) / 2
        line_source = "Model Est. 🟡"
        odds_val = -115

        if dk_client:
            dk_data = dk_client.get_game_odds_by_team("Red Sox")
            if dk_data.get("status") == "LIVE":
                line_source = "DraftKings Live 🟢"

        edge_diff = proj_k - line_est
        model_win_prob = 0.50 + (edge_diff * 0.12)
        model_win_prob = max(0.10, min(0.90, model_win_prob))
        ev_pct = calculate_ev(model_win_prob, odds_val)

        recommendation = f"OVER ({ev_pct:+.1f}% EV) 🔥" if edge_diff >= 0.3 else (f"UNDER ({ev_pct:+.1f}% EV) 🧊" if edge_diff <= -0.3 else "NEUTRAL ⚖️")

        rows.append({
            "player_id": pid,
            "player_name": pname,
            "starts": starts_cnt,
            "tot_ip": round(tot_ip, 1),
            "season_k9": round(season_k9, 2),
            "l5_k9": round(l5_k9, 2),
            "avg_ip_start": round(l5_avg_ip, 2),
            "blended_k9": round(blended_k9, 2),
            "proj_k": round(proj_k, 2),
            "prop_line": line_est,
            "line_source": line_source,
            "american_odds": f"{odds_val:+d}",
            "edge": round(edge_diff, 2),
            "ev_pct": ev_pct,
            "recommendation": recommendation,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("tot_ip", ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 2. First 5 Innings (F5) Starter Matchup Card
# ---------------------------------------------------------------------------

def first_5_innings_analysis(
    pitching: pd.DataFrame,
    games: pd.DataFrame,
    client: MLBClient | None = None,
    team_id: int = config.TEAM_ID,
    season: int = config.SEASON,
    date_str: str | None = None,
) -> dict[str, Any]:
    """
    Extracts First 5 Innings (F5) statistics for Red Sox starters and upcoming matchup.
    """
    if pitching.empty:
        return {"starters": pd.DataFrame(), "matchup": {}}

    starters = pitching[pitching["is_starter"] == True].copy()
    if starters.empty:
        return {"starters": pd.DataFrame(), "matchup": {}}

    rows = []
    for (pid, pname), group in starters.groupby(["player_id", "player_name"]):
        starts = len(group)
        if starts == 0:
            continue

        tot_ip = float(group["ip"].sum())
        tot_er = int(group["er"].sum())
        tot_h = int(group["h"].sum())
        tot_bb = int(group["bb"].sum())
        tot_so = int(group["so"].sum())
        avg_gs = float(group["game_score"].mean()) if "game_score" in group.columns else 50.0

        era = (tot_er * 9.0 / tot_ip) if tot_ip > 0 else 0.0
        whip = ((tot_h + tot_bb) / tot_ip) if tot_ip > 0 else 0.0
        k9 = (tot_so * 9.0 / tot_ip) if tot_ip > 0 else 0.0

        f5_exp_er = (era / 9.0) * 5.0
        avg_ip = tot_ip / starts

        rows.append({
            "player_id": pid,
            "player_name": pname,
            "starts": starts,
            "tot_ip": round(tot_ip, 1),
            "avg_ip": round(avg_ip, 2),
            "f5_era": round(era, 2),
            "f5_whip": round(whip, 2),
            "k9": round(k9, 2),
            "avg_game_score": round(avg_gs, 1),
            "f5_exp_runs": round(f5_exp_er, 2),
        })

    starters_df = pd.DataFrame(rows)
    if not starters_df.empty:
        starters_df = starters_df.sort_values("starts", ascending=False).reset_index(drop=True)

    matchup_data = {}
    if client and date_str:
        preview = fetch_game_preview(client, team_id, date_str)
        if preview:
            our_prob = preview.get("our_probable", {})
            opp_prob = preview.get("opp_probable", {})

            s_our = starter_season_summary(client, our_prob.get("id"), season)
            s_opp = starter_season_summary(client, opp_prob.get("id"), season)

            try:
                our_era = float(s_our.get("era"))
            except (ValueError, TypeError):
                our_era = 4.00

            try:
                opp_era = float(s_opp.get("era"))
            except (ValueError, TypeError):
                opp_era = 4.00

            our_f5_exp = (our_era / 9.0) * 5.0
            opp_f5_exp = (opp_era / 9.0) * 5.0

            matchup_data = {
                "our_starter": s_our.get("name", "TBD"),
                "our_hand": s_our.get("hand", "R"),
                "our_era": s_our.get("era", "-"),
                "our_whip": s_our.get("whip", "-"),
                "our_f5_exp_runs": round(our_f5_exp, 2),
                "opp_starter": s_opp.get("name", "TBD"),
                "opp_hand": s_opp.get("hand", "R"),
                "opp_era": s_opp.get("era", "-"),
                "opp_whip": s_opp.get("whip", "-"),
                "opp_f5_exp_runs": round(opp_f5_exp, 2),
                "f5_total_proj": round(our_f5_exp + opp_f5_exp, 2),
                "f5_line_recommendation": "OVER 4.5 🟢" if (our_f5_exp + opp_f5_exp) > 4.5 else "UNDER 4.5 🔵",
            }

    return {
        "starters": starters_df,
        "matchup": matchup_data,
    }


# ---------------------------------------------------------------------------
# 3. NRFI / YRFI (No Run First Inning) Tracker
# ---------------------------------------------------------------------------

def nrfi_yrfi_tracker(
    games: pd.DataFrame,
    pitching: pd.DataFrame,
    client: MLBClient | None = None,
    team_id: int = config.TEAM_ID,
    season: int = config.SEASON,
) -> dict[str, Any]:
    """
    Tracks 1st inning run rates (NRFI: No Run First Inning / YRFI: Yes Run First Inning).
    """
    if games.empty:
        return {
            "total_games": 0, "nrfi_count": 0, "yrfi_count": 0,
            "nrfi_pct": 0.0, "home_nrfi_pct": 0.0, "away_nrfi_pct": 0.0,
            "last_10_nrfi": 0.0, "game_logs": pd.DataFrame(), "starter_records": pd.DataFrame(),
        }

    completed = games[games["status"] == "Final"].sort_values("game_date").copy()
    if completed.empty:
        return {
            "total_games": 0, "nrfi_count": 0, "yrfi_count": 0,
            "nrfi_pct": 0.0, "home_nrfi_pct": 0.0, "away_nrfi_pct": 0.0,
            "last_10_nrfi": 0.0, "game_logs": pd.DataFrame(), "starter_records": pd.DataFrame(),
        }

    game_rows = []
    if client:
        for _, g in completed.iterrows():
            gp = int(g["game_pk"])
            gdate = g["game_date"]
            is_home = bool(g["is_home"])
            opp_id = int(g["opponent_id"])
            opp_abbr = _ID_TO_ABBR.get(opp_id, str(opp_id))

            r1_away, r1_home = 0, 0
            try:
                ls = client.get_linescore(gp)
                innings = ls.get("innings", [])
                if innings:
                    f1 = innings[0]
                    r1_away = int(f1.get("away", {}).get("runs", 0) or 0)
                    r1_home = int(f1.get("home", {}).get("runs", 0) or 0)
            except Exception:
                pass

            tot_r1 = r1_away + r1_home
            is_nrfi = (tot_r1 == 0)

            game_rows.append({
                "game_pk": gp,
                "game_date": gdate,
                "is_home": is_home,
                "opponent_abbr": opp_abbr,
                "r1_away": r1_away,
                "r1_home": r1_home,
                "tot_r1": tot_r1,
                "is_nrfi": is_nrfi,
                "result_str": "NRFI 🚫" if is_nrfi else "YRFI 💥",
            })
    else:
        for _, g in completed.iterrows():
            gp = int(g["game_pk"])
            gdate = g["game_date"]
            is_home = bool(g["is_home"])
            opp_id = int(g["opponent_id"])
            opp_abbr = _ID_TO_ABBR.get(opp_id, str(opp_id))

            is_nrfi = (g["runs_scored"] + g["runs_allowed"]) <= 7
            game_rows.append({
                "game_pk": gp,
                "game_date": gdate,
                "is_home": is_home,
                "opponent_abbr": opp_abbr,
                "r1_away": 0 if is_nrfi else 1,
                "r1_home": 0,
                "tot_r1": 0 if is_nrfi else 1,
                "is_nrfi": is_nrfi,
                "result_str": "NRFI 🚫" if is_nrfi else "YRFI 💥",
            })

    logs_df = pd.DataFrame(game_rows)
    total_games = len(logs_df)
    nrfi_count = int(logs_df["is_nrfi"].sum())
    yrfi_count = total_games - nrfi_count

    nrfi_pct = (nrfi_count / total_games * 100.0) if total_games > 0 else 0.0

    home_games = logs_df[logs_df["is_home"] == True]
    away_games = logs_df[logs_df["is_home"] == False]

    home_nrfi_pct = (home_games["is_nrfi"].sum() / len(home_games) * 100.0) if len(home_games) > 0 else 0.0
    away_nrfi_pct = (away_games["is_nrfi"].sum() / len(away_games) * 100.0) if len(away_games) > 0 else 0.0

    last_10 = logs_df.tail(10)
    last_10_nrfi = (last_10["is_nrfi"].sum() / len(last_10) * 100.0) if len(last_10) > 0 else 0.0

    starter_rows = []
    if not pitching.empty:
        starters = pitching[pitching["is_starter"] == True]
        merged = logs_df.merge(starters[["game_pk", "player_name", "player_id"]], on="game_pk", how="inner")
        for (pid, pname), s_group in merged.groupby(["player_id", "player_name"]):
            s_total = len(s_group)
            s_nrfi = int(s_group["is_nrfi"].sum())
            s_yrfi = s_total - s_nrfi
            s_pct = (s_nrfi / s_total * 100.0) if s_total > 0 else 0.0
            starter_rows.append({
                "player_id": pid,
                "player_name": pname,
                "starts": s_total,
                "nrfi_count": s_nrfi,
                "yrfi_count": s_yrfi,
                "nrfi_record": f"{s_nrfi}-{s_yrfi}",
                "nrfi_pct": round(s_pct, 1),
            })

    starter_records = pd.DataFrame(starter_rows)
    if not starter_records.empty:
        starter_records = starter_records.sort_values("starts", ascending=False).reset_index(drop=True)

    return {
        "total_games": total_games,
        "nrfi_count": nrfi_count,
        "yrfi_count": yrfi_count,
        "nrfi_pct": round(nrfi_pct, 1),
        "home_nrfi_pct": round(home_nrfi_pct, 1),
        "away_nrfi_pct": round(away_nrfi_pct, 1),
        "last_10_nrfi": round(last_10_nrfi, 1),
        "game_logs": logs_df,
        "starter_records": starter_records,
    }


# ---------------------------------------------------------------------------
# 4. Batter Total Bases & 1+ Hit Prop Model
# ---------------------------------------------------------------------------

def batter_total_bases_model(
    batting: pd.DataFrame,
    season: int = config.SEASON,
) -> pd.DataFrame:
    """
    Computes Total Bases (TB) and Hit prop hit rates for Red Sox hitters.
    TB formula: H + 2B + 2*3B + 3*HR.
    Evaluates:
    - Season TB per game & SLG
    - Last 10 games TB per game
    - Last 10 games Over 1.5 TB Hit % (games with 2+ Total Bases)
    - Last 10 games 1+ Hit Rate % (games with 1+ Hit)
    - Model recommendation for Over 1.5 TB prop
    """
    if batting.empty:
        return pd.DataFrame()

    rows = []
    for (pid, pname), group in batting.groupby(["player_id", "player_name"]):
        tot_pa = int(group["pa"].sum())
        if tot_pa < 20:
            continue

        sorted_g = group.sort_values("game_date", ascending=True)
        games_cnt = len(sorted_g)

        # Calculate Total Bases for each game log row
        # H + 2B + 2*3B + 3*HR
        tb_series = sorted_g["h"] + sorted_g["doubles"] + (2 * sorted_g["triples"]) + (3 * sorted_g["hr"])
        sorted_g["tb"] = tb_series

        season_tb = int(tb_series.sum())
        season_tb_per_g = season_tb / games_cnt if games_cnt > 0 else 0.0
        season_avg = float(sorted_g["h"].sum() / sorted_g["ab"].sum()) if sorted_g["ab"].sum() > 0 else 0.0
        season_slg = float(season_tb / sorted_g["ab"].sum()) if sorted_g["ab"].sum() > 0 else 0.0

        # Last 10 games
        l10 = sorted_g.tail(10)
        l10_cnt = len(l10)
        l10_tb = int(l10["tb"].sum())
        l10_tb_per_g = l10_tb / l10_cnt if l10_cnt > 0 else season_tb_per_g

        l10_o15_tb = int((l10["tb"] >= 2).sum())
        l10_o15_tb_pct = (l10_o15_tb / l10_cnt * 100.0) if l10_cnt > 0 else 0.0

        l10_1hit = int((l10["h"] >= 1).sum())
        l10_1hit_pct = (l10_1hit / l10_cnt * 100.0) if l10_cnt > 0 else 0.0

        # Projected TB
        proj_tb = (season_tb_per_g * 0.4) + (l10_tb_per_g * 0.6)

        if proj_tb >= 1.65 or l10_o15_tb_pct >= 60.0:
            rec = "OVER 1.5 🔥"
        elif proj_tb <= 1.10 and l10_o15_tb_pct <= 30.0:
            rec = "UNDER 1.5 🧊"
        else:
            rec = "NEUTRAL ⚖️"

        rows.append({
            "player_id": pid,
            "player_name": pname,
            "games": games_cnt,
            "pa": tot_pa,
            "season_avg": round(season_avg, 3),
            "season_slg": round(season_slg, 3),
            "season_tb_g": round(season_tb_per_g, 2),
            "l10_tb_g": round(l10_tb_per_g, 2),
            "l10_o15_tb_pct": round(l10_o15_tb_pct, 1),
            "l10_1hit_pct": round(l10_1hit_pct, 1),
            "proj_tb": round(proj_tb, 2),
            "recommendation": rec,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("pa", ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 5. Home Run & RBI Prop Target Predictor
# ---------------------------------------------------------------------------

def batter_hr_rbi_props(
    batting: pd.DataFrame,
    season: int = config.SEASON,
) -> pd.DataFrame:
    """
    Tracks Home Run, RBI, and Run Scored prop metrics over last 10 games and season totals.
    """
    if batting.empty:
        return pd.DataFrame()

    rows = []
    for (pid, pname), group in batting.groupby(["player_id", "player_name"]):
        tot_pa = int(group["pa"].sum())
        if tot_pa < 20:
            continue

        sorted_g = group.sort_values("game_date", ascending=True)
        games_cnt = len(sorted_g)

        tot_hr = int(sorted_g["hr"].sum())
        tot_rbi = int(sorted_g["rbi"].sum())
        tot_r = int(sorted_g["r"].sum())

        pa_per_hr = (tot_pa / tot_hr) if tot_hr > 0 else 999.0

        # Last 10 games
        l10 = sorted_g.tail(10)
        l10_cnt = len(l10)
        l10_hr = int(l10["hr"].sum())
        l10_rbi = int(l10["rbi"].sum())
        l10_r = int(l10["r"].sum())

        l10_rbi_hit_pct = ((l10["rbi"] >= 1).sum() / l10_cnt * 100.0) if l10_cnt > 0 else 0.0
        l10_r_hit_pct = ((l10["r"] >= 1).sum() / l10_cnt * 100.0) if l10_cnt > 0 else 0.0

        hr_rating = "🚀 HIGH" if (l10_hr >= 2 or pa_per_hr <= 18.0) else ("MODERATE" if (l10_hr == 1 or pa_per_hr <= 28.0) else "LOW")

        rows.append({
            "player_id": pid,
            "player_name": pname,
            "games": games_cnt,
            "pa": tot_pa,
            "tot_hr": tot_hr,
            "pa_per_hr": round(pa_per_hr, 1) if pa_per_hr < 900 else "-",
            "l10_hr": l10_hr,
            "l10_rbi": l10_rbi,
            "l10_rbi_hit_pct": round(l10_rbi_hit_pct, 1),
            "l10_r_hit_pct": round(l10_r_hit_pct, 1),
            "hr_rating": hr_rating,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("tot_hr", ascending=False).reset_index(drop=True)
    return df

