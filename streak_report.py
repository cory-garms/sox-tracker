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

from datetime import datetime

import config
from data.fetcher import Fetcher
from analysis.streaks import current_streak, longest_streak_games

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


def _apply_theme(fig: go.Figure, **extra) -> go.Figure:
    return theme.apply(fig, **extra)


# ---------------------------------------------------------------------------
# Chart 1: Milestone Thresholds (Season Best vs Historical Benchmarks)
# ---------------------------------------------------------------------------

def build_milestones_chart(streak_len: int, season: int = config.SEASON) -> go.Figure:
    # These are ordered thresholds, not independent categories, so the
    # benchmarks take a single-hue ramp (light -> dark by streak length) rather
    # than categorical hues. The Red Sox's own bar wears crimson to stand apart.
    # Axis labels stay short so they don't eat the plot area on a phone; the
    # full descriptor rides along in the hover instead.
    milestones = [
        {"name": f"{season} Red Sox", "detail": "Season best", "wins": streak_len, "ours": True},
        {"name": "1946 / 1906 Sox", "detail": "Red Sox franchise record", "wins": 15, "ours": False},
        {"name": "2001 SEA / 1926 NYY", "detail": "AL top-5", "wins": 16, "ours": False},
        {"name": "1947 Yankees", "detail": "AL top-3", "wins": 19, "ours": False},
        {"name": "2002 Athletics", "detail": "Moneyball streak", "wins": 20, "ours": False},
        {"name": "2017 Cleveland", "detail": "AL record", "wins": 22, "ours": False},
        {"name": "1916 NY Giants", "detail": "MLB record", "wins": 26, "ours": False},
    ]

    df = pd.DataFrame(milestones).sort_values("wins", ascending=True).reset_index(drop=True)
    benchmarks = df[~df["ours"]].reset_index(drop=True)
    ramp_pos = {name: i for i, name in enumerate(benchmarks["name"])}
    colors = [
        _RED if ours else theme.sequential(ramp_pos[name], len(benchmarks))
        for name, ours in zip(df["name"], df["ours"])
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=df["name"],
        x=df["wins"],
        orientation="h",
        marker_color=colors,
        text=[f"{w}" for w in df["wins"]],
        textposition="outside",
        cliponaxis=False,
        customdata=df["detail"],
        hovertemplate="%{y} — %{customdata}<br>Streak: %{x} wins<extra></extra>",
    ))

    # No in-chart title: the card heading above already names it, and dropping
    # it buys back vertical space and avoids the modebar on small screens.
    _apply_theme(fig,
        xaxis_title="Consecutive Wins",
        yaxis_title="",
        # Headroom past the longest bar (26) so the outside value labels have
        # somewhere to sit instead of clipping at the container edge.
        xaxis_range=[0, 32],
        margin=dict(l=10, r=30, t=30, b=50),
    )
    return fig


# ---------------------------------------------------------------------------
# Chart 2: Boston Red Sox All-Time Longest Win Streaks
# ---------------------------------------------------------------------------

def build_franchise_streaks_chart(
    streak_len: int,
    streak_note: str = "Season Best",
    season: int = config.SEASON,
) -> go.Figure:
    franchise_streaks = [
        {"season": "1946 Red Sox", "wins": 15, "note": "Ted Williams MVP Season (Franchise Record)", "active": False},
        {"season": "1906 Americans", "wins": 15, "note": "Early Franchise Record", "active": False},
        {"season": f"{season} Red Sox", "wins": streak_len, "note": streak_note, "active": True},
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
        # Bar-interior notes overflow a phone bar; show the count only and put
        # the descriptor in the hover.
        text=[f"{w} W" for w in df["wins"]],
        textposition="inside",
        insidetextanchor="start",
        customdata=df["note"],
        hovertemplate="%{y}: %{x} wins<br>%{customdata}<extra></extra>",
    ))

    _apply_theme(fig,
        xaxis_title="Consecutive Wins",
        xaxis_range=[0, 18],
        margin=dict(l=10, r=20, t=30, b=50),
    )
    return fig


# ---------------------------------------------------------------------------
# Chart 3: Streak Breakdown (Opponent, Date, Margin)
# ---------------------------------------------------------------------------

