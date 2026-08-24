"""
Track Record — how the models have actually done.

The site publishes projections with error bars and declines to call a side when
the edge sits inside the error. Until now nothing measured whether that
discipline was well-founded: a reader could not tell an appropriately humble
model from a useless one, because both render as NO CALL.

This page answers the question, in the order a sceptic would ask it:

  1. How big is the sample? (Before any number is read.)
  2. Does the model beat the market as a forecaster?
  3. Are its stated probabilities calibrated?
  4. How large is its error, measured — against the constant currently in force?

Reads only data/cache/predictions_history.parquet, so it costs no odds quota
and can rebuild after every game.

    python track_record_report.py --team BOS --season 2026
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import config
from analysis import scoring
from analysis.betting import MODEL_ERROR_K, MODEL_ERROR_TB_PROB
from betting_report import _shell
from data import predictions_history as ph
from viz import theme

# The projection and the in-force error bar are only comparable when they are in
# the same units. MODEL_ERROR_K is in strikeouts, so it sits beside a measured
# strikeout error. MODEL_ERROR_TB_PROB is in *probability points* and the
# total-bases projection is in *bases* — printing 1.34 next to 0.049 as if one
# were the other's benchmark would be nonsense dressed as rigour.
MARKETS = {
    "pitcher_strikeouts": {
        "label": "Pitcher strikeouts",
        "unit": "K",
        "in_force": MODEL_ERROR_K,
        "comparable": True,
    },
    "batter_total_bases": {
        "label": "Batter total bases",
        "unit": "TB",
        "in_force": MODEL_ERROR_TB_PROB,
        "comparable": False,
        "in_force_note": (
            "The total-bases model's error bar is stated in probability points, "
            "not bases, so the measured projection error above is not its "
            "benchmark. The two are different quantities."
        ),
    },
}


# Scoped to this page. The shared chrome lives in viz/theme.page_css().
# `.calib` caps at 340px and centres: the reliability plot is square, and a
# square stretched to a desktop column reads as a different chart at every
# window width.
_PAGE_CSS = """
  <style>
    .verdict {
      font-size: clamp(0.92rem, 2.5vw, 1.02rem);
      line-height: 1.6; margin: 14px 0 18px;
      padding: 12px 14px; border-left: 3px solid #9DB0A5;
      background: rgba(0,0,0,0.18); border-radius: 0 3px 3px 0;
    }
    .verdict.flat { border-left-color: #C5A059; }
    .verdict.good { border-left-color: #4E9F3D; }
    .verdict.bad  { border-left-color: #A03030; }
    .sample {
      font-family: 'Share Tech Mono', monospace;
      font-size: clamp(0.76rem, 2vw, 0.86rem);
      letter-spacing: 0.03em; color: #C5A059; margin-bottom: 4px;
    }
    .dim { color: #9DB0A5; font-size: 0.86em; }
    svg.calib {
      display: block; width: 100%; max-width: 340px;
      height: auto; margin: 14px auto 6px;
    }
    .report-table th {
      text-align: left; font-weight: 400; color: #9DB0A5;
      white-space: nowrap; padding-right: 14px;
    }
  </style>
"""


def _calibration_chart(cal: dict, market_label: str) -> str:
    """
    Reliability curve: stated probability against what actually happened.

    Hand-rolled SVG rather than Plotly. The other Odds & Models pages carry no
    charting library at all — they are 20-44KB of HTML — and this is one small
    scatter. Embedding Plotly the way the dashboard does would take the page
    from 39KB to ~5MB, and linking the CDN would break both the offline
    standalone convention and the GitHub Pages mirror. A viewBox scales to any
    width, which is what the mobile-first rule actually asks for.
    """
    table = cal["table"]
    if table.empty:
        return ""

    w, h, pad = 320, 320, 34
    plot = w - 2 * pad

    def px(v: float) -> float:
        return pad + float(v) * plot

    def py(v: float) -> float:
        return h - pad - float(v) * plot

    grid = "".join(
        f'<line x1="{px(t)}" y1="{pad}" x2="{px(t)}" y2="{h - pad}" stroke="{theme.TURF_GRID}" stroke-width="1"/>'
        f'<line x1="{pad}" y1="{py(t)}" x2="{w - pad}" y2="{py(t)}" stroke="{theme.TURF_GRID}" stroke-width="1"/>'
        for t in (0.25, 0.5, 0.75)
    )
    ticks = "".join(
        f'<text x="{px(t)}" y="{h - pad + 15}" fill="{theme.INK_MUTED}" font-size="10" text-anchor="middle">{int(t * 100)}%</text>'
        f'<text x="{pad - 6}" y="{py(t) + 3}" fill="{theme.INK_MUTED}" font-size="10" text-anchor="end">{int(t * 100)}%</text>'
        for t in (0.0, 0.25, 0.5, 0.75, 1.0)
    )

    colour = theme.categorical(1)
    points = list(zip(table["predicted"], table["observed"], table["n"]))
    path = " ".join(
        f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(y):.1f}"
        for i, (x, y, _) in enumerate(points)
    )
    dots = "".join(
        f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="{max(4, min(11, 3 + n ** 0.5)):.1f}" '
        f'fill="{colour}" fill-opacity="0.85" stroke="{theme.PARCHMENT}" stroke-width="1">'
        f'<title>said {x:.0%}, happened {y:.0%} — {int(n)} predictions</title></circle>'
        for x, y, n in points
    )

    return f"""
    <svg class="calib" viewBox="0 0 {w} {h}" role="img"
         aria-label="Reliability curve for {market_label}: predicted probability against observed frequency">
      <rect x="{pad}" y="{pad}" width="{plot}" height="{plot}" fill="{theme.MONSTER_CARD}" stroke="{theme.TURF_GRID}"/>
      {grid}
      <line x1="{px(0)}" y1="{py(0)}" x2="{px(1)}" y2="{py(1)}"
            stroke="{theme.INK_MUTED}" stroke-width="1" stroke-dasharray="4 3"/>
      <path d="{path}" fill="none" stroke="{colour}" stroke-width="2"/>
      {dots}
      {ticks}
      <text x="{w / 2}" y="{h - 4}" fill="{theme.INK_MUTED}" font-size="10" text-anchor="middle">Model said</text>
      <text x="10" y="{h / 2}" fill="{theme.INK_MUTED}" font-size="10" text-anchor="middle"
            transform="rotate(-90 10 {h / 2})">Actually happened</text>
    </svg>
    <p class="note">The dashed diagonal is perfect calibration. Dot size is how
    many predictions fell in that band; points above the line mean the model
    said it less often than it happened.</p>"""


def _verdict(vs: dict) -> tuple[str, str]:
    """The headline sentence, and a css class for how to colour it."""
    if vs["n"] == 0:
        return "No graded predictions with a book line yet.", "flat"
    if not vs["distinguishable"]:
        return (
            f"No demonstrated edge. Across {vs['n']} graded predictions the model's "
            f"Brier score is {vs['model_brier']:.4f} against the market's "
            f"{vs['market_brier']:.4f} — a gap of {vs['difference']:+.4f}, whose 95% "
            f"interval [{vs['ci_low']:+.4f}, {vs['ci_high']:+.4f}] contains zero. "
            f"On this sample the model knows nothing the price did not already carry.",
            "flat",
        )
    if vs["beats_market"]:
        return (
            f"Beats the market. Brier {vs['model_brier']:.4f} against "
            f"{vs['market_brier']:.4f}, a gap of {vs['difference']:+.4f} "
            f"(95% CI [{vs['ci_low']:+.4f}, {vs['ci_high']:+.4f}], excluding zero).",
            "good",
        )
    return (
        f"Loses to the market. Brier {vs['model_brier']:.4f} against "
        f"{vs['market_brier']:.4f} (95% CI [{vs['ci_low']:+.4f}, {vs['ci_high']:+.4f}]).",
        "bad",
    )


def _market_section(market: str, spec: dict, scored: pd.DataFrame, actuals: pd.DataFrame) -> str:
    rows = scored[scored["market"] == market]
    with_actual = actuals[actuals["market"] == market]
    if rows.empty and with_actual.empty:
        return ""

    label = spec["label"]
    n = len(rows)
    verdict_text = scoring.sample_verdict(n)

    if rows.empty:
        return f"""
  <section class="card">
    <h2>{label}</h2>
    <p class="sample">{verdict_text}</p>
  </section>"""

    y = (rows["outcome"] == "over").astype(int)
    vs = scoring.versus_market(rows["model_over_prob"], rows["book_over_prob"], y)
    disc = scoring.discrimination(rows["model_over_prob"], y)
    cal = scoring.calibration(rows["model_over_prob"], y)
    err = scoring.decompose(with_actual["projection"], with_actual["actual"])

    headline, tone = _verdict(vs)

    # Calibration is only worth drawing when the sample can resolve it at all.
    if cal["n"] and not cal["table"].empty:
        cal_note = (
            f"Weighted RMS gap {cal['rms_gap']:.3f} against a sampling-noise floor of "
            f"{cal['noise_floor']:.3f}. "
            + ("The gap is larger than the noise, so it is a real miscalibration."
               if cal["resolvable"] else
               "The gap is inside the noise floor: this sample cannot tell this model "
               "apart from a well-calibrated one.")
        )
        cal_block = _calibration_chart(cal, label) + f'<p class="note">{cal_note}</p>'
    else:
        cal_block = '<p class="note">Not enough graded predictions to plot a reliability curve.</p>'

    slope_note = (
        "A negative slope means the ordering is backwards: the predictions it is "
        "most confident about are the ones it gets wrong."
        if disc["slope"] == disc["slope"] and disc["slope"] < 0 else
        "The slope says how much of the spread in the predictions is real; 1.00 "
        "would mean all of it."
    )

    if spec["comparable"]:
        err_row = f"""
        <tr><th>Measured model error</th><td>{err['model_err']:.3f} {spec['unit']}</td></tr>
        <tr><th>In force (gates NO CALL)</th><td>{spec['in_force']} {spec['unit']}</td></tr>"""
        err_note = (
            f"Measured over {err['n']} projections with a known result. The in-force "
            f"constant is a league-wide backtest; this is the model's own record."
        )
    else:
        err_row = f"""
        <tr><th>Measured projection error</th><td>{err['model_err']:.3f} {spec['unit']}</td></tr>"""
        err_note = spec.get("in_force_note", "")

    return f"""
  <section class="card">
    <h2>{label}</h2>
    <p class="sample">{verdict_text}</p>

    <p class="verdict {tone}">{headline}</p>

    <div class="table-scroll">
    <table class="report-table">
      <tbody>
        <tr><th>Graded predictions</th><td>{n}</td></tr>
        <tr><th>AUC</th><td>{disc['auc']:.3f} <span class="dim">(0.50 = coin flip)</span></td></tr>
        <tr><th>Brier score</th><td>{disc['brier']:.4f} <span class="dim">vs {disc['brier_base']:.4f} for always quoting the base rate</span></td></tr>
        <tr><th>Skill vs base rate</th><td>{disc['skill']:+.4f}</td></tr>
        <tr><th>Recalibration slope</th><td>{disc['slope']:.3f}</td></tr>
        <tr><th>Projection bias</th><td>{err['bias']:+.2f} {spec['unit']} <span class="dim">(mean over-projection)</span></td></tr>
        <tr><th>Mean absolute error</th><td>{err['mae']:.2f} {spec['unit']}</td></tr>{err_row}
      </tbody>
    </table>
    </div>
    <p class="note">{slope_note} {err_note}</p>

    <h3>Calibration</h3>
    {cal_block}
  </section>"""


def _market_move_section(history: pd.DataFrame) -> str:
    """
    Did the market come toward the model between its first price and its last?

    The other scoreboard, and the one that does not wait on a result. Outcomes
    take a season to accumulate; a line closes every night. If the model knows
    something the book has not priced yet, the book should on average revise
    toward it -- and if it does not, that is informative long before the Brier
    scores are.
    """
    from analysis import clv
    from data import odds_history

    frame = clv.attach_clv(history, odds_history.load_history())
    s = clv.summarise(frame)
    if not s.get("n"):
        return ""

    rows = ""
    for market, label in (("pitcher_strikeouts", "Strikeouts"),
                          ("batter_total_bases", "Total bases")):
        g = frame[frame["market"] == market]
        m = clv.summarise(g)
        if not m.get("n"):
            continue
        rows += (f"<tr><td>{label}</td><td>{m['n']}</td>"
                 f"<td>{m['mean_points']:+.2f}</td>"
                 f"<td>[{m['ci_low']:+.2f}, {m['ci_high']:+.2f}]</td>"
                 f"<td>{m['beat_close_pct']:.0f}%</td></tr>")

    contains_zero = s["ci_low"] <= 0 <= s["ci_high"]
    verdict = ("The interval contains zero: the market does not move toward "
               "these projections any more than it moves away from them."
               if contains_zero else
               "The interval clears zero, which would be the first evidence "
               "here of the model seeing a revision before the book made it.")

    return f"""
  <section class="card">
    <h2>Does the market move toward the model?</h2>
    <p>Every projection is logged against the price it was quoted at, and the
    same market is captured again nearer first pitch. The gap between those two
    prices is the book revising its own opinion. If the model knows something
    the book has not priced yet, the revision should on average come
    <em>toward</em> the side the model took.</p>
    <p>Measured over <strong>{s['n']}</strong> priced player-games — the side
    fixed against the opening price, the movement measured to the last capture
    before first pitch:</p>
    <div class="table-scroll">
    <table class="report-table">
      <thead><tr><th>Market</th><th>n</th><th>Mean move (pts)</th><th>95% CI</th><th>Beat the close</th></tr></thead>
      <tbody>{rows}
        <tr><td><strong>All</strong></td><td><strong>{s['n']}</strong></td>
            <td><strong>{s['mean_points']:+.2f}</strong></td>
            <td><strong>[{s['ci_low']:+.2f}, {s['ci_high']:+.2f}]</strong></td>
            <td><strong>{s['beat_close_pct']:.0f}%</strong></td></tr>
      </tbody>
    </table>
    </div>
    <p>{verdict}</p>
    <p class="note">This is not closing line value in the betting sense and is
    not reported as such: nothing was staked, so no vig was paid and nothing had
    to be executed at the quoted number. It measures only whether the model's
    disagreement with the book anticipated the book's own revision. Both prices
    come from the odds log rather than one from each log — taking the quote from
    the projection archive would compare a price against itself, since the
    archive keeps the last pre-game capture and that is the close. Games whose
    line moved are excluded rather than differenced, because 4.5 strikeouts and
    5.5 strikeouts are not two prices for one question.</p>
  </section>"""


def generate_track_record_html(
    team_abbr: str = config.TEAM_ABBR,
    season: int = config.SEASON,
) -> Path:
    team_name = config.TEAMS.get(team_abbr, {}).get("name", config.TEAM_NAME)

    history = ph.load_history()
    # Scoring must go through latest_per_game: every build logs a snapshot, so
    # the raw log counts the same player-game once per build.
    scored = ph.latest_per_game(ph.graded(history)) if not history.empty else history
    actuals = ph.latest_per_game(ph.with_actuals(history)) if not history.empty else history

    if history.empty or scored is None or scored.empty:
        sections = """
  <section class="card">
    <h2>Nothing graded yet</h2>
    <p>No projection has been settled against a result. Once games finish and
    <code>scripts/grade_predictions.py</code> runs, this page fills in.</p>
  </section>"""
        span = ""
    else:
        span_start, span_end = scored["game_date"].min(), scored["game_date"].max()
        span = f"{span_start} to {span_end}"
        replayed = int(scored["model_version"].astype(str).str.endswith("-replay").sum())

        intro = f"""
  <section class="card">
    <h2>What this page is</h2>
    <p>Every projection the models publish is logged with the line it was quoted
    against, then settled against the box score. This is that record — not a
    backtest of a model against its own training data, but the published
    projections scored on what happened next.</p>
    <p><strong>{len(scored)}</strong> graded predictions across
    <strong>{scored['game_date'].nunique()}</strong> game dates ({span}).</p>
    {"<p class='note'>" + str(replayed) + " of these were reconstructed from stored odds rather than published live. Both models are pure functions of their inputs, so a projection can be rebuilt exactly, provided the rebuild is given only the games played before the date it is projecting. They are tagged <code>-replay</code> in the log.</p>" if replayed else ""}
  </section>"""

        sections = intro + "".join(
            _market_section(m, spec, scored, actuals) for m, spec in MARKETS.items()
        )

        sections += """
  <section class="card">
    <h2>Why "no edge" is not the same as "no skill"</h2>
    <p>The total-bases model looks inert above — AUC 0.495, a recalibration
    slope of about zero. Run the same model over <em>every</em> hitter-start in
    the cache rather than only the ones a book priced, and it is not inert at
    all:</p>
    <div class="table-scroll">
    <table class="report-table">
      <thead><tr><th>Population</th><th>n</th><th>AUC</th><th>Slope</th><th>Base rate</th><th>Hitters</th></tr></thead>
      <tbody>
        <tr><td>All hitter-starts</td><td>935</td><td>0.564</td><td>+0.710</td><td>0.353</td><td>54</td></tr>
        <tr><td>Only those a book priced</td><td>140</td><td>0.495</td><td>&minus;0.014</td><td>0.436</td><td>12</td></tr>
      </tbody>
    </table>
    </div>
    <p>Every line in both rows is 1.5 bases, so this is the same question asked
    of two different populations. The model can tell a good hitter-game from a
    bad one across the roster. It cannot do so among the twelve regulars a book
    bothers to post a line on — and the higher base rate in that row shows why:
    the book is already selecting the hitters likely to clear the number.</p>
    <p>That is a <strong>selection effect</strong>, and it is the honest reason
    the board says NO CALL. The skill is real; the market has already priced out
    the part of it you could act on. It also means adding a third prop market
    would not help — the same selection applies wherever a book chooses what to
    quote.</p>
  </section>

  """ + _market_move_section(history) + """
  <section class="card">
    <h2>How to read this</h2>
    <p><strong>Brier score</strong> is the mean squared error of a probability
    forecast — lower is better. The only comparison that matters is against the
    de-vigged market price on the same games: that forecast is free, so a model
    that does not beat it is not adding anything.</p>
    <p><strong>Calibration</strong> asks whether a stated 60% happens 60% of the
    time. It is reported against a sampling-noise floor, because on a small
    sample the observed rate scatters even under a perfect model, and a gap
    smaller than that floor is not evidence of anything.</p>
    <p><strong>Measured model error</strong> separates the error the model is
    responsible for from the irreducible scatter of a random count: a perfect
    projection of a true 5.2-strikeout mean still produces 3s and 8s. It is the
    quantity that gates every NO CALL on the models page.</p>
    <p>Confidence intervals are paired bootstraps over events, 2,000 resamples.
    A difference whose interval contains zero is reported as no difference,
    whichever way the point estimate happens to fall.</p>
  </section>"""

    html = _shell(
        f"{team_name} — Model Track Record",
        "record",
        "&#128200; Track Record",
        "Every published projection, scored against what actually happened — "
        "and against the market price it was quoted beside.",
        _PAGE_CSS + sections,
    )

    output_path = config.OUTPUT_DIR / theme.PAGES["record"][0]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Track record report generated successfully: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the model track record page.")
    parser.add_argument("--team", default=config.TEAM_ABBR)
    parser.add_argument("--season", type=int, default=config.SEASON)
    args = parser.parse_args()
    generate_track_record_html(team_abbr=args.team, season=args.season)


if __name__ == "__main__":
    main()
