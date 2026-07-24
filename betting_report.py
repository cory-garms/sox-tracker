"""
Sports Betting & Prop Intelligence Exporter — generates interactive mobile-first HTML
betting report saved to docs/betting_BOS_2026.html.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import config
from client.mlb_client import MLBClient
from client.draftkings_client import DraftKingsClient
from data.fetcher import Fetcher
from analysis.betting import (
    pitcher_strikeout_model,
    first_5_innings_analysis,
    nrfi_yrfi_tracker,
    batter_total_bases_model,
    batter_hr_rbi_props,
)


def generate_betting_html(
    team_abbr: str = config.TEAM_ABBR,
    season: int = config.SEASON,
    date_str: str | None = None,
    force_refresh: bool = False,
) -> Path:
    """Generate standalone mobile-optimized HTML betting report."""
    if not date_str:
        date_str = date.today().strftime("%Y-%m-%d")

    team_id = config.TEAMS.get(team_abbr, {}).get("id", config.TEAM_ID)
    team_name = config.TEAMS.get(team_abbr, {}).get("name", "Boston Red Sox")

    client = MLBClient()
    dk_client = DraftKingsClient()
    fetcher = Fetcher(team_id=team_id, season=season, client=client, force_refresh=force_refresh)

    games = fetcher.load("games")
    batting = fetcher.load("batting")
    pitching = fetcher.load("pitching")

    # Run analytical models
    k_df = pitcher_strikeout_model(pitching, batting, games, client, dk_client, team_id, season)
    f5_res = first_5_innings_analysis(pitching, games, client, team_id, season, date_str)
    nrfi_res = nrfi_yrfi_tracker(games, pitching, client, team_id, season)
    tb_df = batter_total_bases_model(batting, season)
    hr_df = batter_hr_rbi_props(batting, season)

    # 1. Pitcher Strikeout Model HTML
    k_rows = ""
    if not k_df.empty:
        for _, r in k_df.iterrows():
            rec = r["recommendation"]
            rec_class = "over" if "OVER" in rec else ("under" if "UNDER" in rec else "neu")
            src = r.get("line_source", "Model Est. 🟡")
            odds = r.get("american_odds", "-115")
            k_rows += f"""
            <tr>
              <td><strong>{r['player_name']}</strong></td>
              <td>{r['starts']}</td>
              <td>{r['season_k9']:.2f}</td>
              <td>{r['l5_k9']:.2f}</td>
              <td>{r['avg_ip_start']:.1f}</td>
              <td><strong>{r['proj_k']:.2f}</strong></td>
              <td><span class="prop-line">{r['prop_line']:.1f}</span> ({odds})</td>
              <td><span class="edge-val">{'+' if r['edge'] > 0 else ''}{r['edge']:.2f}</span></td>
              <td><span style="font-size: 0.8rem; font-weight: 600;">{src}</span></td>
              <td><span class="rec-badge {rec_class}">{rec}</span></td>
            </tr>
            """
    else:
        k_rows = '<tr><td colspan="10">No starting pitcher data available.</td></tr>'

    k_html = f"""
    <table class="report-table">
      <thead>
        <tr>
          <th>Pitcher</th>
          <th>Starts</th>
          <th>Season K/9</th>
          <th>L5 K/9</th>
          <th>Avg IP</th>
          <th>Proj K's</th>
          <th>Prop Line (Odds)</th>
          <th>Edge</th>
          <th>Line Source</th>
          <th>Recommendation (+EV)</th>
        </tr>
      </thead>
      <tbody>
        {k_rows}
      </tbody>
    </table>
    """

    # 2. Batter Total Bases & 1+ Hit Model HTML
    tb_rows = ""
    if not tb_df.empty:
        for _, r in tb_df.head(10).iterrows():
            rec = r["recommendation"]
            rec_class = "over" if "OVER" in rec else ("under" if "UNDER" in rec else "neu")
            tb_rows += f"""
            <tr>
              <td><strong>{r['player_name']}</strong></td>
              <td>{r['games']}</td>
              <td>{r['season_avg']:.3f}</td>
              <td>{r['season_slg']:.3f}</td>
              <td>{r['season_tb_g']:.2f}</td>
              <td>{r['l10_tb_g']:.2f}</td>
              <td><span class="delta-pos">{r['l10_o15_tb_pct']:.1f}%</span></td>
              <td>{r['l10_1hit_pct']:.1f}%</td>
              <td><strong>{r['proj_tb']:.2f}</strong></td>
              <td><span class="rec-badge {rec_class}">{rec}</span></td>
            </tr>
            """
    else:
        tb_rows = '<tr><td colspan="10">No batter total bases data available.</td></tr>'

    tb_html = f"""
    <table class="report-table">
      <thead>
        <tr>
          <th>Hitter</th>
          <th>Games</th>
          <th>AVG</th>
          <th>SLG</th>
          <th>Season TB/G</th>
          <th>L10 TB/G</th>
          <th>L10 Over 1.5 TB %</th>
          <th>L10 1+ Hit %</th>
          <th>Proj TB</th>
          <th>Recommendation</th>
        </tr>
      </thead>
      <tbody>
        {tb_rows}
      </tbody>
    </table>
    """

    # 3. Home Run & RBI Prop Target HTML
    hr_rows = ""
    if not hr_df.empty:
        for _, r in hr_df.head(10).iterrows():
            rating = r["hr_rating"]
            rat_class = "over" if "HIGH" in rating else ("under" if "MODERATE" in rating else "neu")
            hr_rows += f"""
            <tr>
              <td><strong>{r['player_name']}</strong></td>
              <td>{r['tot_hr']}</td>
              <td>{r['pa_per_hr']}</td>
              <td><strong>{r['l10_hr']}</strong></td>
              <td>{r['l10_rbi']}</td>
              <td><span class="delta-pos">{r['l10_rbi_hit_pct']:.1f}%</span></td>
              <td>{r['l10_r_hit_pct']:.1f}%</td>
              <td><span class="rec-badge {rat_class}">{rating}</span></td>
            </tr>
            """
    else:
        hr_rows = '<tr><td colspan="8">No home run prop data available.</td></tr>'

    hr_html = f"""
    <table class="report-table">
      <thead>
        <tr>
          <th>Hitter</th>
          <th>Season HR</th>
          <th>PA / HR</th>
          <th>L10 HR</th>
          <th>L10 RBI</th>
          <th>L10 1+ RBI %</th>
          <th>L10 1+ Run %</th>
          <th>HR Prop Target</th>
        </tr>
      </thead>
      <tbody>
        {hr_rows}
      </tbody>
    </table>
    """

    # 4. First 5 Innings (F5) HTML
    f5_starters = f5_res.get("starters")
    f5_matchup = f5_res.get("matchup", {})

    f5_rows = ""
    if f5_starters is not None and not f5_starters.empty:
        for _, r in f5_starters.iterrows():
            f5_rows += f"""
            <tr>
              <td><strong>{r['player_name']}</strong></td>
              <td>{r['starts']}</td>
              <td>{r['tot_ip']:.1f}</td>
              <td>{r['f5_era']:.2f}</td>
              <td>{r['f5_whip']:.2f}</td>
              <td>{r['k9']:.2f}</td>
              <td>{r['avg_game_score']:.1f}</td>
              <td><strong style="color: #58a6ff;">{r['f5_exp_runs']:.2f}</strong></td>
            </tr>
            """
    else:
        f5_rows = '<tr><td colspan="8">No F5 starter data available.</td></tr>'

    matchup_card_html = ""
    if matchup_card := f5_matchup:
        matchup_card_html = f"""
        <div class="matchup-banner">
          <h3>⚡ Today's F5 Starter Matchup Projection</h3>
          <div class="matchup-grid">
            <div class="team-card">
              <div class="team-title">{team_abbr} Starter</div>
              <div class="pitcher-title">{matchup_card.get('our_starter')} ({matchup_card.get('our_hand')}HP)</div>
              <p>F5 ERA: <strong>{matchup_card.get('our_era')}</strong> &nbsp;·&nbsp; F5 WHIP: <strong>{matchup_card.get('our_whip')}</strong></p>
              <p>F5 Expected Runs Allowed: <strong style="color: #f85149;">{matchup_card.get('our_f5_exp_runs')}</strong></p>
            </div>
            <div class="vs-badge">VS</div>
            <div class="team-card">
              <div class="team-title">Opponent Starter</div>
              <div class="pitcher-title">{matchup_card.get('opp_starter')} ({matchup_card.get('opp_hand')}HP)</div>
              <p>F5 ERA: <strong>{matchup_card.get('opp_era')}</strong> &nbsp;·&nbsp; F5 WHIP: <strong>{matchup_card.get('opp_whip')}</strong></p>
              <p>F5 Expected Runs Allowed: <strong style="color: #f85149;">{matchup_card.get('opp_f5_exp_runs')}</strong></p>
            </div>
          </div>
          <div class="f5-total-bar">
            <span>Projected F5 Total Runs: <strong>{matchup_card.get('f5_total_proj')}</strong></span>
            <span class="rec-badge over">{matchup_card.get('f5_line_recommendation')}</span>
          </div>
        </div>
        """

    f5_html = f"""
    {matchup_card_html}
    <table class="report-table" style="margin-top: 16px;">
      <thead>
        <tr>
          <th>Starter</th>
          <th>Starts</th>
          <th>Innings</th>
          <th>F5 ERA</th>
          <th>F5 WHIP</th>
          <th>K / 9</th>
          <th>Avg Game Score</th>
          <th>F5 Exp ER / Game</th>
        </tr>
      </thead>
      <tbody>
        {f5_rows}
      </tbody>
    </table>
    """

    # 5. NRFI / YRFI HTML
    nrfi_kpi = f"""
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-value">{nrfi_res.get('nrfi_pct')}%</div>
        <div class="kpi-label">Season NRFI Rate ({nrfi_res.get('nrfi_count')}/{nrfi_res.get('total_games')})</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{nrfi_res.get('home_nrfi_pct')}%</div>
        <div class="kpi-label">Home Fenway NRFI %</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{nrfi_res.get('away_nrfi_pct')}%</div>
        <div class="kpi-label">Away Road NRFI %</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{nrfi_res.get('last_10_nrfi')}%</div>
        <div class="kpi-label">Last 10 Games NRFI %</div>
      </div>
    </div>
    """

    starter_nrfi_df = nrfi_res.get("starter_records")
    nrfi_rows = ""
    if starter_nrfi_df is not None and not starter_nrfi_df.empty:
        for _, r in starter_nrfi_df.iterrows():
            pct = r["nrfi_pct"]
            pct_class = "pos" if pct >= 65.0 else ("neg" if pct <= 45.0 else "neu")
            nrfi_rows += f"""
            <tr>
              <td><strong>{r['player_name']}</strong></td>
              <td>{r['starts']}</td>
              <td>{r['nrfi_count']}</td>
              <td>{r['yrfi_count']}</td>
              <td><strong>{r['nrfi_record']}</strong></td>
              <td><span class="delta-{pct_class}">{pct:.1f}%</span></td>
            </tr>
            """
    else:
        nrfi_rows = '<tr><td colspan="6">No starter NRFI records available.</td></tr>'

    nrfi_html = f"""
    {nrfi_kpi}
    <h3 style="color: #58a6ff; font-size: 1.0rem; margin: 20px 0 10px 0; text-transform: uppercase;">Red Sox Starting Pitcher NRFI Records</h3>
    <table class="report-table">
      <thead>
        <tr>
          <th>Starter</th>
          <th>Starts</th>
          <th>NRFI Clean (0 R)</th>
          <th>YRFI Runs (1+ R)</th>
          <th>NRFI Record</th>
          <th>NRFI Success %</th>
        </tr>
      </thead>
      <tbody>
        {nrfi_rows}
      </tbody>
    </table>
    """

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">
  <title>{team_name} — Sports Betting & Prop Intelligence</title>
  <script data-goatcounter="https://cory-garms.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      background: #0c1829;
      color: #f0f6fc;
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
      background: #14243b;
      border: 1px solid #243854;
      border-radius: 8px;
    }}
    header {{
      border-bottom: 2px solid #d22d36;
      padding-bottom: 16px;
      margin-bottom: clamp(20px, 4vw, 32px);
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    .team-logo {{
      height: clamp(48px, 10vw, 64px);
      width: auto;
      filter: drop-shadow(0 2px 8px rgba(0,0,0,0.4));
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
      color: #94a7b8;
      margin-top: 6px;
      font-size: clamp(0.85rem, 2.5vw, 1.0rem);
    }}
    .badge {{
      background: #d22d36;
      color: #ffffff;
      font-weight: 800;
      font-size: clamp(0.75rem, 2vw, 0.85rem);
      padding: 4px 10px;
      border-radius: 12px;
    }}
    .card {{
      background: #14243b;
      border: 1px solid #243854;
      border-radius: 12px;
      padding: clamp(14px, 3vw, 24px);
      margin-bottom: clamp(16px, 3vw, 24px);
      width: 100%;
      overflow-x: auto;
    }}
    .card h2 {{
      font-size: clamp(0.95rem, 2.2vw, 1.2rem);
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
    .prop-line {{
      background: #1f314d;
      color: #e6edf3;
      padding: 2px 8px;
      border-radius: 6px;
      font-weight: 700;
    }}
    .edge-val {{
      color: #3fb950;
      font-weight: 700;
    }}
    .rec-badge {{
      font-size: 0.8rem;
      font-weight: 700;
      border-radius: 6px;
      padding: 3px 8px;
    }}
    .rec-badge.over {{ background: rgba(63, 185, 80, 0.2); color: #3fb950; border: 1px solid #3fb950; }}
    .rec-badge.under {{ background: rgba(88, 166, 255, 0.2); color: #58a6ff; border: 1px solid #58a6ff; }}
    .rec-badge.neu {{ background: rgba(139, 148, 158, 0.2); color: #8b949e; border: 1px solid #8b949e; }}
    
    .matchup-banner {{
      background: #0f1c2e;
      border: 1px solid #1f3452;
      border-radius: 10px;
      padding: 16px;
      margin-bottom: 16px;
    }}
    .matchup-banner h3 {{
      color: #e6edf3;
      font-size: 1.05rem;
      margin-bottom: 12px;
    }}
    .matchup-grid {{
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      gap: 16px;
      align-items: center;
    }}
    .team-card {{
      background: #162842;
      padding: 12px;
      border-radius: 8px;
    }}
    .team-title {{ font-size: 0.8rem; color: #8b949e; text-transform: uppercase; font-weight: 700; }}
    .pitcher-title {{ font-size: 1.0rem; color: #ffffff; font-weight: 700; margin: 4px 0 8px 0; }}
    .vs-badge {{
      font-weight: 900;
      color: #d22d36;
      font-size: 1.2rem;
    }}
    .f5-total-bar {{
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid #243854;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px;
      font-size: 0.95rem;
    }}

    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .kpi-card {{
      background: #0f1c2e;
      border: 1px solid #1f3452;
      border-radius: 10px;
      padding: 14px;
      text-align: center;
    }}
    .kpi-value {{
      font-size: 1.6rem;
      font-weight: 800;
      color: #3fb950;
    }}
    .kpi-label {{
      font-size: 0.78rem;
      color: #8b949e;
      margin-top: 4px;
      font-weight: 600;
    }}
    .delta-pos {{ color: #3fb950; font-weight: 700; }}
    .delta-neg {{ color: #f85149; font-weight: 700; }}
    .delta-neu {{ color: #8b949e; }}

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
      .matchup-grid {{ grid-template-columns: 1fr; text-align: center; }}
      .vs-badge {{ margin: 4px 0; }}
    }}
  </style>
</head>
<body>
  <div class="nav-bar">
    <a href="index.html" class="nav-back">&larr; Back to Suite Index</a>
  </div>

  <header>
    <img src="images/sox_retro_logo.png" alt="Boston Red Sox Logo" class="team-logo">
    <div>
      <h1>🎲 Sports Betting &amp; Prop Intelligence <span class="badge">2026</span></h1>
      <p>Pre-game prop projections, First 5 Innings (F5) models, and NRFI/YRFI 1st-inning trend analytics</p>
    </div>
  </header>

  <section class="card">
    <h2>⚾ Pitcher Strikeout Over/Under (O/U K's) Prop Model</h2>
    {k_html}
  </section>

  <section class="card">
    <h2>💥 Batter Total Bases (TB) &amp; 1+ Hit Prop Intelligence</h2>
    {tb_html}
  </section>

  <section class="card">
    <h2>🚀 Home Run &amp; RBI Prop Target Leaderboard</h2>
    {hr_html}
  </section>

  <section class="card">
    <h2>⏱️ First 5 Innings (F5) Starter Matchup &amp; Performance Card</h2>
    {f5_html}
  </section>

  <section class="card">
    <h2>🚫 NRFI / YRFI (No Run / Yes Run 1st Inning) Tracker</h2>
    {nrfi_html}
  </section>

  <footer>
    <p>Generated by <a href="https://github.com/cory-garms/sox-tracker">sox-tracker</a> &mdash;
    Created by <a href="https://github.com/cory-garms">Cory Garms (@cory-garms)</a> &mdash;
    Data: MLB Stats API &amp; Baseball Savant</p>
  </footer>
</body>
</html>"""

    output_path = config.OUTPUT_DIR / "betting_BOS_2026.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_html, encoding="utf-8")
    print(f"Betting report generated successfully: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate interactive HTML betting report.")
    parser.add_argument("--team", default=config.TEAM_ABBR, help="Team abbreviation (default: BOS)")
    parser.add_argument("--season", type=int, default=config.SEASON, help="Season (default: 2026)")
    parser.add_argument("--date", default=None, help="Game date YYYY-MM-DD (default: today)")
    parser.add_argument("--refresh", action="store_true", help="Force re-fetch cache")
    args = parser.parse_args()

    generate_betting_html(
        team_abbr=args.team,
        season=args.season,
        date_str=args.date,
        force_refresh=args.refresh,
    )


if __name__ == "__main__":
    main()
