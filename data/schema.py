"""
Canonical DataFrame schemas for the MLB tracker.

Each constant is a dict mapping column name → pandas dtype string.
Used by fetcher.py to enforce consistent shape when building / loading cache.

Tables
------
GAMES          one row per team-game  (schedule + result)
BATTING_LOG    one row per batter per game
PITCHING_LOG   one row per pitcher per game appearance
FIELDING_LOG   one row per fielder per game
ROSTER         current roster snapshot
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# GAMES  — team-level game results
# ---------------------------------------------------------------------------
GAMES_SCHEMA: dict[str, str] = {
    "game_pk":        "Int64",   # MLB primary key for the game
    "game_date":      "object",  # YYYY-MM-DD string; cast to datetime when needed
    "season":         "Int64",
    "game_num":       "Int64",   # sequential game number in season
    "home_team_id":   "Int64",
    "away_team_id":   "Int64",
    "team_id":        "Int64",   # the team we're tracking
    "opponent_id":    "Int64",
    "is_home":        "bool",
    "runs_scored":    "Int64",
    "runs_allowed":   "Int64",
    "result":         "object",  # "W", "L", or "T"
    "win_pitcher":    "object",
    "loss_pitcher":   "object",
    "save_pitcher":   "object",
    "innings":        "Int64",   # 9 for normal, >9 for extras
    "day_night":      "object",  # "D" or "N"
    "game_type":      "object",  # "R", "P", "S"
    "venue":          "object",
    "status":         "object",  # "Final", "Scheduled", "Postponed", etc.
}

# ---------------------------------------------------------------------------
# BATTING_LOG  — per-batter per-game hitting line
# ---------------------------------------------------------------------------
BATTING_LOG_SCHEMA: dict[str, str] = {
    "game_pk":        "Int64",
    "game_date":      "object",
    "season":         "Int64",
    "team_id":        "Int64",
    "player_id":      "Int64",
    "player_name":    "object",
    "batting_order":  "Int64",   # 1–9
    "position":       "object",  # primary position played
    # counting stats
    "ab":             "Int64",   # at-bats
    "pa":             "Int64",   # plate appearances
    "h":              "Int64",   # hits
    "doubles":        "Int64",
    "triples":        "Int64",
    "hr":             "Int64",
    "rbi":            "Int64",
    "r":              "Int64",   # runs scored
    "bb":             "Int64",   # walks
    "ibb":            "Int64",   # intentional walks
    "so":             "Int64",   # strikeouts
    "hbp":            "Int64",   # hit by pitch
    "sb":             "Int64",   # stolen bases
    "cs":             "Int64",   # caught stealing
    "sac_bunt":       "Int64",
    "sac_fly":        "Int64",
    "gidp":           "Int64",   # grounded into double play
    # derived
    "avg":            "Float64",
    "obp":            "Float64",
    "slg":            "Float64",
    "ops":            "Float64",
}

# ---------------------------------------------------------------------------
# PITCHING_LOG  — per-pitcher per-game appearance
# ---------------------------------------------------------------------------
PITCHING_LOG_SCHEMA: dict[str, str] = {
    "game_pk":        "Int64",
    "game_date":      "object",
    "season":         "Int64",
    "team_id":        "Int64",
    "player_id":      "Int64",
    "player_name":    "object",
    "is_starter":     "bool",
    # counting stats
    "ip":             "Float64",  # innings pitched (e.g., 6.1 = 6⅓)
    "ip_outs":        "Int64",    # total outs recorded (ip * 3)
    "h":              "Int64",
    "r":              "Int64",    # runs allowed
    "er":             "Int64",    # earned runs
    "bb":             "Int64",
    "so":             "Int64",
    "hr":             "Int64",
    "hbp":            "Int64",
    "bf":             "Int64",    # batters faced
    "pitches":        "Int64",
    "strikes":        "Int64",
    # derived
    "era":            "Float64",
    "whip":           "Float64",
    "k_per_9":        "Float64",
    "bb_per_9":       "Float64",
    # decision
    "win":            "bool",
    "loss":           "bool",
    "save":           "bool",
    "hold":           "bool",
    "blown_save":     "bool",
    "game_score":     "Int64",    # Bill James game score (starter quality)
}

# ---------------------------------------------------------------------------
# FIELDING_LOG  — per-fielder per-game
# ---------------------------------------------------------------------------
FIELDING_LOG_SCHEMA: dict[str, str] = {
    "game_pk":        "Int64",
    "game_date":      "object",
    "season":         "Int64",
    "team_id":        "Int64",
    "player_id":      "Int64",
    "player_name":    "object",
    "position":       "object",
    "innings":        "Float64",  # innings at this position
    "putouts":        "Int64",
    "assists":        "Int64",
    "errors":         "Int64",
    "chances":        "Int64",
    "fielding_pct":   "Float64",
    "dp":             "Int64",    # double plays participated in
    "passed_balls":   "Int64",    # catchers only
    "sb_against":     "Int64",    # catchers only
    "cs_against":     "Int64",    # catchers only
}

# ---------------------------------------------------------------------------
# ROSTER  — current active roster snapshot
# ---------------------------------------------------------------------------
ROSTER_SCHEMA: dict[str, str] = {
    "player_id":      "Int64",
    "player_name":    "object",
    "team_id":        "Int64",
    "season":         "Int64",
    "jersey_number":  "object",
    "position":       "object",   # abbreviated position (SP, RP, C, 1B, …)
    "position_group": "object",   # "SP", "RP", "C", "IF", "OF", "DH"
    "bats":           "object",   # "R", "L", "S"
    "throws":         "object",   # "R", "L"
    "age":            "Int64",
    "status":         "object",   # "Active", "10-Day IL", "60-Day IL", etc.
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def enforce_schema(df, schema: dict[str, str]):
    """
    Cast a DataFrame to the given schema, adding missing columns as NA
    and dropping extra columns.
    """
    import pandas as pd

    for col, dtype in schema.items():
        if col not in df.columns:
            df[col] = pd.NA
        try:
            df[col] = df[col].astype(dtype)
        except (ValueError, TypeError):
            pass  # leave as-is if cast fails (will surface in analysis)

    return df[list(schema.keys())]