def build_streak_breakdown_chart(streak_games: pd.DataFrame) -> go.Figure:
    """Margin of victory for each game of the season's longest win streak.

    Takes the streak segment itself (see analysis.streaks.longest_streak_games)
    rather than slicing the tail of the schedule — once the streak ends, the
    final N games are no longer the streak.
    """
    if streak_games.empty:
        return go.Figure()

    # Map opponent_id to abbreviation
    id_to_abbr = {v["id"]: k for k, v in config.TEAMS.items()}

    streak_games = streak_games.copy()
    streak_games["opp_abbr"] = streak_games["opponent_id"].map(
        lambda oid: id_to_abbr.get(int(oid), str(int(oid))) if pd.notna(oid) else ""
    )

    # Differentiate doubleheader games on the same date (e.g. 2026-07-17 G1 / G2),
    # labelling from MLB's own gameNumber rather than row position.
    date_counts = streak_games["game_date"].value_counts()
    dup_dates = set(date_counts[date_counts > 1].index)
    has_game_number = "game_number" in streak_games.columns

    labels = []
    for i, (_, row) in enumerate(streak_games.iterrows(), start=1):
        d = row["game_date"]
        if d in dup_dates:
            gn = int(row["game_number"]) if has_game_number and pd.notna(row["game_number"]) else i
            labels.append(f"{d} G{gn}")
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
        xaxis_title="Game Date",
        yaxis_title="Margin of Victory (Runs)",
        yaxis_range=[0, max(streak_games["margin"]) + 4],
    )
    fig.update_xaxes(type="category")
    return fig


# ---------------------------------------------------------------------------
# HTML Dashboard Builder
# ---------------------------------------------------------------------------

_FRANCHISE_RECORD = 15  # 1946 / 1906 — longest win streak in Red Sox history


def _pretty_date(iso: str) -> str:
    """'2026-07-03' -> 'July 3'."""
    try:
        d = datetime.strptime(str(iso)[:10], "%Y-%m-%d")
    except ValueError:
        return str(iso)
    return f"{d.strftime('%B')} {d.day}"


def _short_date(iso: str) -> str:
    """'2026-07-03' -> 'Jul 3' — fits a stat tile on one line."""
    try:
        d = datetime.strptime(str(iso)[:10], "%Y-%m-%d")
    except ValueError:
        return str(iso)
    return f"{d.strftime('%b')} {d.day}"


def summarize_streak(streak_games: pd.DataFrame, season: int = config.SEASON) -> dict:
    """Commemorative facts about a win streak, derived entirely from the game log."""
    if streak_games.empty:
        return {}

    id_to_abbr = {v["id"]: k for k, v in config.TEAMS.items()}
    opponents = [
        id_to_abbr.get(int(o), str(int(o)))
        for o in streak_games["opponent_id"]
        if pd.notna(o)
    ]
    # Preserve first-faced order, drop repeats
    seen: list[str] = []
    for o in opponents:
        if o not in seen:
            seen.append(o)

    rs = int(streak_games["runs_scored"].sum())
    ra = int(streak_games["runs_allowed"].sum())
    n = len(streak_games)
    start, end = streak_games["game_date"].iloc[0], streak_games["game_date"].iloc[-1]

    return {
        "length": n,
        "start": start,
        "end": end,
        "date_range": f"{_pretty_date(start)} – {_pretty_date(end)}, {season}",
        "runs_scored": rs,
        "runs_allowed": ra,
        "run_diff": rs - ra,
        "avg_margin": round((rs - ra) / n, 1) if n else 0.0,
        "shutouts": int((streak_games["runs_allowed"] == 0).sum()),
        "one_run_wins": int(((streak_games["runs_scored"] - streak_games["runs_allowed"]) == 1).sum()),
        "opponents": seen,
        "ties_record": n >= _FRANCHISE_RECORD,
    }


