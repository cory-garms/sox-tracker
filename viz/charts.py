"""
Individual Plotly chart functions — Day 5.

Each function accepts DataFrames from the analysis modules and returns
a plotly.graph_objects.Figure ready to display or export.

All charts use a consistent dark theme suited for web embedding.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import numpy as np

# ---------------------------------------------------------------------------
# Shared theme
# ---------------------------------------------------------------------------

_BG       = "#0e1117"
_PAPER_BG = "#161b22"
_GRID     = "#30363d"
_TEXT     = "#e6edf3"
_GREEN    = "#3fb950"
_RED      = "#f85149"
_YELLOW   = "#d29922"
_BLUE     = "#58a6ff"
_DIM      = "#8b949e"

_LAYOUT_BASE = dict(
    paper_bgcolor=_PAPER_BG,
    plot_bgcolor=_BG,
    font=dict(color=_TEXT, family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif"),
    xaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID),
    yaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID),
    margin=dict(l=40, r=20, t=65, b=70),
    legend=dict(
        orientation="h",
        yanchor="top",
        y=-0.22,
        xanchor="center",
        x=0.5,
        bgcolor="rgba(0,0,0,0)",
        bordercolor=_GRID,
    ),
)


def _apply_theme(fig: go.Figure, **extra) -> go.Figure:
    layout = {**_LAYOUT_BASE, **extra}
    fig.update_layout(**layout)
    fig.update_xaxes(gridcolor=_GRID, zerolinecolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, zerolinecolor=_GRID)
    return fig


# ---------------------------------------------------------------------------
# Season timeline  (cumulative W-L curve)
# ---------------------------------------------------------------------------

def season_timeline(games: pd.DataFrame, team_name: str) -> go.Figure:
    """
    Cumulative wins and losses over the season.
    Includes a .500 pace reference line.
    """
    f = games[games["status"] == "Final"].sort_values(["game_date", "game_pk"]).reset_index(drop=True)
    if f.empty:
        return go.Figure()

    date_counts = f["game_date"].value_counts()
    dup_dates = set(date_counts[date_counts > 1].index)
    labels = []
    seen: dict[str, int] = {}
    for _, r in f.iterrows():
        d = r["game_date"]
        if d in dup_dates:
            seen[d] = seen.get(d, 0) + 1
            labels.append(f"{d} G{seen[d]}")
        else:
            labels.append(d)
    f["game_label"] = labels

    f["cum_w"] = (f["result"] == "W").cumsum()
    f["cum_l"] = (f["result"] == "L").cumsum()
    f["game_n"] = range(1, len(f) + 1)
    f["pace_500"] = f["game_n"] / 2

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=f["game_n"], y=f["cum_w"],
        name="Wins", mode="lines",
        line=dict(color=_GREEN, width=2),
        text=f["game_label"],
        hovertemplate="Game %{x} (%{text})<br>Wins: %{y}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=f["game_n"], y=f["cum_l"],
        name="Losses", mode="lines",
        line=dict(color=_RED, width=2),
        text=f["game_label"],
        hovertemplate="Game %{x} (%{text})<br>Losses: %{y}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=f["game_n"], y=f["pace_500"],
        name=".500 Pace", mode="lines",
        line=dict(color=_DIM, width=1, dash="dot"),
    ))

    _apply_theme(fig,
        title=dict(text=f"{team_name} — Season Timeline", font=dict(size=16)),
        xaxis_title="Game Number",
        yaxis_title="Cumulative Total",
    )
    return fig


# ---------------------------------------------------------------------------
# Rolling win%
# ---------------------------------------------------------------------------

def rolling_win_pct_chart(
    games: pd.DataFrame,
    team_name: str,
    windows: list[int] | None = None,
) -> go.Figure:
    """Rolling win% for each window size, with a .500 reference line."""
    if windows is None:
        windows = [7, 15]

    f = games[games["status"] == "Final"].sort_values(["game_date", "game_pk"]).reset_index(drop=True)
    if f.empty:
        return go.Figure()

    date_counts = f["game_date"].value_counts()
    dup_dates = set(date_counts[date_counts > 1].index)
    labels = []
    seen: dict[str, int] = {}
    for _, r in f.iterrows():
        d = r["game_date"]
        if d in dup_dates:
            seen[d] = seen.get(d, 0) + 1
            labels.append(f"{d} G{seen[d]}")
        else:
            labels.append(d)
    f["game_label"] = labels

    f["win_flag"] = (f["result"] == "W").astype(int)
    colors = [_BLUE, _YELLOW, _GREEN, _RED]

    fig = go.Figure()
    for i, w in enumerate(windows):
        roll = f["win_flag"].rolling(w).mean()
        fig.add_trace(go.Scatter(
            x=f["game_label"], y=roll,
            name=f"{w}-Game Win%",
            mode="lines",
            line=dict(color=colors[i % len(colors)], width=2),
            hovertemplate="%{x}<br>Win%%: %{y:.3f}<extra></extra>",
        ))

    fig.add_hline(y=0.500, line_dash="dot", line_color=_DIM, annotation_text=".500")

    _apply_theme(fig,
        title=dict(text=f"{team_name} — Rolling Win%", font=dict(size=16)),
        xaxis_title="Game / Date",
        yaxis_title="Win%",
        yaxis_range=[0, 1],
    )
    fig.update_xaxes(type="category")
    return fig


# ---------------------------------------------------------------------------
# Run differential per game
# ---------------------------------------------------------------------------

def run_differential_chart(games: pd.DataFrame, team_name: str) -> go.Figure:
    """
    Per-game bar chart: runs scored vs. allowed, colored by W/L.
    Overlays cumulative run differential as a line.
    """
    f = games[games["status"] == "Final"].sort_values(["game_date", "game_pk"]).reset_index(drop=True)
    if f.empty:
        return go.Figure()

    date_counts = f["game_date"].value_counts()
    dup_dates = set(date_counts[date_counts > 1].index)
    labels = []
    seen: dict[str, int] = {}
    for _, r in f.iterrows():
        d = r["game_date"]
        if d in dup_dates:
            seen[d] = seen.get(d, 0) + 1
            labels.append(f"{d} G{seen[d]}")
        else:
            labels.append(d)
    f["game_label"] = labels

    f["rd"]     = f["runs_scored"] - f["runs_allowed"]
    f["cum_rd"] = f["rd"].cumsum()
    f["color"]  = f["result"].map({"W": _GREEN, "L": _RED})
    f["game_n"] = range(1, len(f) + 1)
    f["hover"]  = f.apply(
        lambda r: f"Game {r['game_n']} ({r['game_label']})<br>"
                  f"{int(r['runs_scored'])}-{int(r['runs_allowed'])}  {r['result']}",
        axis=1,
    )

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=f["game_n"], y=f["rd"],
            marker_color=f["color"].tolist(),
            name="Run Diff",
            hovertext=f["hover"],
            hoverinfo="text",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=f["game_n"], y=f["cum_rd"],
            name="Cumulative",
            mode="lines",
            line=dict(color=_BLUE, width=2),
            hovertemplate="Game %{x}<br>Cumulative: %{y}<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.add_hline(y=0, line_color=_DIM, line_width=1)
    _apply_theme(fig,
        title=dict(text=f"{team_name} — Run Differential", font=dict(size=16)),
        xaxis_title="Game Number",
    )
    fig.update_yaxes(title_text="Game Diff", secondary_y=False, gridcolor=_GRID)
    fig.update_yaxes(title_text="Cumulative", secondary_y=True, gridcolor=_GRID)
    return fig


# ---------------------------------------------------------------------------
# Streak timeline
# ---------------------------------------------------------------------------

def streak_timeline_chart(streak_df: pd.DataFrame, team_name: str) -> go.Figure:
    """
    Bar chart where positive = win-streak length, negative = loss-streak length.
    """
    if streak_df.empty:
        return go.Figure()

    df = streak_df.copy()
    date_counts = df["game_date"].value_counts()
    dup_dates = set(date_counts[date_counts > 1].index)

    labels = []
    seen: dict[str, int] = {}
    for _, r in df.iterrows():
        d = r["game_date"]
        if d in dup_dates:
            seen[d] = seen.get(d, 0) + 1
            labels.append(f"{d} G{seen[d]}")
        else:
            labels.append(d)

    df["game_label"] = labels
    colors = [_GREEN if v > 0 else _RED for v in df["streak_value"]]

    fig = go.Figure(go.Bar(
        x=df["game_label"],
        y=df["streak_value"],
        marker_color=colors,
        hovertemplate="%{x}<br>Streak: %{y}<extra></extra>",
    ))
    fig.add_hline(y=0, line_color=_DIM, line_width=1)
    _apply_theme(fig,
        title=dict(text=f"{team_name} — Streak Timeline", font=dict(size=16)),
        xaxis_title="Date",
        yaxis_title="← Loss Streak  |  Win Streak →",
    )
    fig.update_xaxes(type="category")
    return fig


# ---------------------------------------------------------------------------
# Batting leaderboard heatmap
# ---------------------------------------------------------------------------

def batting_leaderboard_heatmap(
    batting_totals: pd.DataFrame,
    team_name: str,
    min_pa: int = 50,
) -> go.Figure:
    """
    Heatmap: players (rows) × stats (cols), color = z-score within each stat.
    Green = above team average, red = below.
    """
    stats = ["avg", "obp", "slg", "ops", "hr", "rbi", "sb", "bb_pct", "k_pct"]
    labels = ["AVG", "OBP", "SLG", "OPS", "HR", "RBI", "SB", "BB%", "K%"]
    # K% is inverted — lower is better
    inverted = {"k_pct"}

    df = batting_totals[batting_totals["pa"] >= min_pa].copy()
    if df.empty:
        return go.Figure()

    df = df.sort_values("ops", ascending=False).reset_index(drop=True)
    available = [s for s in stats if s in df.columns]
    avail_labels = [labels[stats.index(s)] for s in available]

    z_matrix = []
    text_matrix = []
    for stat in available:
        col   = df[stat].fillna(0).astype(float)
        std   = col.std()
        mean  = col.mean()
        z     = (col - mean) / std if std > 0 else col * 0
        if stat in inverted:
            z = -z
        z_matrix.append(z.tolist())
        text_matrix.append([f"{v:.3f}" if stat in ("avg","obp","slg","ops","bb_pct","k_pct")
                             else str(int(v)) for v in col])

    fig = go.Figure(go.Heatmap(
        z=list(map(list, zip(*z_matrix))),       # transpose: players × stats
        x=avail_labels,
        y=df["player_name"].tolist(),
        text=list(map(list, zip(*text_matrix))),
        texttemplate="%{text}",
        colorscale=[[0, _RED], [0.5, _BG], [1, _GREEN]],
        showscale=False,
        hovertemplate="%{y}  %{x}: %{text}<extra></extra>",
    ))
    _apply_theme(fig,
        title=dict(text=f"{team_name} — Batting Leaderboard (z-score shading)", font=dict(size=16)),
        height=max(400, len(df) * 30 + 100),
    )
    return fig


# ---------------------------------------------------------------------------
# Hot / cold chart
# ---------------------------------------------------------------------------

def hot_cold_chart(hot_cold: pd.DataFrame, team_name: str) -> go.Figure:
    """
    Horizontal bar chart of each player's L7 OPS delta vs. season average.
    Green = hot, red = cold.
    """
    delta_col = [c for c in hot_cold.columns if c.startswith("last_") and c.endswith("_ops")]
    if not delta_col or hot_cold.empty:
        return go.Figure()

    df = hot_cold.sort_values("delta").reset_index(drop=True)
    colors = [_GREEN if d >= 0.100 else (_RED if d <= -0.100 else _DIM)
              for d in df["delta"]]

    fig = go.Figure(go.Bar(
        x=df["delta"],
        y=df["player_name"],
        orientation="h",
        marker_color=colors,
        hovertemplate="%{y}<br>Δ OPS: %{x:+.3f}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color=_DIM, line_width=1)
    fig.add_vline(x=0.100,  line_dash="dot", line_color=_GREEN, annotation_text="Hot")
    fig.add_vline(x=-0.100, line_dash="dot", line_color=_RED,   annotation_text="Cold")

    _apply_theme(fig,
        title=dict(text=f"{team_name} — Hot / Cold (L7 OPS vs. Season)", font=dict(size=16)),
        xaxis_title="OPS Delta",
        height=max(400, len(df) * 25 + 100),
    )
    return fig


# ---------------------------------------------------------------------------
# Rotation heatmap  (game score by start)
# ---------------------------------------------------------------------------

def rotation_heatmap(pitching: pd.DataFrame, team_name: str) -> go.Figure:
    """
    Heatmap: starters (rows) × start number (cols), color = game score.
    Green = strong start (≥60), red = poor start (<40).
    """
    starters = pitching[pitching["is_starter"] == True].copy()
    if starters.empty:
        return go.Figure()

    starters = starters.sort_values("game_date")
    starters["start_n"] = starters.groupby("player_id").cumcount() + 1

    pitcher_names = (
        starters.groupby("player_id")["player_name"].first()
        .sort_values().index.tolist()
    )
    max_starts = int(starters["start_n"].max())

    z_matrix = []
    text_matrix = []
    for pid in pitcher_names:
        row_data = starters[starters["player_id"] == pid].set_index("start_n")["game_score"]
        z_row    = [float(row_data.get(n, float("nan"))) for n in range(1, max_starts + 1)]
        txt_row  = [str(int(v)) if not pd.isna(v) else "" for v in z_row]
        z_matrix.append(z_row)
        text_matrix.append(txt_row)

    name_map = starters.groupby("player_id")["player_name"].first().to_dict()
    y_labels = [name_map.get(pid, str(pid)) for pid in pitcher_names]

    fig = go.Figure(go.Heatmap(
        z=z_matrix,
        x=list(range(1, max_starts + 1)),
        y=y_labels,
        text=text_matrix,
        texttemplate="%{text}",
        colorscale=[[0, _RED], [0.4, _YELLOW], [0.65, _BG], [1, _GREEN]],
        zmin=0, zmax=100,
        colorbar=dict(title="Game Score"),
        hovertemplate="Start %{x}<br>%{y}<br>Game Score: %{z}<extra></extra>",
    ))
    _apply_theme(fig,
        title=dict(text=f"{team_name} — Rotation Game Scores by Start", font=dict(size=16)),
        xaxis_title="Start Number",
        height=max(300, len(pitcher_names) * 45 + 100),
    )
    return fig


# ---------------------------------------------------------------------------
# Bullpen load heatmap
# ---------------------------------------------------------------------------

def bullpen_load_chart(pitching: pd.DataFrame, team_name: str) -> go.Figure:
    """
    Heatmap: reliever (rows) × date (cols), color = pitches thrown.
    Shows workload distribution across the bullpen over time.
    """
    relievers = pitching[pitching["is_starter"] == False].copy()
    if relievers.empty:
        return go.Figure()

    relievers["game_date"] = pd.to_datetime(relievers["game_date"])
    pivot = (
        relievers.groupby(["player_name", "game_date"])["pitches"]
        .sum()
        .unstack(fill_value=0)
    )
    if pivot.empty:
        return go.Figure()

    # Order by total pitches
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
    dates  = [str(d.date()) for d in pivot.columns]

    fig = go.Figure(go.Heatmap(
        z=pivot.values.tolist(),
        x=dates,
        y=pivot.index.tolist(),
        colorscale=[[0, _BG], [0.3, _YELLOW], [1, _RED]],
        zmin=0,
        colorbar=dict(title="Pitches"),
        hovertemplate="%{y}<br>%{x}<br>Pitches: %{z}<extra></extra>",
    ))
    _apply_theme(fig,
        title=dict(text=f"{team_name} — Bullpen Workload by Date", font=dict(size=16)),
        xaxis_title="Date",
        height=max(300, len(pivot) * 28 + 100),
    )
    fig.update_xaxes(tickangle=45)
    return fig


# ---------------------------------------------------------------------------
# ERA split chart
# ---------------------------------------------------------------------------

def era_split_chart(team_era_split: dict, team_name: str) -> go.Figure:
    """
    Side-by-side bars: starter ERA vs. bullpen ERA with league-average reference.
    """
    if not team_era_split:
        return go.Figure()

    categories = ["Starters", "Bullpen", "Team"]
    values     = [
        team_era_split.get("starter_era", 0),
        team_era_split.get("bullpen_era", 0),
        team_era_split.get("era", 0),
    ]
    # Color code: green if below league avg (~4.00), red if above
    league_avg = 4.00
    bar_colors = [_GREEN if v < league_avg else _RED for v in values]

    fig = go.Figure(go.Bar(
        x=categories, y=values,
        marker_color=bar_colors,
        text=[f"{v:.2f}" for v in values],
        textposition="outside",
        hovertemplate="%{x}: %{y:.2f} ERA<extra></extra>",
    ))
    fig.add_hline(y=league_avg, line_dash="dot", line_color=_DIM,
                  annotation_text=f"Lg Avg ({league_avg:.2f})")

    _apply_theme(fig,
        title=dict(text=f"{team_name} — ERA by Role", font=dict(size=16)),
        yaxis_title="ERA",
        yaxis_range=[0, max(values) * 1.3 if values else 6],
    )
    return fig


# ---------------------------------------------------------------------------
# Historical win% bar chart
# ---------------------------------------------------------------------------

def multi_season_win_pct(
    historical: pd.DataFrame,
    team_name: str,
    highlight_seasons: dict[int, str] | None = None,
) -> go.Figure:
    """
    Bar chart of win% per season.
    highlight_seasons: {year: label} — marks notable seasons (e.g., World Series wins).
    """
    if historical.empty:
        return go.Figure()

    df = historical.sort_values("season")
    colors = []
    for year in df["season"]:
        if highlight_seasons and year in highlight_seasons:
            colors.append(_YELLOW)
        else:
            colors.append(_BLUE)

    fig = go.Figure(go.Bar(
        x=df["season"].astype(str),
        y=df["win_pct"],
        marker_color=colors,
        text=df.apply(lambda r: f"{r['wins']}-{r['losses']}", axis=1),
        textposition="outside",
        hovertemplate="%{x}: %{y:.3f} Win%<br>%{text}<extra></extra>",
    ))

    if highlight_seasons:
        for year, label in highlight_seasons.items():
            row = df[df["season"] == year]
            if not row.empty:
                fig.add_annotation(
                    x=str(year), y=float(row["win_pct"].iloc[0]) + 0.03,
                    text=f"🏆", showarrow=False, font=dict(size=14),
                )

    fig.add_hline(y=0.500, line_dash="dot", line_color=_DIM, annotation_text=".500")

    _apply_theme(fig,
        title=dict(text=f"{team_name} — Win% by Season", font=dict(size=16)),
        xaxis_title="Season",
        yaxis_title="Win%",
        yaxis_range=[0, 0.75],
        xaxis_tickangle=45,
        height=500,
    )
    return fig


# ---------------------------------------------------------------------------
# Pace comparison chart
# ---------------------------------------------------------------------------

def pace_comparison_chart(
    current_games: pd.DataFrame,
    historical_seasons: dict[int, pd.DataFrame],
    team_name: str,
) -> go.Figure:
    """
    Multi-line chart: cumulative win% by game number.
    current_games = this season's games DataFrame.
    historical_seasons = {year: games_df} for reference seasons.
    """
    fig = go.Figure()
    colors_pool = [_BLUE, _YELLOW, _GREEN, _RED, "#a371f7", "#79c0ff"]

    def _cum_win_pct(df: pd.DataFrame) -> pd.Series:
        f = df[df["status"] == "Final"].sort_values("game_date").reset_index(drop=True)
        f["win_flag"] = (f["result"] == "W").astype(int)
        f["game_n"]   = range(1, len(f) + 1)
        f["cum_pct"]  = f["win_flag"].expanding().mean()
        return f.set_index("game_n")["cum_pct"]

    # Historical lines first (dimmer)
    for i, (year, df) in enumerate(historical_seasons.items()):
        pct = _cum_win_pct(df)
        fig.add_trace(go.Scatter(
            x=pct.index, y=pct.values,
            name=str(year),
            mode="lines",
            line=dict(color=colors_pool[i % len(colors_pool)], width=1, dash="dot"),
            opacity=0.6,
        ))

    # Current season on top, bold
    curr_pct = _cum_win_pct(current_games)
    season   = current_games["season"].iloc[0] if not current_games.empty else "Current"
    fig.add_trace(go.Scatter(
        x=curr_pct.index, y=curr_pct.values,
        name=f"{season} (current)",
        mode="lines",
        line=dict(color=_TEXT, width=3),
    ))

    fig.add_hline(y=0.500, line_dash="dot", line_color=_DIM, annotation_text=".500")

    _apply_theme(fig,
        title=dict(text=f"{team_name} — Season Pace Comparison", font=dict(size=16)),
        xaxis_title="Game Number",
        yaxis_title="Cumulative Win%",
        yaxis_range=[0.3, 0.8],
    )
    return fig


# ---------------------------------------------------------------------------
# Player rolling slash line
# ---------------------------------------------------------------------------

def player_trend_chart(
    rolling_slash: pd.DataFrame,
    player_name: str,
) -> go.Figure:
    """Line chart of a single player's rolling AVG/OBP/SLG/OPS over the season."""
    if rolling_slash.empty:
        return go.Figure()

    fig = go.Figure()
    stat_colors = {"ops": _BLUE, "slg": _GREEN, "obp": _YELLOW, "avg": _DIM}
    for stat, color in stat_colors.items():
        if stat not in rolling_slash.columns:
            continue
        fig.add_trace(go.Scatter(
            x=rolling_slash.index,
            y=rolling_slash[stat],
            name=stat.upper(),
            mode="lines",
            line=dict(color=color, width=2),
            hovertemplate=f"%{{x}}<br>{stat.upper()}: %{{y:.3f}}<extra></extra>",
        ))

    _apply_theme(fig,
        title=dict(text=f"{player_name} — Rolling Slash Line", font=dict(size=16)),
        xaxis_title="Date",
        yaxis_title="Rate Stat",
    )
    return fig


