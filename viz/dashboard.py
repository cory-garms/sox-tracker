"""
Combined Plotly dashboard — assembles all charts into one self-contained HTML file.

Usage:
    python viz_report.py --team BOS --season 2025
    # → output/dashboard_BOS_2025.html
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import OUTPUT_DIR, TEAM_ABBR, SEASON
from viz.charts import (
    _apply_theme, _BG, _PAPER_BG, _GRID, _TEXT, _GREEN, _RED, _BLUE, _YELLOW, _DIM,
    season_timeline,
    rolling_win_pct_chart,
    run_differential_chart,
    streak_timeline_chart,
    batting_leaderboard_heatmap,
    hot_cold_chart,
    rotation_heatmap,
    bullpen_load_chart,
    era_split_chart,
)


# ---------------------------------------------------------------------------
# Individual figure → HTML div helper
# ---------------------------------------------------------------------------

def _fig_div(fig: go.Figure, div_id: str, height: int = 450) -> str:
    """Return a standalone <div> with embedded Plotly chart (no CDN script tag)."""
    import plotly.io as pio
    fig.update_layout(height=height)
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, div_id=div_id)


# ---------------------------------------------------------------------------
# Full dashboard
# ---------------------------------------------------------------------------

def build(
    games: pd.DataFrame,
    batting: pd.DataFrame,
    pitching: pd.DataFrame,
    fielding: pd.DataFrame,
    team_name: str,
    team_abbr: str = TEAM_ABBR,
    season: int = SEASON,
    output_path: Path | None = None,
) -> Path:
    """
    Build and write the full interactive HTML dashboard.

    Sections (top to bottom):
      1.  Season Timeline (cumulative W-L)
      2.  Rolling Win% (7-game, 15-game)
      3.  Run Differential per game + cumulative
      4.  Streak Timeline
      5.  Batting Leaderboard Heatmap
      6.  Hot / Cold Tracker
      7.  Rotation Game Score Heatmap
      8.  Bullpen Workload Heatmap
      9.  ERA by Role (bar chart)

    Returns the path to the written HTML file.
    """
    from analysis.offense import player_season_totals, hot_cold_summary
    from analysis.pitching import team_pitching_split
    from analysis.streaks import streak_timeline

    if output_path is None:
        output_path = OUTPUT_DIR / f"dashboard_{team_abbr}_{season}.html"

    figures: list[tuple[str, go.Figure, int]] = []  # (title, fig, height)

    # 1. Season timeline
    fig1 = season_timeline(games, team_name)
    figures.append(("Season Timeline", fig1, 420))

    # 2. Rolling win%
    fig2 = rolling_win_pct_chart(games, team_name, windows=[7, 15])
    figures.append(("Rolling Win%", fig2, 380))

    # 3. Run differential
    fig3 = run_differential_chart(games, team_name)
    figures.append(("Run Differential", fig3, 420))

    # 4. Streak timeline
    streak_df = streak_timeline(games)
    fig4 = streak_timeline_chart(streak_df, team_name)
    figures.append(("Streak Timeline", fig4, 320))

    # 5. Batting leaderboard heatmap
    totals = player_season_totals(batting)
    if not totals.empty:
        fig5 = batting_leaderboard_heatmap(totals, team_name)
        figures.append(("Batting Leaderboard", fig5, max(400, len(totals) * 30 + 100)))

    # 6. Hot / cold
    hc = hot_cold_summary(batting, windows=[7, 15])
    if not hc.empty:
        fig6 = hot_cold_chart(hc, team_name)
        figures.append(("Hot / Cold", fig6, max(380, len(hc) * 25 + 100)))

    # 7. Rotation heatmap
    if not pitching.empty:
        fig7 = rotation_heatmap(pitching, team_name)
        figures.append(("Rotation Game Scores", fig7, 380))

    # 8. Bullpen load
    if not pitching.empty:
        fig8 = bullpen_load_chart(pitching, team_name)
        figures.append(("Bullpen Workload", fig8, 380))

    # 9. ERA split
    split = team_pitching_split(pitching) if not pitching.empty else {}
    if split:
        fig9 = era_split_chart(split, team_name)
        figures.append(("ERA by Role", fig9, 360))

    # -----------------------------------------------------------------------
    # Assemble HTML
    # -----------------------------------------------------------------------
    import plotly.io as pio

    divs_html = ""
    for i, (title, fig, height) in enumerate(figures):
        div_id = title.lower().replace(" ", "_").replace("/", "_")
        # Inject the Plotly CDN script only once, from the first figure,
        # so the version always matches the installed plotly package.
        include_js = "cdn" if i == 0 else False
        fig.update_layout(height=height)
        chart_div = pio.to_html(fig, full_html=False, include_plotlyjs=include_js, div_id=div_id)
        divs_html += f"""
        <section class="chart-section">
            <h2 class="chart-title">{title}</h2>
            {chart_div}
        </section>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{team_name} — {season} Dashboard</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: {_BG};
      color: {_TEXT};
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", monospace;
      padding: 24px;
    }}
    header {{
      border-bottom: 1px solid {_GRID};
      padding-bottom: 16px;
      margin-bottom: 32px;
    }}
    header h1 {{ font-size: 1.8rem; color: {_TEXT}; }}
    header p  {{ color: {_DIM}; margin-top: 4px; font-size: 0.9rem; }}
    .chart-section {{
      background: {_PAPER_BG};
      border: 1px solid {_GRID};
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
    }}
    .chart-title {{
      font-size: 1rem;
      font-weight: 600;
      color: {_DIM};
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 12px;
    }}
    footer {{
      text-align: center;
      color: {_DIM};
      font-size: 0.8rem;
      margin-top: 40px;
      padding-top: 16px;
      border-top: 1px solid {_GRID};
    }}
    footer a {{ color: {_BLUE}; text-decoration: none; }}
  </style>
