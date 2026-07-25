# 🎲 Odds Page — What to Build Next

> Rewritten 2026-07-25 at the end of the consistency sprint. Ordered by value per
> unit of effort, not by ambition. The §0 debt this document opened with has been
> paid; what follows is what is left.

---

## 0. ✅ Consistency debt — paid

Every section of the page now holds to the same standard the strikeout model
does: a line has to come from a book, and a *recommendation* has to clear an
error bar that was measured on held-out data.

| Section | Was | Now |
| :--- | :--- | :--- |
| Batter Total Bases | `OVER 1.5 🔥` against an invented 1.5, on hand-picked 1.65 / 60% thresholds | Real DraftKings line and price, de-vigged; a convolved per-PA distribution for the probability; error bar measured at **±4.9 points** by walk-forward backtest; calls nothing it cannot clear |
| First 5 Innings | `OVER 4.5 🟢` against a hardcoded 4.5, from prorated full-start ERA | Estimate published and labelled as one; **no call**. A missing ERA now reports nothing instead of falling back to 4.00 |
| HR / RBI Targets | `🚀 HIGH` badge on invented thresholds | Relabelled as the usage-and-form leaderboard it always was; rates kept, badge gone |
| Strikeouts | (already fixed) | Market and model probability now both rendered — §1a below |

The batter total-bases work is the substantial piece. It is worth reading
`scripts/backtest_batter_tb.py` before touching that model: the measurement it
performs is the only thing standing between the page and another invented
threshold.

**What the measurement found.** Over 714 held-out starts the model's
over-probability moves ±4.9 points on resampling its own inputs, while the
entire spread of opinion it can demonstrate out of sample is 5.1 points
(recalibration slope 0.74 × prediction sd 0.069). AUC is 0.57 against 0.50 for a
coin flip. So the floor and the ceiling nearly meet — the same shape as the
strikeout model, arrived at independently — and the table publishes the line,
both probabilities and the gap, with no bet.

**One structural finding worth carrying forward:** for total bases the edge is a
difference in *probability*, not in bases. Every hitter is posted at 1.5 and the
book moves the price instead — on 2026-07-25 DraftKings had seven hitters at 1.5
with prices from +124 to +152. Comparing a projection to the line would have
ranked hitters by quality the price already charges for, which is what the old
`proj_tb >= 1.65` rule was really doing.

---

## 1. Cheap wins from data already in hand

### 1a. ✅ Show what the market thinks — done
`book_over_prob` and `model_over_prob` are now rendered in both prop tables, and
— because a fourteen-column table on a 390px phone hides everything past column
two — also written out in prose above each table:

> **Sonny Gray** 4.5 (-154) · market **57.3%** over · model **66.7%** · gap
> **+1.16 K** · `NO CALL ⚖️`

### 1b. The market's own innings expectation
`pitcher_outs` is available and free-standing. DraftKings had Gray at **17.5
outs**, implying ~6.0 IP against our 5.93 projection. Showing it next to
`Proj IP` tells the reader which half of the projection the market agrees with —
and this session it agreed almost exactly, which is how we isolated the
disagreement to K-rate alone. *Effort: ~2 hours, 1 extra credit per build (the
budget is now 240/month of 500 — see below).*

### 1c. Both starters, not just ours
The prop payload already contains the opposing starter (Dylan Cease 7.5) at no
extra cost — same call, same credit, and it is **already being logged to the
odds history**, just not rendered. We cannot *project* him (only Red Sox
pitching is cached), but showing his line and the market's de-vigged probability
is honest and doubles the page's coverage. The same is true of the five
opposition hitters in the total-bases payload. Label the missing projection
clearly rather than leaving a blank. *Effort: ~2 hours, 0 extra credits.*

### 1d. "How did the last ten projections do?"
Every ingredient is already cached: past projections are reproducible from the
game logs, and actual strikeout counts are in the box scores. A short calibration
table — projected vs actual for the starter's last ten outings — is the most
trust-building thing the page could carry, and it is the honest, reader-facing
version of `MODEL_ERROR_K`. *Effort: ~half a day.*

---

## 2. The page's memory — running since 2026-07-25

`data/odds_history.py` appends every build's lines to
`data/cache/odds_history.parquet` (one row per build/event/market/player), the
workflow commits it, and the page reports movement from it. That file is the one
artefact here that cannot be rebuilt later, so it matters that it keeps running.

