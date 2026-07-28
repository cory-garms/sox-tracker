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
from data import odds_history, opponent
from analysis.matchup import fetch_doubleheader_previews, format_first_pitch
from analysis.betting import (
    EARLY_WIN_LIFT_2RUN,
    MARKET_H2H,
    MIN_MOVE_POINTS,
    MARKET_K,
    MARKET_TB,
    MAX_PLAUSIBLE_EDGE_K,
    MAX_PLAUSIBLE_EDGE_TB_PROB,
    MIN_CONSENSUS_BOOKS,
    MIN_STARTS_FOR_PROP,
    MODEL_ERROR_K,
    MODEL_ERROR_TB_PROB,
    batter_hr_rbi_props,
    batter_total_bases_model,
    biggest_movers,
    consensus_edge_table,
    fetch_book_lines,
    first_5_innings_analysis,
    nrfi_yrfi_tracker,
    pitcher_strikeout_model,
    probable_starters,
    promo_comparison,
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


def _short_time(raw: str | None) -> str:
    """"15:01 UTC" — enough to place a snapshot in the day without the noise."""
    if not raw:
        return "an earlier build"
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return "an earlier build"
    return stamp.astimezone(timezone.utc).strftime("%H:%M UTC")


def _pct(value) -> str:
    """
    A probability as "54.6%", or an em dash when there is none.

    None arrives as a float NaN once pandas has boxed a column, and "nan%" on
    the page reads as a broken number rather than an absent one.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return '<span class="no-line">&mdash;</span>'
    if number != number:                        # NaN
        return '<span class="no-line">&mdash;</span>'
    return f"{number * 100:.1f}%"


def _quote(line, odds) -> str:
    """A line and its price, as the book posts it: "4.5 (-137)"."""
    if line is None:
        return "—"
    price = f" ({odds:+d})" if isinstance(odds, (int, float)) and odds else ""
    return f"{float(line):.1f}{price}"


def _price(odds) -> str:
    """An American price on its own: "-125", "+148"."""
    try:
        return f"{int(odds):+d}"
    except (TypeError, ValueError):
        return "—"


def _quote_or_price(line, odds) -> str:
    """
    "4.5 (-137)" for a market with a number, "+148" for one without.

    A moneyline has no line, and passing that through _quote() renders an em
    dash — which would report a moneyline that moved from +148 to +158 as
    "— → —".
    """
    if line is None or line != line:              # None, or NaN out of parquet
        return _price(odds)
    return _quote(line, odds)


def _market_read(df, edge_fmt) -> str:
    """
    The priced rows written out in prose, above the table.

    A fourteen-column table on a 390px phone shows the first two columns and
    hides the line, both probabilities and the verdict behind a swipe — which
    is exactly the comparison the page exists to make. This says it in a
    sentence per quoted player, so the answer is visible without scrolling and
    the table stays there for the reader who wants the workings.
    """
    if df is None or df.empty or not df["has_line"].any():
        return ""

    items = []
    for _, r in df[df["has_line"]].iterrows():
        rec = r["recommendation"]
        if r.get("flagged"):
            rec_class = "review"
        elif "OVER" in rec:
            rec_class = "over"
        elif "UNDER" in rec:
            rec_class = "under"
        else:
            rec_class = "neu"
        items.append(
            f'<li><strong>{r["player_name"]}</strong> &nbsp;'
            f'<span class="prop-line">{_quote(r["prop_line"], _odds_int(r["american_odds"]))}</span>'
            f'<br>market <strong>{_pct(r["book_over_prob"])}</strong> over &nbsp;·&nbsp; '
            f'model <strong>{_pct(r["model_over_prob"])}</strong> &nbsp;·&nbsp; '
            f'{edge_fmt(r)} &nbsp; <span class="rec-badge {rec_class}">{rec}</span></li>'
        )
    return f'<ul class="market-read">{"".join(items)}</ul>'


def _odds_int(american) -> int | None:
    """"-154" back to -154; the frame carries it as a signed string for display."""
    try:
        return int(str(american))
    except (TypeError, ValueError):
        return None


def _movement_notes(history, event, names: list[str], market: str) -> str:
    """
    What the market has done since the first build that saw it.

    Says nothing at all until there are at least two snapshots of the same line,
    which is the state of every line on the day the history file is created.
    """
    if history is None or history.empty or not event or not names:
        return ""

    moved, watched, snapshots = [], 0, 0
    for name in names:
        mv = odds_history.line_movement(history, event.get("id", ""), market, name)
        if not mv:
            continue
        watched += 1
        snapshots = max(snapshots, mv["snapshots"])
        if mv["moved"]:
            moved.append(
                f"<strong>{name}</strong> "
                f"{_quote_or_price(mv['opened_line'], mv['opened_over_odds'])} at "
                f"{_short_time(mv['opened_at'])} &rarr; "
                f"{_quote_or_price(mv['current_line'], mv['current_over_odds'])}"
            )
    if moved:
        return ('<p class="table-note">📈 <strong>Line movement.</strong> '
                + " &nbsp;·&nbsp; ".join(moved)
                + " — every build's prices are logged, so this is measured "
                  "drift rather than an impression.</p>")
    if watched:
        subject = "line above has" if watched == 1 else f"{watched} lines above have"
        return ('<p class="table-note">📈 <strong>No line movement.</strong> '
                f'{snapshots} builds have logged this game, and the {subject} '
                'not moved between them.</p>')
    return ""


_MARKET_LABELS = {
    "pitcher_strikeouts": "Strikeouts",
    "batter_total_bases": "Total bases",
    "h2h": "Moneyline",
}


def _side_label(row) -> str:
    """
    "Over 5.5", or just "Moneyline" where there is no number to state.

    A moneyline carries a null line, and formatting that through :g raises
    rather than rendering — so the absence is handled here once instead of at
    each of the several call sites that print a selection.
    """
    line = row["line"]
    if line is None or line != line:             # None, or NaN once pandas boxes it
        return str(row["side"])
    return f"{row['side']} {float(line):g}"


def _movers_html(movers, snapshots: int = 0) -> str:
    """
    The handful of prices that actually moved, ranked.

    Placed first on the page because it is the only section whose value decays:
    a season rate is the same at noon and at first pitch, while "what has the
    market changed its mind about since this morning" is the one question a
    static page can answer that the book's own screen cannot.

    Movement is shown in de-vigged probability points rather than in odds. A
    move from -110 to -120 and one from +200 to +190 are similar as prices and
    very different as bets, so ranking on odds would sort the list by how long
    the prices happened to be rather than by how much anyone's opinion changed.
    """
    if movers is None or movers.empty:
        if snapshots < 2:
            return ('<p class="table-note"><strong>No movement to report yet.</strong> '
                    'This is the first snapshot of the game, and movement needs two. '
                    'The next scheduled build will have something to compare against.</p>')
        return (f'<p class="table-note"><strong>Nothing has moved.</strong> '
                f'{snapshots} snapshots of this game are logged and no price has '
                f'shifted by as much as {MIN_MOVE_POINTS:g} of a probability point. '
                'A quiet board is a real observation, not a missing one.</p>')

    top = movers.iloc[0]
    direction = "toward the over" if top["points"] > 0 else "away from the over"
    if top["line_moved"]:
        lead = (
            f"<strong>{top['player']}</strong> has had the line itself moved &mdash; "
            f"{top['open_line']:g} to {top['current_line']:g} &mdash; which is a "
            "different bet rather than the same bet repriced, and the clearest "
            "signal on this page that someone has changed their mind."
        )
    else:
        lead = (
            f"Biggest move: <strong>{top['player']}</strong> "
            f"{_price(top['open_price'])} &rarr; {_price(top['current_price'])}, "
            f"<strong>{abs(top['points']):.1f} points</strong> {direction} "
            f"since {_short_time(top['opened_at'])}."
        )

    rows = ""
    for _, r in movers.iterrows():
        cls = "delta-pos" if r["points"] > 0 else "delta-neg"
        arrow = "&#9650;" if r["points"] > 0 else "&#9660;"
        if r["line_moved"]:
            shown = (f"{r['open_line']:g} &rarr; {r['current_line']:g} "
                     '<span class="rec-badge review">LINE MOVED</span>')
        else:
            shown = f"{_price(r['open_price'])} &rarr; {_price(r['current_price'])}"
        rows += f"""
        <tr>
          <td>{r['player']}</td>
          <td>{shown}</td>
          <td class="{cls}">{arrow} {abs(r['points']):.1f} pts</td>
          <td>{_MARKET_LABELS.get(r['market'], r['market'])}</td>
        </tr>"""

    return f"""
    <p class="market-read">{lead}</p>
    <div class="table-scroll">
    <table class="report-table">
      <thead>
        <tr>
          <th>Selection</th>
          <th>Open &rarr; Now</th>
          <th>Shift</th>
          <th>Market</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    </div>
    <p class="table-note">Ranked across {snapshots} logged snapshots by change in
    <em>de-vigged</em> probability, so a book widening its margin does not appear
    as an opinion changing &mdash; a wider margin moves both sides and cancels.
    A selection missing from this list simply moved less than the ones on it;
    anything under {MIN_MOVE_POINTS:g} of a point is treated as churn. Line moves
    sort above price moves because they are a different bet, not a repricing.</p>"""


def _consensus_html(edges, boost_pct: float = 50.0, movement_html: str = "") -> str:
    """
    Render the primary book priced against the rest of the market.

    This is the only section on the page whose edge does not route through a
    model, so it is also the only one that can speak without clearing a model
    error bar. What it can still be wrong about is the benchmark: these are the
    US books The Odds API returns, which are retail books rather than the sharp
    limits a closing line is made of. A consensus of soft books is a better
    reference than one soft book, and worse than a real market.

    It covers both teams because the payload always did — the opposing starter
    and the opposing lineup cost nothing extra and were simply being discarded.
    """
    if edges is None or edges.empty:
        return (
            '<p class="table-note"><strong>No consensus available.</strong> Pricing a '
            "book against the market needs several books quoting the same number at "
            "the same time, and this build did not get that. Nothing is shown rather "
            "than comparing a price against itself.</p>"
        )

    best_ev = edges.iloc[0]
    best_boost = edges.sort_values("ev_boost_pct", ascending=False).iloc[0]

    if best_ev["ev_pct"] > 0:
        lead = (
            f"Best raw price: <strong>{best_ev['player']}</strong> "
            f"{_side_label(best_ev).lower()} at "
            f"{_price(best_ev['price'])} &mdash; the market's own fair number is "
            f"<strong>{best_ev['consensus_prob'] * 100:.1f}%</strong> across "
            f"{int(best_ev['n_books'])} other books, making it "
            f"<strong>{best_ev['ev_pct']:+.2f}%</strong>."
        )
    else:
        lead = (
            "<strong>No positive-EV price on the board.</strong> Every selection "
            "here is priced at or behind the consensus of the other books &mdash; "
            f"the closest is <strong>{best_ev['player']}</strong> "
            f"{_side_label(best_ev).lower()} at {_price(best_ev['price'])}, "
            f"{best_ev['ev_pct']:+.2f}%. That is the normal state of a liquid "
            "market and is what the vig looks like from the inside."
        )

    boost_note = (
        f"Under a {boost_pct:g}% profit boost the same board reads differently: "
        f"<strong>{best_boost['player']}</strong> "
        f"{_side_label(best_boost).lower()} at {_price(best_boost['price'])} becomes "
        f"<strong>{best_boost['ev_boost_pct']:+.2f}%</strong>. A boost multiplies "
        "profit rather than stake, so its value climbs as the price lengthens "
        "&mdash; which is why the boosted column does not rank the same way as the "
        "raw one."
    )

    # Column order is a mobile decision, not a cosmetic one. The first column is
    # sticky and a 390px phone shows roughly three more, so EV — the answer this
    # table exists to give — has to arrive before the workings that justify it.
    # Rendered at 390px it previously showed market, selection, side and price,
    # and hid every EV figure behind a swipe.
    rows = ""
    for _, r in edges.head(12).iterrows():
        ev_cls = "delta-pos" if r["ev_pct"] > 0 else "delta-neg"
        rows += f"""
        <tr>
          <td>{r['player']}</td>
          <td>{_side_label(r)}</td>
          <td>{_price(r['price'])}</td>
          <td class="{ev_cls}">{r['ev_pct']:+.2f}%</td>
          <td>{r['ev_boost_pct']:+.2f}%</td>
          <td>{r['consensus_prob'] * 100:.1f}%</td>
          <td>{int(r['n_books'])}</td>
          <td>{_MARKET_LABELS.get(r['market'], r['market'])}</td>
        </tr>"""

    trimmed = (
        f" Showing the {min(12, len(edges))} best of {len(edges)} priced selections."
        if len(edges) > 12 else ""
    )

    return f"""
    <p class="market-read">{lead}</p>
    <p class="market-read">{boost_note}</p>
    {movement_html}
    <p class="scroll-hint">&#8594; Swipe table to see all columns</p>
    <div class="table-scroll">
    <table class="report-table">
      <thead>
        <tr>
          <th>Selection</th>
          <th>Side</th>
          <th>{config.ODDS_BOOKMAKER.title()}</th>
          <th>EV</th>
          <th>EV w/ {boost_pct:g}% boost</th>
          <th>Consensus Fair %</th>
          <th>Books</th>
          <th>Market</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    </div>
    <p class="table-note">Each book is de-vigged on its own before the books are
    combined, and the book being priced is excluded from its own benchmark. Only
    books quoting the <em>same</em> number are compared, and a selection needs at
    least {MIN_CONSENSUS_BOOKS} others before it appears &mdash; two books agreeing
    is a coincidence as often as it is a price.{trimmed} The comparison books are retail
    US books, not sharp limits, so treat a small positive as noise rather than as
    an edge.</p>"""


def _promo_html(edges, event_book: dict | None) -> str:
    """
    Value the two promotion types against each other on the same selections.

    Promotions are the only positive expectation on this page that does not
    require a model to be right, which makes them worth computing precisely
    rather than by feel. Both are worth more on longer prices, so the ranking
    has to be recomputed per selection instead of settled once.
    """
    if edges is None or edges.empty:
        return (
            '<p class="table-note"><strong>No promotion maths available.</strong> '
            "Valuing a boost or a token needs a fair price to apply it to, and this "
            "build has no consensus to supply one.</p>"
        )

    rows = ""
    for _, r in edges.sort_values("ev_boost_pct", ascending=False).head(8).iterrows():
        promo = promo_comparison(r["consensus_prob"], r["price"])
        # An early-win token settles a *moneyline* early. It has nothing to
        # apply to on a strikeout or total-bases prop, so the column is left
        # empty there rather than quoting a number for a bet that cannot be
        # placed — the whole point of this section is to compare the two
        # promotions on offer, not to invent a third.
        is_ml = r["market"] == "h2h"
        token_cell = f"{promo['token_ev_pct']:+.2f}%" if is_ml else (
            '<span class="no-line">&mdash; n/a</span>'
        )
        if is_ml:
            better = "Boost" if promo["boost_ev_pct"] >= promo["token_ev_pct"] else "Token"
        else:
            better = "Boost only"
        rows += f"""
        <tr>
          <td>{r['player']}</td>
          <td>{_side_label(r)}</td>
          <td>{_price(r['price'])}</td>
          <td>{promo['raw_ev_pct']:+.2f}%</td>
          <td>{promo['boost_ev_pct']:+.2f}%</td>
          <td>{token_cell}</td>
          <td><strong>{better}</strong></td>
        </tr>"""

    return f"""
    <p class="market-read">A 50% profit boost pays
    <strong>1.5 &times; EV<sub>raw</sub> + 0.5 &times; (1 &minus; p)</strong> &mdash;
    so at a fair price it returns +25% on an even-money bet and +40% on a +400
    one. An early-win token instead adds a fixed
    <strong>{EARLY_WIN_LIFT_2RUN * 100:.1f} points</strong> of win probability,
    paid at those same odds. Both therefore prefer longer prices, and which one
    wins depends on the price rather than on the promotion. A boost is
    all-purpose and a token is not &mdash; the token can only settle a moneyline
    early, which is why most rows here have no token figure at all and why the
    boost's real advantage is the selections it can reach.</p>
    <p class="scroll-hint">&#8594; Swipe table to see all columns</p>
    <div class="table-scroll">
    <table class="report-table">
      <thead>
        <tr>
          <th>Selection</th>
          <th>Side</th>
          <th>Price</th>
          <th>EV raw</th>
          <th>EV + 50% boost</th>
          <th>EV + 2-run token</th>
          <th>Better</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    </div>
    <p class="table-note">The token lift is measured, not assumed:
    <code>scripts/measure_early_win_lift.py</code> walks half-inning linescores
    over 3,172 team-games of the 2026 season and finds
    P(ever led by 2+ <em>or</em> won) &minus; P(won) =
    <strong>{EARLY_WIN_LIFT_2RUN:+.4f}</strong>. It is stored as a lift rather
    than a rate because a team's own P(ever up 2) is anchored to the schedule it
    played and cannot be set against tonight's price. Token maths assumes the bet
    still settles normally when the trigger never happens &mdash; check the
    promotion's own terms, because that assumption is doing real work here.</p>"""


def _betting_css() -> str:
    """Styling shared by both betting pages. One copy, two consumers."""
    return f"""
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
    /* The model-vs-market read, for a phone that will not see column ten. */
    .market-read {{
      list-style: none; margin: 0 0 16px 0; padding: 0;
    }}
    .market-read li {{
      background: rgba(0,0,0,0.22);
      border-left: 3px solid {theme.BRASS};
      border-radius: 3px;
      padding: 10px 12px; margin-bottom: 8px;
      font-size: 0.88rem; line-height: 1.75;
    }}
    .market-read strong {{ font-family: {theme.FONT_MONO}; color: {theme.SCOREBOARD_GOLD}; }}
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
"""


def _shell(title: str, slug: str, heading: str, subtitle: str, sections: str) -> str:
    """
    The common document around either betting page.

    Both pages carry the same theme, nav and footer; only the heading and the
    sections differ. Keeping the shell here means a change to the chrome cannot
    land on one page and miss the other, which is the failure the five-way
    duplicated nav already demonstrated once.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">
  <title>{title}</title>
  <script data-goatcounter="https://cory-garms.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
  {theme.FONTS_LINK}
  <style>
    {theme.page_css()}
{_betting_css()}
  </style>
</head>
<body>
{theme.nav_bar(slug)}

  <header>
    <img src="images/sox_retro_logo.png" alt="Boston Red Sox Logo" class="team-logo">
    <div>
      <h1>{heading} <span class="badge">2026</span></h1>
      <p>{subtitle}</p>
    </div>
  </header>

{sections}

  <footer>
    <p>Generated by <a href="https://github.com/cory-garms/sox-tracker">sox-tracker</a> &mdash;
    Created by <a href="https://github.com/cory-garms">Cory Garms (@cory-garms)</a> &mdash;
    Data: MLB Stats API &amp; Baseball Savant</p>
  </footer>
</body>
</html>"""


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

    # One trip to the odds provider for the whole page — two credits, one for
    # each prop market — and every model prices off the same snapshot.
    book = fetch_book_lines(odds_client, team_id)
    event = book.get("event")

    # Write that snapshot down before rendering anything. A static page can only
    # ever show the market as of its last build; the log is what turns four
    # builds a day from a weakness into a record of how the line moved.
    for market in (MARKET_K, MARKET_TB, MARKET_H2H):
        odds_history.append_snapshot(
            odds_history.snapshot_rows(event, market, book.get(market, {}))
        )
    # Read it back afterwards so this build's own prices are the "now" end of
    # any movement the page reports.
    history = odds_history.load_history()

    # Run analytical models.
    #
    # The strikeout table covers whoever actually takes the mound today, not
    # every arm that has ever started — that swept in openers and long
    # relievers who will not pitch and have no prop line. A doubleheader
    # legitimately has two probables, so this is a list.
    probables = probable_starters(client, team_id, date_str)

    # First pitch is what makes the "lines as of" timestamp legible: a reader
    # needs both to judge how stale the odds on this page really are.
    try:
        previews = fetch_doubleheader_previews(client, team_id, date_str)
    except Exception:
        previews = []
    if len(previews) > 1:
        first_pitch = " · ".join(
            f"G{i}: {format_first_pitch(p)}" for i, p in enumerate(previews, start=1)
        )
    else:
        first_pitch = format_first_pitch(previews[0]) if previews else "TBD"
    # Who tonight's starter is facing. Falls back to no adjustment when the
    # league logs or the opponent cannot be resolved.
    opp_logs = opponent.load_team_hitting_logs(season, client=client)
    opp_id = None
    if previews:
        opp_id = (previews[0] or {}).get("opponent", {}).get("id")
    if opp_id is None and not games.empty and "opponent_id" in games.columns:
        opp_id = int(games.sort_values("game_date").iloc[-1]["opponent_id"])

    k_df = pitcher_strikeout_model(
        pitching, batting, games, client, book.get(MARKET_K, {}), team_id, season,
        opponent_logs=opp_logs, opponent_team_id=opp_id, as_of_date=date_str,
        # Deliberately a set even when empty: an unresolved probable must yield
        # an empty table the page can explain, never a fallback to the whole
        # rotation.
        only_player_ids={p["id"] for p in probables},
    )
    f5_res = first_5_innings_analysis(pitching, games, client, team_id, season, date_str)
    nrfi_res = nrfi_yrfi_tracker(games, pitching, client, team_id, season)
    tb_df = batter_total_bases_model(batting, book.get(MARKET_TB, {}), season)
    hr_df = batter_hr_rbi_props(batting, season)

    # The market priced against itself. This covers both teams — the opposing
    # starter and the opposing lineup arrive in the same payload at the same
    # cost and were previously parsed away.
    edges = consensus_edge_table(
        book.get("by_book", {}), primary_book=config.ODDS_BOOKMAKER
    )
    # The moneyline is where a promotion actually lands, so its drift belongs
    # in this section rather than only in the log.
    ml_movement = _movement_notes(
        history, event, list(book.get(MARKET_H2H, {}).keys()), MARKET_H2H
    )
    consensus_html = _consensus_html(edges, movement_html=ml_movement)

    # What changed since the last build. Ranked across every snapshot the log
    # holds for this event, not just the previous one.
    event_id = (event or {}).get("id", "")
    movers = biggest_movers(history, event_id, top_n=5)
    snapshot_count = (
        int(history[history["event_id"] == str(event_id)]["captured_at"].nunique())
        if history is not None and not history.empty and event_id else 0
    )
    movers_html = _movers_html(movers, snapshot_count)
    promo_html = _promo_html(edges, book.get("event"))

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
              <td>{_pct(r['book_over_prob'])}</td>
              <td><strong>{_pct(r['model_over_prob'])}</strong></td>
              <td>{edge_cell}</td>
              <td><span style="font-size: 0.8rem; font-weight: 600;">{src}</span></td>
              <td><span class="rec-badge {rec_class}">{rec}</span></td>
            </tr>
            """
    elif not probables:
        k_rows = (f'<tr><td colspan="12">No probable starter could be resolved for '
                  f'{date_str}. The table is left empty rather than falling back to '
                  f'the rest of the rotation.</td></tr>')
    else:
        listed = " and ".join(p["name"] for p in probables)
        k_rows = (f'<tr><td colspan="12">{listed} listed as probable, but has fewer '
                  f'than {MIN_STARTS_FOR_PROP} starts this season — too few for a '
                  f'projection worth publishing.</td></tr>')

    if probables:
        who = " and ".join(p["name"] for p in probables)
        starter_line_html = (
            f'<p class="table-note">Probable starter for {date_str}: '
            f"<strong>{who}</strong>. First pitch <strong>{first_pitch}</strong>.</p>"
        )
    else:
        starter_line_html = (
            f'<p class="table-note">No probable starter announced for {date_str}. '
            f"First pitch <strong>{first_pitch}</strong>.</p>"
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

    k_movement_html = _movement_notes(
        history, event, k_df["player_name"].tolist() if not k_df.empty else [], MARKET_K
    )

    if lines_live:
        k_note = (
            "<strong>Market %</strong> is the book's own price with the vig "
            "stripped out — what DraftKings really thinks the chance of the "
            "over is. <strong>Model %</strong> is this page's Poisson "
            "probability around its projection. Reading them side by side is "
            "the point of the table: it shows exactly where, and by how much, "
            "the model disagrees with the market. "
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

    k_read_html = _market_read(
        k_df, lambda r: f'gap <strong>{r["edge"]:+.2f} K</strong>')

    k_html = f"""
    {stamp_html}
    {k_read_html}
    {k_movement_html}
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
          <th>Market Over %</th>
          <th>Model Over %</th>
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

    # 2. Batter Total Bases HTML
    tb_rows = ""
    tb_quoted = []
    if not tb_df.empty:
        for _, r in tb_df.head(10).iterrows():
            rec = r["recommendation"]
            if r.get("flagged"):
                rec_class = "review"
            elif "OVER" in rec:
                rec_class = "over"
            elif "UNDER" in rec:
                rec_class = "under"
            else:
                rec_class = "neu"

            if r.get("has_line"):
                tb_quoted.append(r["player_name"])
                odds = r.get("american_odds") or "—"
                line_cell = f'<span class="prop-line">{r["prop_line"]:.1f}</span> ({odds})'
                edge = r["prob_edge"]
                edge_cell = ('<span class="no-line">—</span>' if edge is None
                             else f'<span class="edge-val">{edge * 100:+.1f}</span>')
            else:
                line_cell = '<span class="no-line">—</span>'
                edge_cell = '<span class="no-line">—</span>'

            tb_rows += f"""
            <tr>
              <td><strong>{r['player_name']}</strong></td>
              <td>{r['starts']}</td>
              <td>{r['season_avg']:.3f}</td>
              <td>{r['season_slg']:.3f}</td>
              <td>{r['tb_per_start']:.2f}</td>
              <td>{r['l10_tb_start']:.2f}</td>
              <td><span class="delta-pos">{r['l10_o15_tb_pct']:.1f}%</span></td>
              <td>{r['l10_1hit_pct']:.1f}%</td>
              <td><strong>{r['proj_tb']:.2f}</strong></td>
              <td>{line_cell}</td>
              <td>{_pct(r['book_over_prob'])}</td>
              <td><strong>{_pct(r['model_over_prob'])}</strong></td>
              <td>{edge_cell}</td>
              <td><span class="rec-badge {rec_class}">{rec}</span></td>
            </tr>
            """
    else:
        tb_rows = '<tr><td colspan="14">No batter total bases data available.</td></tr>'

    tb_lines_live = bool(not tb_df.empty and tb_df["has_line"].any())
    if tb_lines_live:
        tb_note = (
            "Lines are DraftKings' own, fetched with the strikeout market. "
            "<strong>Edge</strong> here is a difference in probability, not in "
            "bases: nearly every hitter is posted at 1.5, so what separates them "
            "is the price, and comparing a projection to the line would just rank "
            "hitters by quality the book has already charged for. "
            "<strong>This model does not call sides either.</strong> Its own "
            f"over-probability moves by &plusmn;{MODEL_ERROR_TB_PROB * 100:.1f} "
            "points when its inputs are resampled, and the entire spread of "
            "opinion it has been shown to hold out of sample is "
            f"{MAX_PLAUSIBLE_EDGE_TB_PROB * 100:.1f} points "
            "(walk-forward backtest, 714 held-out starts, AUC 0.57 against 0.50 "
            "for a coin flip). An edge has to be larger than the first and "
            "smaller than the second to mean anything, and almost nothing is. "
            "The honest reading of this table is the two probability columns "
            "side by side, not the last one."
        )
    else:
        tb_note = (
            "<strong>No total-bases lines connected.</strong> These are projections "
            "only. The table used to price them against an assumed 1.5 with "
            "hand-picked thresholds — a line no book had quoted and an edge nobody "
            "had measured. It now waits for a real line instead."
        )

    tb_movement_html = _movement_notes(history, event, tb_quoted, MARKET_TB)

    tb_read_html = _market_read(
        tb_df, lambda r: f'gap <strong>{r["prob_edge"] * 100:+.1f} pts</strong>')

    tb_html = f"""
    {tb_read_html}
    {tb_movement_html}
    <p class="scroll-hint">&#8594; Swipe table to see all columns</p>
    <div class="table-scroll">
    <table class="report-table">
      <thead>
        <tr>
          <th>Hitter</th>
          <th>Starts</th>
          <th>AVG</th>
          <th>SLG</th>
          <th>TB / Start</th>
          <th>L10 TB / Start</th>
          <th>L10 2+ TB %</th>
          <th>L10 1+ Hit %</th>
          <th>Proj TB</th>
          <th>Prop Line (Odds)</th>
          <th>Market Over %</th>
          <th>Model Over %</th>
          <th>Edge (pts)</th>
          <th>Recommendation</th>
        </tr>
      </thead>
      <tbody>
        {tb_rows}
      </tbody>
    </table>
    </div>
    <p class="table-note">{tb_note}</p>
    """

    # 3. Home Run, RBI & Runs — usage and form, no calls
    hr_rows = ""
    if not hr_df.empty:
        for _, r in hr_df.head(10).iterrows():
            hr_rows += f"""
            <tr>
              <td><strong>{r['player_name']}</strong></td>
              <td>{r['games']}</td>
              <td>{r['tot_hr']}</td>
              <td>{r['pa_per_hr']}</td>
              <td><strong>{r['l10_hr']}</strong></td>
              <td>{r['l10_rbi']}</td>
              <td><span class="delta-pos">{r['l10_rbi_hit_pct']:.1f}%</span></td>
              <td>{r['l10_r_hit_pct']:.1f}%</td>
            </tr>
            """
    else:
        hr_rows = '<tr><td colspan="8">No home run or RBI data available.</td></tr>'

    hr_html = f"""
    <p class="scroll-hint">&#8594; Swipe table to see all columns</p>
    <div class="table-scroll">
    <table class="report-table">
      <thead>
        <tr>
          <th>Hitter</th>
          <th>Games</th>
          <th>Season HR</th>
          <th>PA / HR</th>
          <th>L10 HR</th>
          <th>L10 RBI</th>
          <th>L10 1+ RBI %</th>
          <th>L10 1+ Run %</th>
        </tr>
      </thead>
      <tbody>
        {hr_rows}
      </tbody>
    </table>
    </div>
    <p class="table-note">Rate stats, not picks. This table used to end in a
    <em>HR Prop Target</em> badge of HIGH / MODERATE / LOW, keyed off thresholds
    — two homers in ten games, one per eighteen plate appearances — that nobody
    had measured, against a home-run line this page never fetched. The rates
    themselves are honest form and usage numbers, so they stayed; the verdict on
    top of them did not.</p>
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

    def _f5_runs(value) -> str:
        """An estimate, or a plain statement that there isn't one."""
        return "—" if value is None else f"{float(value):.2f}"

    matchup_card_html = ""
    if matchup_card := f5_matchup:
        total = matchup_card.get("f5_total_proj")
        total_html = (
            f"Estimated F5 Total Runs: <strong>{total:.2f}</strong>"
            if total is not None else
            "<strong>No F5 estimate.</strong> One of the two starters has no "
            "season ERA on record, and the total is not worth guessing at."
        )
        matchup_card_html = f"""
        <div class="matchup-banner">
          <h3>⚡ Today's F5 Starter Matchup Estimate</h3>
          <div class="matchup-grid">
            <div class="team-card">
              <div class="team-title">{team_abbr} Starter</div>
              <div class="pitcher-title">{matchup_card.get('our_starter')} ({matchup_card.get('our_hand')}HP)</div>
              <p>Season ERA: <strong>{matchup_card.get('our_era')}</strong> &nbsp;·&nbsp; WHIP: <strong>{matchup_card.get('our_whip')}</strong></p>
              <p>Est. Runs Allowed Thru 5: <strong style="color: #f85149;">{_f5_runs(matchup_card.get('our_f5_exp_runs'))}</strong></p>
            </div>
            <div class="vs-badge">VS</div>
            <div class="team-card">
              <div class="team-title">Opponent Starter</div>
              <div class="pitcher-title">{matchup_card.get('opp_starter')} ({matchup_card.get('opp_hand')}HP)</div>
              <p>Season ERA: <strong>{matchup_card.get('opp_era')}</strong> &nbsp;·&nbsp; WHIP: <strong>{matchup_card.get('opp_whip')}</strong></p>
              <p>Est. Runs Allowed Thru 5: <strong style="color: #f85149;">{_f5_runs(matchup_card.get('opp_f5_exp_runs'))}</strong></p>
            </div>
          </div>
          <div class="f5-total-bar">
            <span>{total_html}</span>
          </div>
        </div>
        <p class="table-note"><strong>An estimate, not a bet.</strong> This card
        used to call OVER or UNDER against a hardcoded 4.5 that no book had
        quoted, and it did so from full-start ERA divided down to five innings —
        not a measured first-five split, since the cached box scores carry no
        inning breakdown. Both halves of that call were made up, so the call is
        gone. A real F5 total would have to come from the book's own
        first-five market, and a projection worth pricing against it would need
        its error measured first, exactly as the strikeout and total-bases
        models now do.</p>"""

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

    # ------------------------------------------------------------------
    # Two pages, not one.
    #
    # The board is time-sensitive and the models are not. Tonight's prices are
    # stale within the hour and are read while deciding; the models and their
    # error bars are read once, argued with, and then trusted or not. Putting
    # them on one page meant scrolling past ~2,000px of measurement reasoning
    # every night to reach the four numbers that had changed since morning.
    # ------------------------------------------------------------------

    board_sections = f"""  <section class="card">
    <h2>&#128200; Biggest Line Moves &mdash; What the Market Changed Its Mind About</h2>
    {movers_html}
  </section>

  <section class="card">
    <h2>&#128202; Market Consensus &mdash; {config.ODDS_BOOKMAKER.title()} vs the Field</h2>
    {consensus_html}
  </section>

  <section class="card">
    <h2>&#127873; Promotion Value &mdash; Boost vs Early-Win Token</h2>
    {promo_html}
  </section>

  <section class="card">
    <h2>&#9918; Tonight's Quoted Props &mdash; At a Glance</h2>
    {starter_line_html}
    {k_read_html or '<p class="table-note">No strikeout line quoted for tonight.</p>'}
    {tb_read_html or '<p class="table-note">No total-bases lines quoted for tonight.</p>'}
    <p class="table-note">Every one of these reads <code>NO CALL</code> because
    both models measured their own error and found it as large as the entire
    spread of opinion they can demonstrate. The workings, the error bars and how
    they were measured are on
    <a href="{theme.PAGES['models'][0]}">Models &amp; Method</a>.</p>
  </section>"""

    models_sections = f"""  <section class="card">
    <h2>&#9918; Pitcher Strikeout Over/Under (O/U K's) &mdash; Today's Starter</h2>
    {starter_line_html}
    {k_html}
  </section>

  <section class="card">
    <h2>&#128165; Batter Total Bases (TB) &mdash; Model vs Market</h2>
    {tb_html}
  </section>

  <section class="card">
    <h2>&#128640; Home Run, RBI &amp; Runs &mdash; Usage and Form</h2>
    {hr_html}
  </section>

  <section class="card">
    <h2>&#9201; First 5 Innings (F5) Starter Matchup &amp; Performance Card</h2>
    {f5_html}
  </section>

  <section class="card">
    <h2>&#128683; NRFI / YRFI (No Run / Yes Run 1st Inning) Tracker</h2>
    {nrfi_html}
  </section>"""

    outputs = []
    for slug, title, heading, subtitle, sections in (
        ("board", f"{team_name} — Tonight's Board",
         "&#127922; Tonight's Board",
         "Line movement, the market priced against itself, and what a promotion "
         "is actually worth. Everything here is stale within the hour and says when "
         "it was read.",
         board_sections),
        ("models", f"{team_name} — Models &amp; Method",
         "&#128300; Models &amp; Method",
         "The projections behind the board, each published with the error bar it "
         "was measured against &mdash; and declining to call a side wherever that "
         "error is larger than the edge claimed.",
         models_sections),
    ):
        filename = theme.PAGES[slug][0]
        path = config.OUTPUT_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_shell(title, slug, heading, subtitle, sections), encoding="utf-8")
        print(f"Betting report generated successfully: {path}")
        outputs.append(path)

    # The old single-page URL is in the wild - it was linked from the suite
    # index for months. A stub costs nothing and keeps a bookmark working.
    legacy = config.OUTPUT_DIR / "betting_BOS_2026.html"
    legacy.write_text(
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "  <meta charset=\"UTF-8\">\n"
        f"  <meta http-equiv=\"refresh\" content=\"0; url={theme.PAGES['board'][0]}\">\n"
        "  <title>Redirecting to Tonight's Board</title>\n</head>\n<body>\n"
        f"  <p>The betting page is now split in two. Redirecting to "
        f"<a href=\"{theme.PAGES['board'][0]}\">Tonight's Board</a>.</p>\n"
        "</body>\n</html>\n",
        encoding="utf-8",
    )

    return outputs[0]


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