</head>
<body>
  <header>
    <h1>{team_name} — {season} Season Dashboard</h1>
    <p>Data: MLB Stats API · Baseball Savant / Statcast &nbsp;|&nbsp;
       Built with <a href="https://github.com/cgarms/sox-tracker">sox-tracker</a></p>
  </header>

  {divs_html}

  <footer>
    <p>Generated by <a href="https://github.com/cgarms/sox-tracker">sox-tracker</a> &mdash;
    data via <a href="https://statsapi.mlb.com">MLB Stats API</a> &amp;
    <a href="https://baseballsavant.mlb.com">Baseball Savant</a></p>
  </footer>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# PNG exports
# ---------------------------------------------------------------------------

def build_png_exports(
    games: pd.DataFrame,
    batting: pd.DataFrame,
    pitching: pd.DataFrame,
    team_name: str,
    team_abbr: str = TEAM_ABBR,
    season: int = SEASON,
) -> list[Path]:
    """
    Export key charts as static PNGs for README previews.
    Requires kaleido: pip install kaleido
    """
    from analysis.offense import player_season_totals, hot_cold_summary
    from analysis.streaks import streak_timeline
    from viz.exports import save_png

    out_dir = OUTPUT_DIR / "img"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    exports = [
        ("timeline",    season_timeline(games, team_name),                   1200, 500),
        ("rolling_win", rolling_win_pct_chart(games, team_name),             1200, 450),
        ("run_diff",    run_differential_chart(games, team_name),            1200, 500),
        ("streak",      streak_timeline_chart(streak_timeline(games), team_name), 1200, 350),
    ]

    totals = player_season_totals(batting)
    if not totals.empty:
        exports.append(("batting_heatmap", batting_leaderboard_heatmap(totals, team_name),
                         1200, max(500, len(totals) * 30 + 100)))

    if not pitching.empty:
        exports.append(("rotation_heatmap", rotation_heatmap(pitching, team_name), 1200, 420))

    for name, fig, w, h in exports:
        path = out_dir / f"{team_abbr}_{season}_{name}.png"
        try:
            written.append(save_png(fig, path, width=w, height=h))
        except Exception as e:
            print(f"PNG export failed for {name}: {e} (is kaleido installed?)")

    return written
