"""
Team Stat Leaders HTML Exporter — generates interactive mobile-first HTML leaderboards
saved to docs/leaders_BOS_2026.html.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go

import config
from data.fetcher import Fetcher
from analysis.offense import player_season_totals


# ---------------------------------------------------------------------------
# Theme configuration
# ---------------------------------------------------------------------------
from viz import theme

_BG       = theme.PRESS_BOX
_PAPER_BG = theme.MONSTER_CARD
_GRID     = theme.TURF_GRID
_TEXT     = theme.PARCHMENT
_GREEN    = theme.WIN
_RED      = theme.LOSS
_YELLOW   = theme.SCOREBOARD_GOLD
_BLUE     = theme.NAVY_BLUE
_DIM      = theme.INK_MUTED

# Each leaderboard is its own single-series chart, so hues here carry no
# cross-chart identity — they cycle the validated categorical order for variety.
_PURPLE   = theme.NAVY_BLUE


def _apply_theme(fig: go.Figure, **extra) -> go.Figure:
    return theme.apply(fig, **extra)


def build_leader_bar_chart(
    df: pd.DataFrame,
    stat_col: str,
    title: str,
    stat_name: str,
    color: str = _BLUE,
    is_float: bool = False,
    top_n: int = 5,
    min_ab_ip: float = 0,
    filter_col: str | None = None,
    lowest_first: bool = False,
) -> go.Figure:
    """Build horizontal top-N leader bar chart."""
    data = df.copy()

    if filter_col and min_ab_ip > 0 and filter_col in data.columns:
        data = data[data[filter_col] >= min_ab_ip]

    if stat_col not in data.columns or data.empty:
        fig = go.Figure()
        _apply_theme(fig, title=dict(text=title))
        return fig

    # Sort top N (lowest or highest)
    if lowest_first:
        top_df = data.sort_values(stat_col, ascending=True).head(top_n).copy()
        top_df = top_df.sort_values(stat_col, ascending=False)  # descending so #1 (lowest) is at top of bar chart
    else:
        top_df = data.sort_values(stat_col, ascending=False).head(top_n).copy()
        top_df = top_df.sort_values(stat_col, ascending=True)   # ascending so #1 (highest) is at top of bar chart

    player_col = "player_name" if "player_name" in top_df.columns else "name"
    y_vals = top_df[player_col]
    x_vals = top_df[stat_col]

    if is_float:
        txt = [f"{v:.2f}" if "era" in stat_col or "whip" in stat_col else f"{v:.3f}" for v in x_vals]
    else:
        txt = [f"{int(v)}" if pd.notna(v) else "0" for v in x_vals]

    fig = go.Figure(go.Bar(
        y=y_vals,
        x=x_vals,
        orientation="h",
        marker_color=color,
        text=txt,
        textposition="inside",
        insidetextanchor="start",
        hovertemplate="%{y}: %{x} " + stat_name + "<extra></extra>",
    ))

    _apply_theme(fig,
        title=dict(text=title, font=dict(size=14, color=_TEXT)),
        xaxis_title=stat_name,
        yaxis_title="",
    )
    return fig


def generate_leaders_html(
    team_abbr: str = config.TEAM_ABBR,
    season: int = config.SEASON,
) -> Path:
    """Generate standalone mobile-optimized HTML team leaders report."""
    team_id = config.TEAMS.get(team_abbr, {}).get("id", config.TEAM_ID)
    team_name = config.TEAMS.get(team_abbr, {}).get("name", "Boston Red Sox")

    fetcher = Fetcher(team_id=team_id, season=season)
    batting = fetcher.load("batting")
    pitching = fetcher.load("pitching")

    # Aggregate Player Totals
    b_totals = player_season_totals(batting) if not batting.empty else pd.DataFrame()

    # Pitching Totals
    if not pitching.empty:
        win_col = "win" if "win" in pitching.columns else ("w" if "w" in pitching.columns else None)
        loss_col = "loss" if "loss" in pitching.columns else ("l" if "l" in pitching.columns else None)
        save_col = "save" if "save" in pitching.columns else ("sv" if "sv" in pitching.columns else None)

        p_agg = {}
        if win_col: p_agg["w"] = (win_col, "sum")
        if loss_col: p_agg["l"] = (loss_col, "sum")
        if save_col: p_agg["sv"] = (save_col, "sum")
        if "so" in pitching.columns: p_agg["so"] = ("so", "sum")
        if "ip_outs" in pitching.columns: p_agg["ip_outs"] = ("ip_outs", "sum")
        if "er" in pitching.columns: p_agg["er"] = ("er", "sum")
        if "h" in pitching.columns: p_agg["h"] = ("h", "sum")
        if "bb" in pitching.columns: p_agg["bb"] = ("bb", "sum")

        p_group = pitching.groupby(["player_id", "player_name"]).agg(**p_agg).reset_index()

        if "ip_outs" in p_group.columns:
            p_group["ip"] = p_group["ip_outs"] / 3
            p_group["era"] = p_group.apply(lambda r: round((r["er"] * 27) / r["ip_outs"], 2) if r["ip_outs"] > 0 else 0.0, axis=1)
            p_group["whip"] = p_group.apply(lambda r: round((r["h"] + r["bb"]) / (r["ip_outs"] / 3), 2) if r["ip_outs"] > 0 else 0.0, axis=1)
        else:
            p_group["ip"] = 0
            p_group["era"] = 0.0
            p_group["whip"] = 0.0

        p_totals = p_group
    else:
        p_totals = pd.DataFrame()

    # Offensive Charts
    fig_hr = build_leader_bar_chart(b_totals, "hr", "💣 Home Run Leaders", "Home Runs", color=_RED)
    fig_rbi = build_leader_bar_chart(b_totals, "rbi", "🏃 RBI Leaders", "RBIs", color=_YELLOW)
    fig_ops = build_leader_bar_chart(b_totals, "ops", "🎯 OPS Leaders (Min 80 AB)", "OPS", color=_GREEN, is_float=True, min_ab_ip=80, filter_col="ab")
    fig_avg = build_leader_bar_chart(b_totals, "avg", "📈 Batting Average (Min 80 AB)", "AVG", color=_BLUE, is_float=True, min_ab_ip=80, filter_col="ab")
    fig_sb = build_leader_bar_chart(b_totals, "sb", "💨 Stolen Base Leaders", "Stolen Bases", color=_PURPLE)

    # Pitching Charts
    fig_so = build_leader_bar_chart(p_totals, "so", "⚡ Strikeout Leaders", "Strikeouts", color=_BLUE)
    fig_w = build_leader_bar_chart(p_totals, "w", "🏆 Pitching Wins", "Wins", color=_GREEN)
    fig_sv = build_leader_bar_chart(p_totals, "sv", "🔒 Bullpen Saves", "Saves", color=_YELLOW)

    # ERA & WHIP (Lowest value is best - lowest_first=True)
    fig_era = build_leader_bar_chart(p_totals, "era", "🛡️ Lowest ERA (Min 15 IP)", "ERA", color=_GREEN, is_float=True, min_ab_ip=15, filter_col="ip", lowest_first=True)
    fig_whip = build_leader_bar_chart(p_totals, "whip", "🎯 Lowest WHIP (Min 15 IP)", "WHIP", color=_BLUE, is_float=True, min_ab_ip=15, filter_col="ip", lowest_first=True)

    import plotly.io as pio

    charts = [
        ("💣 Home Run Leaders", fig_hr),
        ("🏃 RBI Leaders", fig_rbi),
        ("🎯 OPS Leaders (Min 80 AB)", fig_ops),
        ("📈 Batting Average (Min 80 AB)", fig_avg),
        ("💨 Stolen Base Leaders", fig_sb),
        ("⚡ Strikeouts", fig_so),
        ("🛡️ Lowest ERA (Min 15 IP)", fig_era),
        ("🎯 Lowest WHIP (Min 15 IP)", fig_whip),
        ("🏆 Pitching Wins", fig_w),
        ("🔒 Bullpen Saves", fig_sv),
    ]

    cards_html = ""
    for i, (title, fig) in enumerate(charts):
        div_id = f"leader_chart_{i}"
        include_js = True if i == 0 else False
        fig.update_layout(
            height=320,
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
        c_div = pio.to_html(fig, full_html=False, include_plotlyjs=include_js, div_id=div_id,
                          config=theme.PLOTLY_CONFIG)
        cards_html += f"""
        <div class="chart-card">
          <h2>{title}</h2>
          {c_div}
        </div>
        """

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">
  <title>{team_name} — 2026 Team Stat Leaders</title>
  <script data-goatcounter="https://cory-garms.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
  {theme.FONTS_LINK}
  <style>
    {theme.page_css()}
    .grid-container {{
      display: grid;
      grid-template-columns: 1fr;
      gap: clamp(16px, 3vw, 26px);
    }}
  </style>
</head>
<body>
{theme.nav_bar('leaders')}

  <header>
    <img src="images/sox_retro_logo.png" alt="Boston Red Sox Logo" class="team-logo">
    <div>
      <h1>🥇 {team_name} — 2026 Team Stat Leaders <span class="badge">TOP 5 RANKINGS</span></h1>
      <p>Individual player rankings across major batting and pitching categories.</p>
    </div>
  </header>

  <main class="grid-container">
    {cards_html}
  </main>

  <footer>
    <p>Generated by <a href="https://github.com/cory-garms/sox-tracker">sox-tracker</a> &mdash;
    Created by <a href="https://github.com/cory-garms">Cory Garms (@cory-garms)</a> &mdash;
    Data: MLB Stats API &amp; Baseball Savant</p>
  </footer>

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

    output_path = config.OUTPUT_DIR / "leaders_BOS_2026.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_html, encoding="utf-8")
    print(f"Leaders report generated successfully: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate interactive HTML team leaders report.")
    parser.add_argument("--team", default=config.TEAM_ABBR, help="Team abbreviation (default: BOS)")
    parser.add_argument("--season", type=int, default=config.SEASON, help="Season (default: 2026)")
    args = parser.parse_args()

    generate_leaders_html(team_abbr=args.team, season=args.season)


if __name__ == "__main__":
    main()