# ---------------------------------------------------------------------------
# Turnaround Figure 1: Inflection Point / Net Games Above/Below .500
# ---------------------------------------------------------------------------

def momentum_curve_chart(games: pd.DataFrame, team_name: str) -> go.Figure:
    """
    Cumulative net games above/below .500 (Wins - Losses) per game number.
    Annotates the low point (e.g. -12) and highlights the active win streak.
    """
    f = games[games["status"] == "Final"].sort_values("game_date").reset_index(drop=True)
    if f.empty:
        return go.Figure()

    f["win_flag"]  = (f["result"] == "W").astype(int)
    f["loss_flag"] = (f["result"] == "L").astype(int)
    f["net_games"] = f["win_flag"].cumsum() - f["loss_flag"].cumsum()
    f["game_n"]    = range(1, len(f) + 1)

    min_idx  = f["net_games"].idxmin()
    min_val  = f.loc[min_idx, "net_games"]
    min_game = f.loc[min_idx, "game_n"]

    last_val  = f["net_games"].iloc[-1]
    last_game = f["game_n"].iloc[-1]

    fig = go.Figure()

    # Base net curve
    fig.add_trace(go.Scatter(
        x=f["game_n"], y=f["net_games"],
        name="Net W-L (.500 Delta)",
        mode="lines+markers",
        line=dict(color=_GREEN if last_val >= 0 else _RED, width=3),
        marker=dict(size=4),
        hovertemplate="Game %{x} (%{text})<br>Net: %{y:+d}<extra></extra>",
        text=f["game_date"],
    ))

    # .500 Reference line
    fig.add_hline(y=0, line_dash="dash", line_color=_DIM, annotation_text=".500 Baseline")

    # Annotate low point
    fig.add_annotation(
        x=min_game, y=min_val,
        text=f"Low Point: {min_val:+d} (Game {min_game})",
        showarrow=True, arrowhead=2, ax=0, ay=35,
        bgcolor=_PAPER_BG, bordercolor=_RED, font=dict(color=_RED, size=12)
    )

    # Annotate current peak/streak
    fig.add_annotation(
        x=last_game, y=last_val,
        text=f"Current Peak: {last_val:+d} (Game {last_game})",
        showarrow=True, arrowhead=2, ax=-40, ay=-35,
        bgcolor=_PAPER_BG, bordercolor=_GREEN, font=dict(color=_GREEN, size=12)
    )

    _apply_theme(fig,
        title=dict(text=f"{team_name} — Season Turnaround & Momentum Curve", font=dict(size=16)),
        xaxis_title="Game Number",
        yaxis_title="Games Above / Below .500",
    )
    return fig


