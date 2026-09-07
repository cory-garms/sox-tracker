# 🎲 Sports Betting & Prop Intelligence Roadmap — `sox_tracker`

A strategic feature roadmap for transforming **`sox_tracker`** into an elite pre-game betting intelligence & prop model suite.

> **Read [`NEXT_SEASON_PLAN.md`](NEXT_SEASON_PLAN.md) first.** As of 2026-09-07
> the strikeout model's measured ceiling is 0.9% — 98.1% of its error is
> irreducible Poisson scatter — so most of the prop-accuracy items below are
> competing for shares of a percent. Several are struck through here because a
> measurement closed them, not because they were tried and abandoned. The open
> work is measurement and timing, not features.

---

## 🎯 1. Player Prop Betting Intelligence

### ⚾ Pitcher Strikeout Over/Under Model (`O/U K's`)
- ~~**Opposing Lineup K-Rate Matching**~~ — **built 2026-07-27, and confirmed to
  work on 2026-08-04.** `data/opponent.py` applies a league-relative team K rate,
  regressed by plate appearances and computed only from games *before* the one
  being projected. It was recorded here for a week as "measured no improvement",
  on a 73-start test too small to resolve it. Across all 2,347 league starts it
  is worth a paired-bootstrap MSE gap of [+0.016, +0.121] K² on top of Marcel —
  clear of zero. A split by pitcher handedness is the open version of this item.
- ~~**Regress the projection toward the league mean**~~ — **built 2026-08-04.**
  The largest single accuracy gain found so far ([+0.114, +0.308] K²), and it
  replaced rather than extended the season/last-5 blend, which measured as worth
  nothing at all over a plain season average. See
  [`analysis/k_projections.py`](analysis/k_projections.py).
- ~~**Pitch Count & Innings Limit Predictor**~~ — **closed 2026-09-07 by
  measurement.** Days of rest carries no signal: residuals at 5, 6 and 7+ days
  sit within ±0.09 K, and modern rotations barely vary it (the short-rest
  buckets are n=2 and n=6). The pitch-count half is untested, but it is bidding
  for a share of a 0.9% ceiling.

### 💥 Batter Total Bases (TB) & Home Run Props
- **Pitch Type Matchup Matrix**: Match batter pitch-type OPS (e.g., Devers vs. 4-Seam Fastballs > 95mph) against opposing starter's pitch mix via Baseball Savant Statcast.
- **Stadium & Park Factor Adjustments**: Factor in Fenway Park Green Monster HR/2B park factors vs. road venue dimensions. — *Untested, and see the ceiling note above. The nearest thing measured is home/away, which is a real bias (+0.272 K, interval clear of zero) that produced no measurable improvement when applied. Bank the data; do not model it yet.*

---

## 💰 2. Game Lines & Expected Value (+EV) Models

### 📈 Moneyline Implied Probability & Value Alerts
- **Pythagorean / BaseRuns Win Probability**: Calculate model true win probability based on rolling run differential and team OPS/ERA.
- **Vegas Odds Edge Calculator**: Compare model win% against sportsbook moneyline odds to flag **+EV (Positive Expected Value)** bets.

### ⏱️ First 5 Innings (F5) Moneyline & Total
- **Starter-Only F5 Model**: Isolate starting pitcher metrics for the first 5 innings to eliminate bullpen variance.

---

## 📊 3. Trend & Prop Market Trackers

### 🚫 NRFI / YRFI Tracker (No Run / Yes Run First Inning)
- **1st Inning Run Scored/Allowed Matrix**: Track Red Sox starter 1st-inning ERA, WHIP, and NRFI success rate.

### 🎲 Game Total Over/Under Trends
- **Contextual O/U Hit Rates**: Track Over/Under trends for Day vs. Night games, Home vs. Away, and Weather/Wind factors. — *As a tracker this is fine. As a model input it is the home/away result again: a real split that does not survive contact with the noise it has to beat.*

---

## 🔭 3b. The work that is actually open

Not features. See [`NEXT_SEASON_PLAN.md`](NEXT_SEASON_PLAN.md) for the reasoning
and the numbers.

1. **Close the capture gap.** The last pre-game price lands a median of 58
   minutes before first pitch, and the closing-line result reverses sign
   between the loose and tight windows. Nothing else can be evaluated until
   this is fixed.
2. **Capture openers earlier.** The only population where skill survives is the
   one no book has priced yet, which points at timing rather than modelling.
3. **Bank weather, park, umpire and catcher** without modelling them, so the
   question is answerable in 2027.

---

## 🚀 4. Proposed 5th HTML Page: `betting_BOS_2026.html`

A standalone interactive Plotly page (`betting_report.py`) featuring:
1. **Top +EV Prop Recommendations** (Pitcher K's, Batter TB, NRFI).
2. **First 5 Innings (F5) Starter Matchup Card**.
3. **Over/Under & Moneyline Trend Dashboard**.
