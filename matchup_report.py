"""
Matchup Report HTML Exporter — generates interactive mobile-first HTML preview
for today's game / doubleheader saved to docs/matchup_BOS_2026.html.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import pandas as pd

import config
from client.mlb_client import MLBClient
from data.fetcher import Fetcher
from analysis.matchup import (
    fetch_doubleheader_previews,
    starter_season_summary,
    platoon_recommendations,
    bullpen_availability,
    head_to_head_summary,
)


def generate_matchup_html(
    team_abbr: str = config.TEAM_ABBR,
    season: int = config.SEASON,
    date_str: str | None = None,
    force_refresh: bool = False,
) -> Path:
    """Generate standalone mobile-optimized HTML matchup preview report."""
    if not date_str:
        date_str = date.today().strftime("%Y-%m-%d")

    team_id = config.TEAMS.get(team_abbr, {}).get("id", config.TEAM_ID)
    team_name = config.TEAMS.get(team_abbr, {}).get("name", "Boston Red Sox")

    client = MLBClient()
    fetcher = Fetcher(team_id=team_id, season=season, client=client, force_refresh=force_refresh)

    games = fetcher.load("games")
    batting = fetcher.load("batting")
    pitching = fetcher.load("pitching")

    previews = fetch_doubleheader_previews(client, team_id, date_str)

    if not previews:
        # Fallback to last played date if no games today
        if not games.empty:
            date_str = str(games[games["status"] == "Final"].iloc[-1]["game_date"])
            previews = fetch_doubleheader_previews(client, team_id, date_str)

    if not previews:
        p1 = {}
    else:
        p1 = previews[0]

    is_dh = len(previews) > 1
    opp_abbr = p1.get("opponent_abbr", "BAL")
    opp_id = p1.get("opponent_id", 110)
    opp_name = config.TEAMS.get(opp_abbr, {}).get("name", f"Team {opp_id}")
    is_home = p1.get("is_home", True)
    loc_str = "Fenway Park (Home)" if is_home else f"{p1.get('venue', 'Away')}"
    game_date = p1.get("game_date", date_str)

    # 1. Probable Starters HTML
    starters_html = ""
    if is_dh:
        p2 = previews[1]
        s1_our = starter_season_summary(client, p1.get("our_probable", {}).get("id"), season)
        s1_opp = starter_season_summary(client, p1.get("opp_probable", {}).get("id"), season)
        s2_our = starter_season_summary(client, p2.get("our_probable", {}).get("id"), season)
        s2_opp = starter_season_summary(client, p2.get("opp_probable", {}).get("id"), season)

        starters_html = f"""
        <table class="report-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>G1 {team_abbr}<br><span class="starter-name">{s1_our.get('name', 'TBD')}</span></th>
              <th>G1 {opp_abbr}<br><span class="starter-name">{s1_opp.get('name', 'TBD')}</span></th>
              <th>G2 {team_abbr}<br><span class="starter-name">{s2_our.get('name', 'TBD')}</span></th>
              <th>G2 {opp_abbr}<br><span class="starter-name">{s2_opp.get('name', 'TBD')}</span></th>
            </tr>
          </thead>
          <tbody>
            <tr><td>Throwing Hand</td><td>{s1_our.get('hand', 'R')}</td><td>{s1_opp.get('hand', 'R')}</td><td>{s2_our.get('hand', 'R')}</td><td>{s2_opp.get('hand', 'R')}</td></tr>
            <tr><td>Season W-L</td><td>{s1_our.get('w',0)}-{s1_our.get('l',0)}</td><td>{s1_opp.get('w',0)}-{s1_opp.get('l',0)}</td><td>{s2_our.get('w',0)}-{s2_our.get('l',0)}</td><td>{s2_opp.get('w',0)}-{s2_opp.get('l',0)}</td></tr>
            <tr><td>ERA</td><td>{s1_our.get('era','-')}</td><td>{s1_opp.get('era','-')}</td><td>{s2_our.get('era','-')}</td><td>{s2_opp.get('era','-')}</td></tr>
            <tr><td>WHIP</td><td>{s1_our.get('whip','-')}</td><td>{s1_opp.get('whip','-')}</td><td>{s2_our.get('whip','-')}</td><td>{s2_opp.get('whip','-')}</td></tr>
            <tr><td>K / 9</td><td>{s1_our.get('k9','-')}</td><td>{s1_opp.get('k9','-')}</td><td>{s2_our.get('k9','-')}</td><td>{s2_opp.get('k9','-')}</td></tr>
            <tr><td>BB / 9</td><td>{s1_our.get('bb9','-')}</td><td>{s1_opp.get('bb9','-')}</td><td>{s2_our.get('bb9','-')}</td><td>{s2_opp.get('bb9','-')}</td></tr>
            <tr><td>IP</td><td>{s1_our.get('ip',0)}</td><td>{s1_opp.get('ip',0)}</td><td>{s2_our.get('ip',0)}</td><td>{s2_opp.get('ip',0)}</td></tr>
          </tbody>
        </table>
        """
    else:
        our_prob = p1.get("our_probable", {})
        opp_prob = p1.get("opp_probable", {})
        s_our = starter_season_summary(client, our_prob.get("id"), season)
        s_opp = starter_season_summary(client, opp_prob.get("id"), season)

        starters_html = f"""
        <table class="report-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>{team_abbr} Starter<br><span class="starter-name">{s_our.get('name', 'TBD')}</span></th>
              <th>{opp_abbr} Starter<br><span class="starter-name">{s_opp.get('name', 'TBD')}</span></th>
            </tr>
          </thead>
          <tbody>
            <tr><td>Throwing Hand</td><td>{s_our.get('hand', 'R')}</td><td>{s_opp.get('hand', 'R')}</td></tr>
            <tr><td>Season W-L</td><td>{s_our.get('w',0)}-{s_our.get('l',0)}</td><td>{s_opp.get('w',0)}-{s_opp.get('l',0)}</td></tr>
            <tr><td>ERA</td><td>{s_our.get('era','-')}</td><td>{s_opp.get('era','-')}</td></tr>
            <tr><td>WHIP</td><td>{s_our.get('whip','-')}</td><td>{s_opp.get('whip','-')}</td></tr>
            <tr><td>K / 9</td><td>{s_our.get('k9','-')}</td><td>{s_opp.get('k9','-')}</td></tr>
            <tr><td>BB / 9</td><td>{s_our.get('bb9','-')}</td><td>{s_opp.get('bb9','-')}</td></tr>
            <tr><td>Innings Pitched</td><td>{s_our.get('ip',0)}</td><td>{s_opp.get('ip',0)}</td></tr>
          </tbody>
        </table>
        """

    # 2. Platoon Lineup Advantage HTML
    g1_opp_hand = starter_season_summary(client, p1.get("opp_probable", {}).get("id"), season).get("hand", "R")
    plat_df = platoon_recommendations(batting, g1_opp_hand, season)

    plat_rows = ""
    if not plat_df.empty:
        for _, r in plat_df.head(8).iterrows():
            delta = r['ops_delta']
            d_str = f"+{delta:.3f}" if delta >= 0 else f"{delta:.3f}"
            d_class = "pos" if delta >= 0.050 else ("neg" if delta <= -0.050 else "neu")
            plat_rows += f"""
            <tr>
              <td><strong>{r['player_name']}</strong></td>
              <td>{int(r['ab'])}</td>
              <td>{r['avg']:.3f}</td>
              <td>{r['obp']:.3f}</td>
              <td>{r['slg']:.3f}</td>
              <td><span class="highlight-ops">{r['ops']:.3f}</span></td>
              <td>{int(r['hr'])}</td>
              <td><span class="delta-{d_class}">{d_str}</span></td>
            </tr>
            """

    plat_html = f"""
    <table class="report-table">
      <thead>
        <tr>
          <th>Hitter</th>
          <th>AB</th>
          <th>AVG</th>
          <th>OBP</th>
          <th>SLG</th>
          <th>OPS</th>
          <th>HR</th>
          <th>Platoon Δ</th>
        </tr>
      </thead>
      <tbody>
        {plat_rows}
      </tbody>
    </table>
    """

    # 3. Bullpen Availability HTML
    bp_df = bullpen_availability(pitching, ref_date_str=date_str, days=3)
    bp_rows = ""
    if not bp_df.empty:
        for _, r in bp_df.iterrows():
            st = r['status']
            st_class = "fresh" if "FRESH" in st else ("mod" if "MODERATE" in st else "heavy")
            bp_rows += f"""
            <tr>
              <td><strong>{r['player_name']}</strong></td>
              <td>{r['d1_pitches']}</td>
              <td>{r['d2_pitches']}</td>
              <td>{r['d3_pitches']}</td>
              <td><strong>{r['tot_3d']}</strong></td>
              <td><span class="status-badge {st_class}">{st}</span></td>
            </tr>
            """

    bp_html = f"""
    <table class="report-table">
      <thead>
        <tr>
          <th>Reliever</th>
          <th>1-Day Ago</th>
          <th>2-Days Ago</th>
          <th>3-Days Ago</th>
          <th>3-Day Total</th>
          <th>Availability</th>
        </tr>
      </thead>
      <tbody>
        {bp_rows}
      </tbody>
    </table>
    """

    # 4. Head-to-Head HTML
    h2h = head_to_head_summary(games, opp_id)
    h2h_html = f"""
    <table class="report-table">
      <thead>
        <tr>
          <th>Games Played</th>
          <th>W - L</th>
          <th>Win%</th>
          <th>Runs Scored</th>
          <th>Runs Allowed</th>
          <th>Run Differential</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>{h2h['games_played']}</td>
          <td><strong style="color: #3fb950;">{h2h['wins']} - {h2h['losses']}</strong></td>
          <td>{h2h['win_pct']:.3f}</td>
          <td>{h2h['rs']}</td>
          <td>{h2h['ra']}</td>
          <td><strong style="color: #58a6ff;">{'+' if h2h['diff'] > 0 else ''}{h2h['diff']}</strong></td>
        </tr>
      </tbody>
    </table>
    """

    status_badge = '<span class="badge dh">⚡ SPLIT DOUBLEHEADER</span>' if is_dh else f'<span class="badge">{p1.get("status", "Scheduled")}</span>'

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">
  <title>{team_name} vs {opp_name} — Today's Pre-Game Matchup Preview</title>
  <script data-goatcounter="https://cory-garms.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      background: #0e1117;
      color: #e6edf3;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      min-height: 100vh;
      width: 100%;
      overflow-x: hidden;
    }}
    body {{
      padding: clamp(12px, 3vw, 28px);
    }}
    .nav-bar {{ margin-bottom: 16px; }}
    .nav-back {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: #58a6ff;
      text-decoration: none;
      font-weight: 600;
      font-size: 0.9rem;
      padding: 6px 12px;
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 8px;
    }}
    header {{
      border-bottom: 2px solid #3fb950;
      padding-bottom: 16px;
      margin-bottom: clamp(20px, 4vw, 32px);
    }}
    header h1 {{
      font-size: clamp(1.4rem, 4vw, 2.2rem);
      font-weight: 800;
      line-height: 1.25;
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
    }}
    header p {{
      color: #8b949e;
      margin-top: 6px;
      font-size: clamp(0.85rem, 2.5vw, 1.0rem);
    }}
    .badge {{
      background: #3fb950;
      color: #000000;
      font-weight: 800;
      font-size: clamp(0.75rem, 2vw, 0.85rem);
      padding: 4px 10px;
      border-radius: 12px;
    }}
    .badge.dh {{ background: #f85149; color: #ffffff; }}
    .card {{
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 12px;
      padding: clamp(14px, 3vw, 24px);
      margin-bottom: clamp(16px, 3vw, 24px);
      width: 100%;
      overflow-x: auto;
    }}
    .card h2 {{
      font-size: clamp(0.9rem, 2.2vw, 1.15rem);
      font-weight: 700;
      color: #58a6ff;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 16px;
    }}
    .report-table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: clamp(0.82rem, 2.2vw, 0.95rem);
    }}
    .report-table th, .report-table td {{
      padding: 10px 12px;
      border-bottom: 1px solid #30363d;
    }}
    .report-table th {{
      color: #8b949e;
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.78rem;
    }}
    .starter-name {{ color: #ffffff; font-weight: 700; font-size: 0.9rem; text-transform: none; }}
    .highlight-ops {{ color: #3fb950; font-weight: 700; }}
    .delta-pos {{ color: #3fb950; font-weight: 700; }}
    .delta-neg {{ color: #f85149; font-weight: 700; }}
    .delta-neu {{ color: #8b949e; }}
    .status-badge {{ font-size: 0.8rem; font-weight: 700; border-radius: 4px; padding: 2px 6px; }}
    .status-badge.fresh {{ background: rgba(63, 185, 80, 0.2); color: #3fb950; }}
    .status-badge.mod {{ background: rgba(210, 153, 34, 0.2); color: #d29922; }}
    .status-badge.heavy {{ background: rgba(248, 81, 73, 0.2); color: #f85149; }}
    footer {{
      text-align: center;
      color: #8b949e;
      font-size: 0.85rem;
      margin-top: 40px;
      padding-top: 16px;
      border-top: 1px solid #30363d;
    }}
    footer a {{ color: #58a6ff; text-decoration: none; }}

    @media (max-width: 600px) {{
      body {{ padding: 10px 8px; }}
      .card {{ padding: 10px 6px; border-radius: 8px; }}
      .report-table th, .report-table td {{ padding: 8px 6px; }}
    }}
  </style>
</head>
<body>
  <div class="nav-bar">
    <a href="index.html" class="nav-back">&larr; Back to Suite Index</a>
  </div>

  <header>
    <h1>⚾ {team_name} vs {opp_name} {status_badge}</h1>
    <p>Game Date: <strong>{game_date}</strong> &nbsp;·&nbsp; Venue: <strong>{loc_str}</strong> &nbsp;·&nbsp; Pre-Game Intelligence Report</p>
  </header>

  <section class="card">
    <h2>⚾ Probable Starters Comparison</h2>
    {starters_html}
  </section>

  <section class="card">
    <h2>💥 {team_abbr} Platoon Hitting Advantage (vs {g1_opp_hand}HP Pitching)</h2>
    {plat_html}
  </section>

  <section class="card">
    <h2>🛡️ {team_abbr} Bullpen Workload Capacity & Availability</h2>
    {bp_html}
  </section>

  <section class="card">
    <h2>📊 2026 Head-to-Head Series History vs {opp_abbr}</h2>
    {h2h_html}
  </section>

  <footer>
    <p>Generated by <a href="https://github.com/cory-garms/sox-tracker">sox-tracker</a> &mdash;
    Created by <a href="https://github.com/cory-garms">Cory Garms (@cory-garms)</a> &mdash;
    Data: MLB Stats API &amp; Baseball Savant</p>
  </footer>
</body>
</html>"""

    output_path = config.OUTPUT_DIR / "matchup_BOS_2026.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_html, encoding="utf-8")
    print(f"Matchup report generated successfully: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate interactive HTML matchup report.")
    parser.add_argument("--team", default=config.TEAM_ABBR, help="Team abbreviation (default: BOS)")
    parser.add_argument("--season", type=int, default=config.SEASON, help="Season (default: 2026)")
    parser.add_argument("--date", default=None, help="Game date YYYY-MM-DD (default: today)")
    parser.add_argument("--refresh", action="store_true", help="Force re-fetch cache")
    args = parser.parse_args()

    generate_matchup_html(
        team_abbr=args.team,
        season=args.season,
        date_str=args.date,
        force_refresh=args.refresh,
    )


if __name__ == "__main__":
    main()