# ---------------------------------------------------------------------------
# Turnaround Figure 2: Monthly Differential & Win% Surge
# ---------------------------------------------------------------------------

def monthly_surge_chart(monthly_df: pd.DataFrame, team_name: str) -> go.Figure:
    """
    Subplot chart: Monthly Run Differential (Bars) & Monthly Win% (Line).
    """
    if monthly_df.empty:
        return go.Figure()

    df = monthly_df.copy()
    df["month_str"] = df["month"].astype(str)
    colors = [_GREEN if rd >= 0 else _RED for rd in df["run_diff"]]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Run Diff Bars
    fig.add_trace(go.Bar(
        x=df["month_str"], y=df["run_diff"],
        name="Run Differential",
        marker_color=colors,
        hovertemplate="Month %{x}<br>Run Diff: %{y:+d}<extra></extra>",
    ), secondary_y=False)

    # Win% Line
    fig.add_trace(go.Scatter(
        x=df["month_str"], y=df["win_pct"],
        name="Win%",
        mode="lines+markers",
        line=dict(color=_BLUE, width=3),
        marker=dict(size=8, color=_BLUE),
        hovertemplate="Month %{x}<br>Win%%: %{y:.3f}<extra></extra>",
    ), secondary_y=True)

    fig.add_hline(y=0, line_color=_DIM, line_width=1, secondary_y=False)
    fig.add_hline(y=0.500, line_dash="dot", line_color=_DIM, secondary_y=True)

    _apply_theme(fig,
        title=dict(text=f"{team_name} — Monthly Surge & Run Differential", font=dict(size=16)),
        xaxis_title="Month",
    )
    fig.update_yaxes(title_text="Run Differential", secondary_y=False, gridcolor=_GRID)
    fig.update_yaxes(title_text="Win%", secondary_y=True, gridcolor=_GRID, range=[0, 1.0])
    return fig


