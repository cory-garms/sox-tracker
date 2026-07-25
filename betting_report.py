"""
Sports Betting & Prop Intelligence Exporter — generates interactive mobile-first HTML
betting report saved to docs/betting_BOS_2026.html.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path

import config
from viz import theme
from client.mlb_client import MLBClient
from client.odds_api_client import OddsAPIClient
from data.fetcher import Fetcher
from analysis.betting import (
    MAX_PLAUSIBLE_EDGE_K,
    MIN_STARTS_FOR_PROP,
    MODEL_ERROR_K,
    pitcher_strikeout_model,
    probable_starters,
    first_5_innings_analysis,
    nrfi_yrfi_tracker,
    batter_total_bases_model,
    batter_hr_rbi_props,
)


def _format_line_timestamp(raw: str | None) -> str | None:
    """
    Render a bookmaker's ISO-8601 `last_update` as "15:01 UTC on 25 Jul 2026".

    Returns None if the provider sent nothing parseable — an unlabelled line is
    better than a made-up timestamp.
    """
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(timezone.utc).strftime("%H:%M UTC on %d %b %Y")


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
    odds_client = OddsAPIClient(bookmaker=config.ODDS_BOOKMAKER)
    if not odds_client.configured:
        print("ODDS_API_KEY not set — building report with projections only "
              "(no book lines, no EV). See CONFIGURE.md.")
    fetcher = Fetcher(team_id=team_id, season=season, client=client, force_refresh=force_refresh)

    games = fetcher.load("games")
    batting = fetcher.load("batting")
    pitching = fetcher.load("pitching")

    # Run analytical models.
    #
    # The strikeout table covers whoever actually takes the mound today, not
    # every arm that has ever started — that swept in openers and long
    # relievers who will not pitch and have no prop line. A doubleheader
    # legitimately has two probables, so this is a list.
    probables = probable_starters(client, team_id, date_str)
    k_df = pitcher_strikeout_model(
        pitching, batting, games, client, odds_client, team_id, season,
        # Deliberately a set even when empty: an unresolved probable must yield
        # an empty table the page can explain, never a fallback to the whole
        # rotation.
        only_player_ids={p["id"] for p in probables},
    )
    f5_res = first_5_innings_analysis(pitching, games, client, team_id, season, date_str)
    nrfi_res = nrfi_yrfi_tracker(games, pitching, client, team_id, season)
    tb_df = batter_total_bases_model(batting, season)
    hr_df = batter_hr_rbi_props(batting, season)

    # 1. Pitcher Strikeout Model HTML
    k_rows = ""
    if not k_df.empty:
        for _, r in k_df.iterrows():
            rec = r["recommendation"]
            if r.get("flagged"):
                rec_class = "review"
            elif "OVER" in rec:
                rec_class = "over"
            elif "UNDER" in rec:
                rec_class = "under"
            else:
                rec_class = "neu"
            src = r.get("line_source", "No line available")

            # Line/edge cells only carry meaning when a book actually quoted one.
            if r.get("has_line"):
                odds = r.get("american_odds") or "—"
                line_cell = f'<span class="prop-line">{r["prop_line"]:.1f}</span> ({odds})'
                edge = r["edge"]
                edge_cell = f'<span class="edge-val">{"+" if edge > 0 else ""}{edge:.2f}</span>'
            else:
                line_cell = '<span class="no-line">—</span>'
                edge_cell = '<span class="no-line">—</span>'

            k_rows += f"""
            <tr>
              <td><strong>{r['player_name']}</strong></td>
              <td>{r['starts']}</td>
              <td>{r['season_k9']:.2f}</td>
              <td>{r['l5_k9']:.2f}</td>
              <td>{r['avg_ip_start']:.1f}</td>
              <td><strong>{r['proj_k']:.2f}</strong></td>
              <td>{line_cell}</td>
              <td>{edge_cell}</td>
              <td><span style="font-size: 0.8rem; font-weight: 600;">{src}</span></td>
              <td><span class="rec-badge {rec_class}">{rec}</span></td>
            </tr>
            """
    elif not probables:
        k_rows = (f'<tr><td colspan="10">No probable starter could be resolved for '
                  f'{date_str}. The table is left empty rather than falling back to '
                  f'the rest of the rotation.</td></tr>')
    else:
        listed = " and ".join(p["name"] for p in probables)
        k_rows = (f'<tr><td colspan="10">{listed} listed as probable, but has fewer '
                  f'than {MIN_STARTS_FOR_PROP} starts this season — too few for a '
                  f'projection worth publishing.</td></tr>')

    if probables:
        who = " and ".join(p["name"] for p in probables)
        starter_line_html = (
            f'<p class="table-note">Probable starter for {date_str}: '
            f"<strong>{who}</strong>.</p>"
        )
    else:
        starter_line_html = (
            f'<p class="table-note">No probable starter announced for {date_str}.</p>'
        )

    lines_live = bool(not k_df.empty and k_df["has_line"].any())

    # A GitHub Pages build serves a static file, so these odds are only ever as
    # fresh as the last build. Say which moment they came from rather than
    # letting the page imply they are live.
    stamp_html = ""
    if lines_live:
        stamps = [s for s in k_df["line_last_update"].tolist() if s]
        shown = _format_line_timestamp(max(stamps)) if stamps else None
        built = datetime.now(timezone.utc).strftime("%H:%M UTC on %d %b %Y")
        if shown:
            stamp_html = (
                f'<p class="table-note"><strong>Lines as of {shown}.</strong> '
                f"This page is a static build (generated {built}) — the odds "
                "above do not update after it is published. Re-check the book "
                "before acting on anything here.</p>"
            )
        else:
            stamp_html = (
                f'<p class="table-note"><strong>Line timestamp unavailable.</strong> '
                f"The book did not report when it last moved these prices; the page "
                f"itself was built {built}. Treat the odds as stale.</p>"
            )

    if lines_live:
        k_note = (
            "Edge is the model projection minus the sportsbook line. "
            f"<strong>This model does not currently call sides.</strong> Its own "
            f"measured error is &plusmn;{MODEL_ERROR_K:.2f} K per start — from a "
            "walk-forward backtest over the 2026 starts, after removing the "
            "irreducible scatter a perfect projection would still show. An edge "
            "smaller than that cannot be told apart from zero, and an edge larger "
            f"than {MAX_PLAUSIBLE_EDGE_K:.1f} K against a liquid market means the "
            "model is reporting its own bug, which the table marks "
            "<span class=\"rec-badge review\">REVIEW</span>. Those two limits "
            "nearly meet, which leaves no honest window to recommend from, so the "
            "table publishes the projection, the line, and the gap between them — "
            "and no bet. Restoring recommendations needs a sharper model, starting "
            "with the opponent strikeout-rate adjustment that has never been built; "
            "there is also no park or platoon context."
        )
    else:
        k_note = ("<strong>No sportsbook lines connected.</strong> These are model "
                  "projections only — no edge or EV can be computed without a real "
                  "line to compare against. Set <code>ODDS_API_KEY</code> to enable them.")

    k_html = f"""
    {stamp_html}
    <p class="scroll-hint">&#8594; Swipe table to see all columns</p>
    <div class="table-scroll">
    <table class="report-table">
      <thead>
        <tr>
          <th>Pitcher</th>
          <th>Starts</th>
          <th>Season K/9</th>
          <th>L5 K/9</th>
          <th>Proj IP</th>
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
    </div>
    <p class="table-note">{k_note}</p>
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
    <p class="scroll-hint">&#8594; Swipe table to see all columns</p>
    <div class="table-scroll">
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
    </div>
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
    <p class="scroll-hint">&#8594; Swipe table to see all columns</p>
    <div class="table-scroll">
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
    </div>
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
              <td>{r['era']:.2f}</td>
              <td>{r['whip']:.2f}</td>
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
              <p>Season ERA: <strong>{matchup_card.get('our_era')}</strong> &nbsp;·&nbsp; WHIP: <strong>{matchup_card.get('our_whip')}</strong></p>
              <p>Est. Runs Allowed Thru 5: <strong style="color: #f85149;">{matchup_card.get('our_f5_exp_runs')}</strong></p>
            </div>
            <div class="vs-badge">VS</div>
            <div class="team-card">
              <div class="team-title">Opponent Starter</div>
              <div class="pitcher-title">{matchup_card.get('opp_starter')} ({matchup_card.get('opp_hand')}HP)</div>
              <p>Season ERA: <strong>{matchup_card.get('opp_era')}</strong> &nbsp;·&nbsp; WHIP: <strong>{matchup_card.get('opp_whip')}</strong></p>
              <p>Est. Runs Allowed Thru 5: <strong style="color: #f85149;">{matchup_card.get('opp_f5_exp_runs')}</strong></p>
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
    <p class="scroll-hint">&#8594; Swipe table to see all columns</p>
    <div class="table-scroll">
    <table class="report-table" style="margin-top: 16px;">
      <thead>
        <tr>
          <th>Starter</th>
          <th>Starts</th>
          <th>Innings</th>
          <th>ERA</th>
          <th>WHIP</th>
          <th>K / 9</th>
          <th>Avg Game Score</th>
          <th>Est. ER Thru 5</th>
        </tr>
      </thead>
      <tbody>
        {f5_rows}
      </tbody>
    </table>
    </div>
    """

    # 5. NRFI / YRFI HTML
    if not nrfi_res.get("available"):
        nrfi_kpi = """
    <p class="table-note"><strong>First-inning data unavailable.</strong> NRFI rates are
    read from each game's linescore; none could be retrieved for this run. Rates are
    omitted rather than estimated from full-game scores.</p>
    """
    else:
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
    <p class="scroll-hint">&#8594; Swipe table to see all columns</p>
    <div class="table-scroll">
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
    </div>
    """

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">
  <title>{team_name} — Sports Betting & Prop Intelligence</title>
  <script data-goatcounter="https://cory-garms.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
  {theme.FONTS_LINK}
  <style>
    {theme.page_css()}
    .matchup-banner {{
      background:
        repeating-linear-gradient(90deg, rgba(0,0,0,0.14) 0 2px, rgba(0,0,0,0) 2px 46px),
        linear-gradient(135deg, {theme.MONSTER_DARK} 0%, #0b2b21 100%);
      border: 2px dashed {theme.BRASS};
      border-radius: 6px;
      padding: clamp(14px, 3vw, 24px);
      margin-bottom: 20px;
    }}
    .matchup-banner h3 {{
      font-family: {theme.FONT_STENCIL};
      font-size: clamp(0.82rem, 2vw, 0.98rem);
      font-weight: 400; color: {theme.SCOREBOARD_GOLD};
      text-transform: uppercase; letter-spacing: 0.1em;
      margin-bottom: 16px;
    }}
    .matchup-grid {{
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center; gap: 14px;
    }}
    .team-card {{
      background: rgba(0,0,0,0.28);
      border: 1px solid {theme.BRASS};
      border-radius: 4px;
      padding: 14px;
    }}
    .team-title {{
      font-family: {theme.FONT_STENCIL};
      font-size: 0.7rem; letter-spacing: 0.1em;
      text-transform: uppercase; color: {theme.INK_MUTED};
    }}
    .pitcher-title {{
      font-family: {theme.FONT_DISPLAY};
      font-size: clamp(0.95rem, 2.4vw, 1.15rem);
      color: {theme.PARCHMENT};
      margin: 6px 0 10px 0; line-height: 1.25;
    }}
    .team-card p {{ font-size: 0.86rem; line-height: 1.7; color: #cfe0d4; }}
    .team-card strong {{ font-family: {theme.FONT_MONO}; color: {theme.SCOREBOARD_GOLD}; }}
    .vs-badge {{
      font-family: {theme.FONT_DISPLAY};
      font-size: 1.25rem; color: {theme.FENWAY_CRIMSON};
    }}
    .f5-total-bar {{
      margin-top: 16px; padding-top: 14px;
      border-top: 1px solid {theme.BRASS};
      display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 10px;
      font-size: 0.92rem;
    }}
    @media (max-width: 600px) {{
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
    <h2>⚾ Pitcher Strikeout Over/Under (O/U K's) &mdash; Today's Starter</h2>
    {starter_line_html}
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
