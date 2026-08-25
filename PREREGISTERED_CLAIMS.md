# 🔒 Pre-registered claims

Predictions written down **before** the games they describe, with the scoring
rule fixed in advance. The point is not that any one night resolves anything —
most entries here are n=1 — but that the claim and its test are on the record
before the outcome is known, so neither can be adjusted afterwards to fit.

Grading is automatic: `scripts/grade_predictions.py` settles rows in
`data/cache/predictions_history.parquet`, and `track_record_report.py` scores
them. Nothing in this file is graded by hand.

---

## 2026-08-24 · Boston at Miami (gamePk 823828)

First pitch 22:41 UTC. Projections logged at **21:35 UTC**, committed in
`92c9339` at 21:36 UTC — 65 minutes before first pitch. Suárez vs Alcántara.

22 rows logged: 1 strikeout, 21 total bases. Five carry a line. All four
priced Boston hitters were confirmed in the posted lineup.

| Market | Player | Line | Projection | Model over% | Book over% (de-vigged) | Page says |
|---|---|---|---|---|---|---|
| K | Ranger Suárez | 4.5 | 4.99 | 55.71% | 55.88% | `PRICED OUT (-5.9% EV) 🏷️` ¹ |
| TB | Wilyer Abreu | 1.5 | 1.75 | 42.24% | 41.01% | `NO CALL` |
| TB | Ceddanne Rafaela | 1.5 | 1.83 | 46.54% | 38.49% | `REVIEW ⚠️ (+8.1 pts)` |
| TB | Willson Contreras | 1.5 | 1.86 | 43.34% | 40.85% | `NO CALL` |
| TB | Nick Sogard | 1.5 | 1.62 | 43.17% | 41.22% | `NO CALL` |

Lines are the 15:30 ET capture already in `odds_history.parquet`. No odds
credits were spent producing any of this.

¹ **Amended 21:44 UTC, still 57 minutes before first pitch.** This row first
logged as `OVER (-5.9% EV) 🔥` — the defect described in Claim 4. It was fixed
in `9a5e30d` and tonight was re-logged before the game, so the capture that
gets scored carries the corrected label. The original 21:35 UTC capture stays
in the append-only archive as the record of what the buggy code said;
`latest_per_game()` keeps the later one, which is the rule scoring already
followed before any of this.

¹ **Second amendment, 21:56 UTC.** The 17:30 ET production build ran after the
fix landed and fetched fresher odds, so the capture that `latest_per_game()`
scores is that one, not mine. Projections are identical; only the market side
moved — Suárez reads `PRICED OUT (-3.0% EV)` rather than −5.9%, and Rafaela
`REVIEW (+7.4 pts)` rather than +8.1. Neither claim changes in substance, and
the scored row is now a genuine production capture rather than a hand-run one.

### Claim 1 — the REVIEW flag is the model being wrong, not the model finding value

Rafaela's gap of **+8.1 points** exceeds `MAX_PLAUSIBLE_EDGE_TB_PROB` (4.8),
which is the most information the model has ever been shown to hold out of
sample. The project's own position is that a gap that large is parameter noise,
not an edge a liquid market left lying around.

**Predicted:** REVIEW-flagged rows settle nearer the **book's** probability than
the model's. Tonight that is 38.5%, not 46.5%.

**Scored by:** Brier score of REVIEW rows against the model's probability versus
against the de-vigged market, accumulated across every REVIEW row. **n=1 tonight
— this resolves nothing on its own** and is recorded to accumulate.

**Falsified if:** over a meaningful REVIEW sample, the model's probability beats
the market's with a paired-bootstrap CI clear of zero. That would mean the
ceiling is set too low and the model is being silenced when it has something.

### Claim 2 — the selection effect persists

The total-bases model scores AUC 0.564 with a +0.710 recalibration slope across
935 hitter-starts, and 0.495 with −0.014 across the 140 a book actually priced.
Tonight adds **4 priced and 17 unpriced** Boston hitter-games.

**Predicted:** as the sample grows, discrimination on unpriced hitters stays
materially above discrimination on priced ones.

**Falsified if:** the two converge, which would mean the gap was small-sample
noise rather than the book selecting hitters likely to clear the number.

### Claim 3 — the projections are unbiased, not merely imprecise

**Predicted:** tonight's five projection errors are consistent with the measured
bands — `MODEL_ERROR_K` 0.37 K on top of Poisson scatter for Suárez, and the
total-bases equivalent — with **no systematic direction**. Every total-bases
projection tonight sits above its 1.5 line (1.62–1.86), so a night where all
four land under is the shape worth watching for.

**Scored by:** `analysis.scoring.decompose()` bias term over the accumulating
sample, not tonight alone.

### Claim 4 — flagged in advance: the strikeout recommendation contradicts its own probability layer

Not a prediction about the game. A prediction about **the code**, recorded here
because tonight is the first night it is visible on a live board.

The strikeout model gates on `edge_diff` in **K units** — projection minus line
— and never consults the price. Suárez projects 4.99 against a 4.5 line, so
`edge_diff = +0.49` clears `MIN_EDGE_K` and the page prints
`OVER (-5.9% EV) 🔥`. But the model's own over-probability, 55.71%, is **below**
the book's de-vigged 55.88%. By the standard the total-bases model is held to,
there is no edge here at all — it would read `NO CALL`.

So the page is about to publish a recommendation, with a flame on it, that is
negative expected value at the offered price and that its own probability layer
contradicts.

**Fixed before first pitch, in `9a5e30d`.** `_side_call` now computes the EV
first and refuses to name a side unless it is positive, returning `PRICED OUT`
with the number attached. Negative EV is not a weaker OVER; it is the book
having already taken that side and charged for it.