# ---------------------------------------------------------------------------
# Turnaround Figure 3: Rolling Synergy (OPS vs. ERA)
# ---------------------------------------------------------------------------

def rolling_synergy_chart(
    games: pd.DataFrame,
    batting: pd.DataFrame,
    pitching: pd.DataFrame,
    team_name: str,
    window: int = 7,
) -> go.Figure:
    """
    Dual-axis rolling time-series: Rolling 7-Game Team OPS (Primary Y)
    vs Rolling 7-Game Team ERA (Secondary Y, inverted).
    """
    f = games[games["status"] == "Final"].sort_values(["game_date", "game_pk"]).reset_index(drop=True)
    if f.empty or batting.empty or pitching.empty:
        return go.Figure()

    # Per-game batting OPS (grouped by game_pk to handle doubleheaders)
    b_grp = batting.groupby(["game_date", "game_pk"]).agg(
        ab=("ab", "sum"), h=("h", "sum"), bb=("bb", "sum"),
        hbp=("hbp", "sum"), sf=("sac_fly", "sum"),
        doubles=("doubles", "sum"), triples=("triples", "sum"), hr=("hr", "sum")
    ).reset_index().sort_values("game_pk")
    b_grp["tb"] = b_grp["h"] + b_grp["doubles"] + 2 * b_grp["triples"] + 3 * b_grp["hr"]

    # Rolling batting over last N games
    b_grp["roll_ab"] = b_grp["ab"].rolling(window).sum()
    b_grp["roll_h"]  = b_grp["h"].rolling(window).sum()
    b_grp["roll_bb"] = b_grp["bb"].rolling(window).sum()
    b_grp["roll_hbp"]= b_grp["hbp"].rolling(window).sum()
    b_grp["roll_sf"] = b_grp["sf"].rolling(window).sum()
    b_grp["roll_tb"] = b_grp["tb"].rolling(window).sum()

    obp_d = b_grp["roll_ab"] + b_grp["roll_bb"] + b_grp["roll_hbp"] + b_grp["roll_sf"]
    roll_obp = (b_grp["roll_h"] + b_grp["roll_bb"] + b_grp["roll_hbp"]) / obp_d
    roll_slg = b_grp["roll_tb"] / b_grp["roll_ab"]
    b_grp["roll_ops"] = (roll_obp + roll_slg).round(3)

    # Per-game pitching ERA (grouped by game_pk)
    p_grp = pitching.groupby(["game_date", "game_pk"]).agg(
        ip=("ip", "sum"), er=("er", "sum")
    ).reset_index().sort_values("game_pk")
    p_grp["roll_ip"]  = p_grp["ip"].rolling(window).sum()
    p_grp["roll_er"]  = p_grp["er"].rolling(window).sum()
    p_grp["roll_era"] = (p_grp["roll_er"] * 9 / p_grp["roll_ip"]).round(2)

    merged = pd.merge(b_grp[["game_date", "game_pk", "roll_ops"]], p_grp[["game_date", "game_pk", "roll_era"]], on=["game_date", "game_pk"]).dropna()
    if merged.empty:
        return go.Figure()

    # Differentiate doubleheader dates
    date_counts = merged["game_date"].value_counts()
    dup_dates = set(date_counts[date_counts > 1].index)
    labels = []
    seen: dict[str, int] = {}
    for _, r in merged.iterrows():
        d = r["game_date"]
        if d in dup_dates:
            seen[d] = seen.get(d, 0) + 1
            labels.append(f"{d} G{seen[d]}")
        else:
            labels.append(d)
    merged["game_label"] = labels

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Scatter(
        x=merged["game_label"], y=merged["roll_ops"],
        name=f"{window}-Game Team OPS",
        mode="lines",
        line=dict(color=_GREEN, width=3),
        hovertemplate="%{x}<br>OPS: %{y:.3f}<extra></extra>",
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=merged["game_label"], y=merged["roll_era"],
        name=f"{window}-Game Team ERA",
        mode="lines",
        line=dict(color=_BLUE, width=3),
        hovertemplate="%{x}<br>ERA: %{y:.2f}<extra></extra>",
    ), secondary_y=True)

    _apply_theme(fig,
        title=dict(text=f"{team_name} — Rolling Synergy (OPS vs. ERA)", font=dict(size=16)),
        xaxis_title="Date",
    )
    fig.update_xaxes(type="category")
    fig.update_yaxes(title_text="Team OPS", secondary_y=False, gridcolor=_GRID)
    fig.update_yaxes(title_text="Team ERA", secondary_y=True, gridcolor=_GRID, autorange="reversed")
    return fig


