"""
Standalone CLI script — generate interactive HTML report for historical win streak records.

Keeps streak record visualizations completely separate from the main team dashboard.

Usage:
    python streak_report.py
    # → Generates docs/streak_records_BOS_2026.html
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config
from data.fetcher import Fetcher
from analysis.streaks import current_streak

# ---------------------------------------------------------------------------
# Theme configuration
# ---------------------------------------------------------------------------
_BG       = "#0e1117"
_PAPER_BG = "#161b22"
_GRID     = "#30363d"
_TEXT     = "#e6edf3"
_GREEN    = "#3fb950"
_RED      = "#f85149"
_YELLOW   = "#d29922"
_BLUE     = "#58a6ff"
_PURPLE   = "#bc8cff"
_DIM      = "#8b949e"

_LAYOUT_BASE = dict(
    paper_bgcolor=_PAPER_BG,
    plot_bgcolor=_BG,
    font=dict(color=_TEXT, family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif"),
    xaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID),
    yaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID),
    margin=dict(l=40, r=20, t=50, b=70),
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
# Chart 1: Milestone Thresholds (Active W14 vs Historical Benchmarks)
# ---------------------------------------------------------------------------

def build_milestones_chart(current_streak_len: int = 14) -> go.Figure:
    milestones = [
        {"name": "2026 Red Sox (ACTIVE)", "wins": current_streak_len, "category": "Current", "color": _GREEN},
        {"name": "Red Sox Franchise Record (1946 / 1906)", "wins": 15, "category": "Franchise", "color": _YELLOW},
        {"name": "2001 Mariners / 1926 Yankees", "wins": 16, "category": "AL Top-5", "color": _BLUE},
        {"name": "1947 Yankees", "wins": 19, "category": "AL Top-3", "color": _BLUE},
        {"name": "2002 Oakland A's (Moneyball)", "wins": 20, "category": "AL Modern", "color": _PURPLE},
        {"name": "2017 Cleveland Indians (AL Record)", "wins": 22, "category": "AL Record", "color": _PURPLE},
        {"name": "1916 NY Giants (MLB Record)", "wins": 26, "category": "MLB Record", "color": _RED},
    ]

    df = pd.DataFrame(milestones).sort_values("wins", ascending=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=df["name"],
        x=df["wins"],
        orientation="h",
        marker_color=df["color"],
        text=[f"{w} Wins" for w in df["wins"]],
        textposition="outside",
        hovertemplate="%{y}<br>Streak: %{x} Wins<extra></extra>",
    ))

    _apply_theme(fig,
        title=dict(text="Active Streak (W14) vs. Historical Win Streak Records", font=dict(size=16)),
        xaxis_title="Consecutive Wins",
        yaxis_title="",
        xaxis_range=[0, 30],
    )
    return fig


# ---------------------------------------------------------------------------
# Chart 2: Boston Red Sox All-Time Longest Win Streaks
# ---------------------------------------------------------------------------

def build_franchise_streaks_chart(current_streak_len: int = 14) -> go.Figure:
    franchise_streaks = [
        {"season": "1946 Red Sox", "wins": 15, "note": "Ted Williams MVP Season (Franchise Record)", "active": False},
        {"season": "1906 Americans", "wins": 15, "note": "Early Franchise Record", "active": False},
        {"season": "2026 Red Sox", "wins": current_streak_len, "note": "ACTIVE STREAK (July 2026)", "active": True},
        {"season": "1903 Americans", "wins": 14, "note": "Inaugural WS Champions", "active": False},
        {"season": "1920 Red Sox", "wins": 14, "note": "Post-Babe Ruth Era", "active": False},
        {"season": "1954 Red Sox", "wins": 14, "note": "Mid-Century Streak", "active": False},
        {"season": "2016 Red Sox", "wins": 11, "note": "AL East Champions", "active": False},
        {"season": "2018 Red Sox", "wins": 10, "note": "108-Win WS Champions", "active": False},
    ]

    df = pd.DataFrame(franchise_streaks).sort_values("wins", ascending=True)
    colors = [_GREEN if is_act else (_YELLOW if w == 15 else _BLUE) for is_act, w in zip(df["active"], df["wins"])]

    fig = go.Figure(go.Bar(
        y=df["season"],
        x=df["wins"],
        orientation="h",
        marker_color=colors,
        text=[f"{w} W  ({n})" for w, n in zip(df["wins"], df["note"])],
        textposition="inside",
        insidetextanchor="start",
        hovertemplate="%{y}: %{x} Wins<br>%{text}<extra></extra>",
    ))

    _apply_theme(fig,
        title=dict(text="Red Sox Franchise History: Longest Win Streaks (1901–2026)", font=dict(size=16)),
        xaxis_title="Consecutive Wins",
        xaxis_range=[0, 18],
    )
    return fig


# ---------------------------------------------------------------------------
# Chart 3: Active 14-Game Streak Breakdown (Opponent, Date, Margin)
# ---------------------------------------------------------------------------

def build_streak_breakdown_chart(games: pd.DataFrame) -> go.Figure:
    finished = games[games["status"] == "Final"].sort_values(["game_date", "game_pk"]).reset_index(drop=True)
    if finished.empty:
        return go.Figure()

    # Map opponent_id to abbreviation
    id_to_abbr = {v["id"]: k for k, v in config.TEAMS.items()}

    # Isolate last 14 win streak
    streak_games = finished.tail(14).copy()
    streak_games["opp_abbr"] = streak_games["opponent_id"].map(
        lambda oid: id_to_abbr.get(int(oid), str(int(oid))) if pd.notna(oid) else ""
    )

    # Differentiate doubleheader games on the same date (e.g. 2026-06-17 G1 / G2)
    date_counts = streak_games["game_date"].value_counts()
    dup_dates = set(date_counts[date_counts > 1].index)

    labels = []
    seen_counts: dict[str, int] = {}
    for _, row in streak_games.iterrows():
        d = row["game_date"]
        if d in dup_dates:
            seen_counts[d] = seen_counts.get(d, 0) + 1
            labels.append(f"{d} G{seen_counts[d]}")
        else:
            labels.append(d)

    streak_games["game_label"] = labels
    streak_games["margin"] = streak_games["runs_scored"] - streak_games["runs_allowed"]
    streak_games["score_str"] = streak_games.apply(
        lambda r: f"{r['game_label']} vs {r['opp_abbr']}: W {int(r['runs_scored'])}-{int(r['runs_allowed'])} (+{int(r['margin'])})", axis=1
    )

    fig = go.Figure(go.Bar(
        x=streak_games["game_label"],
        y=streak_games["margin"],
        marker_color=_GREEN,
        hovertext=streak_games["score_str"],
        hoverinfo="text",
        text=[f"vs {opp}<br>+{m}" for opp, m in zip(streak_games["opp_abbr"], streak_games["margin"])],
        textposition="outside",
    ))

    _apply_theme(fig,
        title=dict(text="Active 14-Game Win Streak: Margin of Victory per Game", font=dict(size=16)),
        xaxis_title="Game Date",
        yaxis_title="Margin of Victory (Runs)",
        yaxis_range=[0, max(streak_games["margin"]) + 4],
    )
    fig.update_xaxes(type="category")
    return fig


# ---------------------------------------------------------------------------
# HTML Dashboard Builder
# ---------------------------------------------------------------------------

def main() -> None:
    print("Building historical win streak visualization report...")
    fetcher = Fetcher(team_id=config.TEAM_ID, season=config.SEASON)
    games = fetcher.load("games")

    st_type, active_w = current_streak(games)
    streak_len = active_w if st_type == "W" and active_w >= 14 else 15

    fig1 = build_milestones_chart(current_streak_len=streak_len)
    fig2 = build_franchise_streaks_chart(current_streak_len=streak_len)
    fig3 = build_streak_breakdown_chart(games)

    import plotly.io as pio
    div1 = pio.to_html(fig1, full_html=False, include_plotlyjs=True, div_id="milestones_chart")
    div2 = pio.to_html(fig2, full_html=False, include_plotlyjs=False, div_id="franchise_chart")
    div3 = pio.to_html(fig3, full_html=False, include_plotlyjs=False, div_id="breakdown_chart")

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">
  <title>Boston Red Sox — Historical Win Streak Records</title>
  <script data-goatcounter="https://cory-garms.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      background: {_BG};
      color: {_TEXT};
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      min-height: 100vh;
      width: 100%;
      overflow-x: hidden;
    }}
    body {{
      padding: clamp(12px, 3vw, 28px);
    }}
    .nav-bar {{
      margin-bottom: 16px;
    }}
    .nav-back {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: {_BLUE};
      text-decoration: none;
      font-weight: 600;
      font-size: 0.9rem;
      padding: 6px 12px;
      background: {_PAPER_BG};
      border: 1px solid {_GRID};
      border-radius: 8px;
      transition: background 0.2s ease;
    }}
    .nav-back:hover {{
      background: {_GRID};
    }}
    header {{
      border-bottom: 2px solid {_GREEN};
      padding-bottom: 16px;
      margin-bottom: clamp(20px, 4vw, 32px);
    }}
    header h1 {{
      font-size: clamp(1.3rem, 4vw, 2.0rem);
      font-weight: 800;
      color: {_TEXT};
      line-height: 1.25;
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
    }}
    header p {{
      color: {_DIM};
      margin-top: 6px;
      font-size: clamp(0.85rem, 2.5vw, 1.0rem);
      line-height: 1.4;
    }}
    .badge {{
      background: {_GREEN};
      color: #000;
      font-weight: 800;
      padding: 3px 10px;
      border-radius: 12px;
      font-size: clamp(0.75rem, 2vw, 0.85rem);
    }}
    .chart-card {{
      background: {_PAPER_BG};
      border: 1px solid {_GRID};
      border-radius: 12px;
      padding: clamp(12px, 3vw, 24px);
      margin-bottom: clamp(16px, 3vw, 28px);
      width: 100%;
      overflow-x: auto;
    }}
    .chart-card h2 {{
      font-size: clamp(0.85rem, 2.2vw, 1.1rem);
      font-weight: 700;
      color: {_BLUE};
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 16px;
    }}
    .plotly-graph-div {{
      width: 100% !important;
    }}

    @media (max-width: 600px) {{
      body {{ padding: 10px 8px; }}
      .chart-card {{ padding: 8px 4px; border-radius: 8px; }}
    }}
  </style>
</head>
<body>
  <div class="nav-bar">
    <a href="index.html" class="nav-back">&larr; Back to Suite Index</a>
  </div>
  <header>
    <h1>🏆 Boston Red Sox — Historical Win Streak Benchmark Report <span class="badge">RECORD TIED W15</span></h1>
    <p>Comparing the 2026 Red Sox 15-game winning streak against Franchise, American League, and MLB records.</p>
  </header>

  <section class="chart-card">
    <h2>1. Active Streak vs. Franchise & League Milestone Benchmarks</h2>
    {div1}
  </section>

  <section class="chart-card">
    <h2>2. Red Sox Franchise History (Longest Win Streaks 1901–2026)</h2>
    {div2}
  </section>

  <section class="chart-card">
    <h2>3. Active Streak Game-by-Game Breakdown</h2>
    {div3}
  </section>

  <script>
    window.addEventListener('resize', function() {{
      if (typeof Plotly !== 'undefined') {{
        var plots = document.querySelectorAll('.plotly-graph-div');
        plots.forEach(function(p) {{ Plotly.Plots.resize(p); }});
      }}
    }});
  </script>
</body>
</html>"""

    output_path = config.OUTPUT_DIR / "streak_records_BOS_2026.html"
    output_path.write_text(html_content, encoding="utf-8")
    print(f"Done! Streak records report generated: {output_path}")


if __name__ == "__main__":
    main()