def main() -> None:
    print("Building historical win streak visualization report...")
    fetcher = Fetcher(team_id=config.TEAM_ID, season=config.SEASON)
    games = fetcher.load("games")

    # The season's best win streak — a permanent fact, whether or not it's still running.
    streak_games = longest_streak_games(games, "W")
    streak_len = len(streak_games)
    facts = summarize_streak(streak_games, config.SEASON)

    st_type, active_w = current_streak(games)
    still_running = (st_type == "W" and active_w == streak_len and streak_len > 0)

    if not streak_len:
        print("No completed wins in the game log yet — nothing to report.")
        return

    streak_note = facts["date_range"] + (" (Active)" if still_running else "")
    fig1 = build_milestones_chart(streak_len, config.SEASON)
    fig2 = build_franchise_streaks_chart(streak_len, streak_note, config.SEASON)
    fig3 = build_streak_breakdown_chart(streak_games)

    badge_text = (
        f"TIED FRANCHISE RECORD &middot; W{streak_len}"
        if facts["ties_record"]
        else f"SEASON BEST &middot; W{streak_len}"
    )
    record_line = (
        "Tied the franchise record set by the 1946 and 1906 clubs."
        if facts["ties_record"]
        else f"The longest Red Sox win streak of the {config.SEASON} season."
    )
    status_line = "Still running." if still_running else "One for the books."

    tribute_stats = [
        (f"W{facts['length']}", "Consecutive Wins", ""),
        (f"{_short_date(facts['start'])} &ndash; {_short_date(facts['end'])}",
         f"When It Happened ({config.SEASON})", " compact"),
        (f"{facts['runs_scored']}&ndash;{facts['runs_allowed']}", "Runs For / Against", ""),
        (f"+{facts['run_diff']}", "Run Differential", ""),
        (f"+{facts['avg_margin']}", "Avg. Margin", ""),
        (str(facts["shutouts"]), "Shutouts Thrown", ""),
    ]
    tribute_cards = "\n".join(
        f'      <div class="stat-tile"><div class="stat-value{cls}">{v}</div>'
        f'<div class="stat-label">{lbl}</div></div>'
        for v, lbl, cls in tribute_stats
    )
    opponents_line = " &middot; ".join(facts["opponents"])

    import plotly.io as pio
    div1 = pio.to_html(fig1, full_html=False, include_plotlyjs=True, div_id="milestones_chart",
                       config=theme.PLOTLY_CONFIG)
    div2 = pio.to_html(fig2, full_html=False, include_plotlyjs=False, div_id="franchise_chart",
                       config=theme.PLOTLY_CONFIG)
    div3 = pio.to_html(fig3, full_html=False, include_plotlyjs=False, div_id="breakdown_chart",
                       config=theme.PLOTLY_CONFIG)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">
  <title>Boston Red Sox — The {facts['length']}-Game Win Streak ({config.SEASON})</title>
{theme.social_meta('streaks', f"Boston Red Sox — The {facts['length']}-Game Win Streak")}
{theme.analytics_tag()}
  {theme.FONTS_LINK}
  <style>
    {theme.page_css()}
    /* streak-page tribute banner */
    .tribute {{
      background:
        repeating-linear-gradient(90deg, rgba(0,0,0,0.14) 0 2px, rgba(0,0,0,0) 2px 46px),
        linear-gradient(135deg, {theme.MONSTER_DARK} 0%, #0b2b21 100%);
      border: 2px dashed {theme.BRASS};
      border-radius: 6px;
      padding: clamp(18px, 4vw, 34px);
      margin-bottom: clamp(16px, 3vw, 28px);
    }}
    .tribute-kicker {{
      display: inline-block; color: {theme.SCOREBOARD_GOLD};
      font-family: {theme.FONT_STENCIL};
      font-size: clamp(0.68rem, 1.8vw, 0.76rem);
      letter-spacing: 0.2em; text-transform: uppercase; margin-bottom: 10px;
    }}
    .tribute-title {{
      font-family: {theme.FONT_DISPLAY};
      font-size: clamp(2.1rem, 9vw, 3.6rem);
      font-weight: 400; line-height: 1; color: {theme.PARCHMENT};
      text-shadow: 0 3px 0 rgba(0,0,0,0.4);
    }}
    .tribute-sub {{
      color: #cfe0d4; margin-top: 12px; max-width: 62ch;
      font-size: clamp(0.88rem, 2.4vw, 1.02rem); line-height: 1.6;
    }}
    .stat-grid {{ margin-top: clamp(18px, 3vw, 26px); }}
  </style>
</head>
<body>
{theme.nav_bar('streaks')}
  <header>
    <img src="images/sox_retro_logo.png" alt="Boston Red Sox Logo" class="team-logo">
    <div>
      <h1>🏆 Boston Red Sox — The {facts['length']}-Game Win Streak <span class="badge">{badge_text}</span></h1>
      <p>{facts['date_range']} &nbsp;·&nbsp; {record_line} {status_line}</p>
    </div>
  </header>

  <section class="tribute">
    <div class="tribute-head">
      <span class="tribute-kicker">Season Highlight</span>
      <h2 class="tribute-title">{facts['length']} Straight</h2>
      <p class="tribute-sub">
        From {_pretty_date(facts['start'])} to {_pretty_date(facts['end'])}, the {config.SEASON} Red Sox
        won {facts['length']} in a row — outscoring {opponents_line} by {facts['run_diff']} runs.
      </p>
    </div>
    <div class="stat-grid">
{tribute_cards}
    </div>
  </section>

  <section class="chart-card">
    <h2>1. The Streak vs. Franchise &amp; League Milestone Benchmarks</h2>
    {div1}
  </section>

  <section class="chart-card">
    <h2>2. Red Sox Franchise History (Longest Win Streaks 1901–2026)</h2>
    {div2}
  </section>

  <section class="chart-card">
    <h2>3. Game-by-Game Breakdown of the Streak</h2>
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