# ---------------------------------------------------------------------------
# Turnaround Figure 5: Platoon Diverging Bar Chart
# ---------------------------------------------------------------------------

def platoon_diverging_chart(plat_summary: pd.DataFrame, team_name: str) -> go.Figure:
    """
    Diverging / side-by-side bar chart showing vs-LHP OPS vs vs-RHP OPS and Platoon Delta.
    plat_summary: output from pivoted_platoon_summary().
    """
    if plat_summary.empty:
        return go.Figure()

    df = plat_summary[plat_summary["l_ab"] + plat_summary["r_ab"] >= 30].sort_values("ops_delta", ascending=True)
    if df.empty:
        return go.Figure()

    fig = go.Figure()

    fig.add_trace(go.Bar(
        y=df["player_name"], x=df["l_ops"],
        name="vs LHP OPS", orientation="h",
        marker_color=_GREEN,
        hovertemplate="%{y}<br>vs LHP OPS: %{x:.3f}<extra></extra>",
    ))

    fig.add_trace(go.Bar(
        y=df["player_name"], x=df["r_ops"],
        name="vs RHP OPS", orientation="h",
        marker_color=_BLUE,
        hovertemplate="%{y}<br>vs RHP OPS: %{x:.3f}<extra></extra>",
    ))

    _apply_theme(fig,
        title=dict(text=f"{team_name} — Platoon Splits (vs LHP vs vs RHP OPS)", font=dict(size=16)),
        xaxis_title="OPS",
        yaxis_title="Player",
        barmode="group",
    )
    return fig