This is a labelling fix — no projection moved. But it has a substantive
consequence worth recording: **a model probability below the book's de-vigged
price cannot produce positive EV, so it can no longer produce a call either.**
The EV sign now enforces on the strikeout side the same probability discipline
the total-bases model was already held to, without rewriting the gate.

**Still open, and deliberately not touched tonight:** the K gate continues to
*screen* on projection minus line in K units, where total bases screens in
probability space. The EV check catches the bad calls at the exit; it does not
make the two models agree on what an edge is.

**Predicted:** re-screening strikeouts in probability space removes further
calls beyond the ones the EV gate now catches, and the removed ones are not
profitable. The 24 graded strikeout predictions already show AUC 0.415 and a
recalibration slope of −0.319, so the probability layer is the weak part.

**Falsified if:** calls that clear the K-unit gate but fail a probability gate
show positive CLV once there are enough of them to tell.

---

## 2026-08-25 · Boston at Miami (gamePk 823826)

First pitch 22:40 UTC. Written at **21:40 UTC — 60 minutes before**. Tolle vs
Phillips. Lineup posted; all four priced Boston hitters confirmed in it.

Scored capture as of writing is **19:34 UTC** (the 15:00 ET build). The 17:30 ET
build had not landed at time of writing — GitHub's scheduler runs it late, and
yesterday's arrived at 21:56. If it lands before first pitch it becomes the
capture `latest_per_game()` scores and the prices below move. **The claims do
not depend on which capture wins**; only the table does.

| Market | Player | Line | Proj | Model over% | Book over% | Board says | Slot |
|---|---|---|---|---|---|---|---|
| K | Payton Tolle | 6.5 | 6.09 | 40.81% | 47.11% | `UNDER (+5.4% EV) 🧊` | — |
| K | Tyler Phillips *(MIA)* | 3.5 | 3.46 | 45.38% | 56.31% | `NO CALL` | — |
| TB | Nick Sogard | 1.5 | 1.61 | 42.84% | 39.29% | `NO CALL` | 1 |
| TB | Ceddanne Rafaela | 1.5 | 1.83 | 46.41% | 41.32% | `REVIEW ⚠️ (+5.1 pts)` | 2 |
| TB | Wilyer Abreu | 1.5 | 1.75 | 42.43% | 42.95% | `NO CALL` | 3 |
| TB | Willson Contreras | 1.5 | 1.85 | 42.99% | 39.44% | `NO CALL` | 4 |

Nine books priced this board, against one on 2026-08-24. Same credit cost.

### Claim 5 — the first side the EV gate has allowed through

`UNDER (+5.4% EV)` on Tolle is the first call the board has published since
`_side_call` began requiring positive EV. Yesterday's Suárez was the same shape
and was refused; this one clears, so the gate is not simply silencing
everything.

**Predicted:** it is not an edge. The project's own measured position, over 175
graded player-games and 160 market-movement observations, is that these models
do not beat the market — so a call clearing an EV threshold should still show
closing-line movement indistinguishable from zero, and should win at roughly
the model's stated 59.2% under rather than better.

**Scored by:** `analysis.clv` over the accumulating set of gate-allowed calls,
and their Brier against the de-vigged market. **n=1 tonight.**

**Falsified if:** gate-allowed calls accumulate positive movement with a CI
clear of zero. That would be the first evidence in this project of a rule that
selects profitable disagreements, and would deserve a much harder look than one
night can give it.

### Claim 6 — the opposing starter, and a gap recorded before it bites

Tyler Phillips is the first opposing starter this project has ever projected in
production. Yesterday's Alcántara row never existed: the wiring landed at 21:59
UTC, three minutes after the build that would have used it.

**Predicted:** the same estimator on the other team's starter is neither better
nor worse than on ours. Projection error should sit in the same measured band —
it is `project_marcel` reading the same league logs, with the opponent factor
computed against our lineup rather than theirs.

**Known limitation, stated now rather than discovered later:**
`scripts/grade_predictions.py` is given only Boston's `pitching` and `batting`
caches, so `resolve_appearance` will return "player did not appear" for Phillips
and **this row will not settle**. The actual is not missing — league logs hold
his 31 starts — it is simply not handed to the grader. Recording it here so the
first opposing-starter prediction is on the record as ungradeable *by design as
currently wired*, and not quietly counted as a miss later. Deliberately not
fixed tonight: grading runs after the game and rewriting it an hour beforehand
risks the run that grades everything else.

### Claims 1–3 — what tonight adds

**Claim 1** gets a second observation: Rafaela is REVIEW-flagged again, at
+5.1 points, the model again more bullish than the book (46.4% vs 41.3%).
Yesterday's went the way the claim predicted, on n=1.

**Claim 2** gets a supporting observation that is not part of its scoring rule
but is worth recording: the four priced Boston hitters bat **1, 2, 3 and 4**.
Yesterday's four batted 1, 2, 3 and 4. The book is pricing the top of the order
both nights, which is the selection the claim describes, visible directly.

**Claim 3** adds five projection errors. Every total-bases projection again
sits above its 1.5 line (1.61–1.85), the same shape as yesterday, when three of
four landed under and the projections averaged 1.77 against an actual mean of
1.0. Two nights is not a bias measurement and is not offered as one.

---

## How to read a claim here

- **n is stated honestly.** Most of these are one observation. A claim that
  cannot be resolved tonight says so.
- **The scoring rule is fixed before the outcome.** If a claim needs a different
  test after the fact, that is a new claim, dated when it was written.
- **A falsification condition is required.** A claim with no stated way to be
  wrong does not belong in this file.