### 2a. ✅ Line movement — live
The page prints the drift when there is any, and says plainly when there is not:

> 📈 **No line movement.** 4 builds have logged this game, and the line above has
> not moved between them.

### 2b. Closing line value — the next real step
The log records the line at build time; what is missing is the *closing* line and
the projection alongside it. Log those and you can answer the question the whole
sprint left open: **do this model's disagreements predict which way the line
moves?**

CLV is how professionals measure a model before risking anything on results,
because results are far noisier. It is also the only rigorous route to lowering
`MODEL_ERROR_K` and `MODEL_ERROR_TB_PROB` — and therefore the only route to the
page recommending anything again. Needs a build after first pitch to catch the
close, which the current schedule does not have. *Effort: ~1 day.*

---

## 3. Model work — the thing that unlocks recommendations

### 3a. Opponent strikeout-rate adjustment (`roadmap.md` item 1)
The evidence from this session is unusually clear about where the error lives:

| | K/9 |
| :--- | ---: |
| Model's blended rate | 8.59 |
| Gray's season rate | 7.97 |
| What DraftKings is pricing | **~7.35** |

The book prices Gray **below his own season rate**, while independently agreeing
with our innings estimate to within 0.1 IP. That is the signature of an opponent
adjustment we do not have. Toronto's team K% vs RHP/LHP is one MLB API call.

**This is the only item that can bring `MIN_EDGE_K` down and let the page speak
again.** Re-run the backtest afterwards and set `MODEL_ERROR_K` from the
measurement — never by hand. *Effort: ~2 days including re-validation.*

### 3b. The same gap on the hitting side
The total-bases model has no opposing starter in it at all, which is the obvious
first suspect for an AUC of 0.57. The opposing probable is already known to the
page (it is on the F5 card), and his season K/9, HR/9 and WHIP are one call away.
Re-run `scripts/backtest_batter_tb.py` afterwards and copy the constants it
prints. If the demonstrated information does not separate from the noise floor,
the model still says nothing — that is the point of measuring first.
*Effort: ~2 days.*

### 3c. Park and platoon context
Lower value than 3a/3b and more fiddly. Do it only after those are measured, so
you can tell whether it actually moved the error bar.

---

## 4. Deliberately not doing

- **A closer / save prop.** `pitcher_saves` is not a market on The Odds API
  (probed 2026-07-25). `pitcher_record_a_win` exists but was empty. There is no
  data source, so there is nothing to build.
- **Parlays or bet-sizing / Kelly staking.** Two models that cannot currently
  justify a single side have no business compounding positions or sizing them.
- **More prop markets for their own sake** (`pitcher_walks`,
  `pitcher_earned_runs`, `pitcher_hits_allowed`). Each costs a credit per build
  — the page is now at 2 credits per build, ~240/month against a 500 quota — and
  would need its own error bar measured before it could say anything. Breadth is
  not the constraint; validated accuracy is.
- **Anchoring our projection on the book's own numbers.** Tempting after seeing
  how well `pitcher_outs` matched, but a projection derived from the line cannot
  then be used to find an edge against that line. That circularity is the exact
  bug the first version of this model had.
- **Lowering either error constant to make the page speak.** They are outputs of
  a measurement, not settings. `scripts/backtest_batter_tb.py` prints the
  total-bases pair; the strikeout pair comes from the walk-forward backtest
  described in `ODDS_SPRINT_HANDOFF.md`.

---

## Suggested sequence

| Order | Item | Effort | Why here |
| :--- | :--- | :--- | :--- |
| 1 | §1c both starters, both lineups | ~half day | The data is already fetched and already logged; it is pure rendering |
| 2 | §1b outs line | ~2 hours | Cheap corroboration of the innings half of the K model |
| 3 | §3a opponent K-rate | ~2 days | The only route back to recommendations on strikeouts |
| 4 | §3b opposing starter for hitters | ~2 days | The same gap, on the side of the page with more rows |
| 5 | §2b closing line value | ~1 day | Wants a few weeks of §2 history behind it first |
| 6 | §1d calibration table | ~half day | Best done once 3a has changed the numbers |

The history log needs no further work to keep accumulating — but check after the
first CI run with a real key that `data/cache/odds_history.parquet` is actually
being committed, because a snapshot the runner takes and then discards is worth
nothing.
