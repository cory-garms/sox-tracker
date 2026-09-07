# 🧭 Where to spend effort next

Written 2026-09-07, with 19 games left in the regular season.

This is the plan that follows from what the site has now measured about itself,
rather than from what would be interesting to build. Most of it is not model
work, because the model is close to its ceiling and the ceiling has been
measured rather than guessed.

The figures below are a **dated snapshot**, typed into this document on
2026-09-07 — which is the exact failure this project spent that day finding in
four other places. They are safe to quote only because each one names the page
or module that recomputes it, and that live number is the authority. If a figure
here disagrees with the track record page, the page is right and this file is
stale.

---

## 1. What is actually known

Four measurements constrain everything else. All four are on
[`docs/track_record_BOS_2026.html`](docs/track_record_BOS_2026.html) and are
rebuilt nightly.

### The strikeout model is near its ceiling

Of its total error, **98.1% is irreducible Poisson scatter** and 1.9% is model
error. A *perfect* projection — one that knew everything knowable — would take
RMSE from 2.246 K to 2.225 K.

> **0.9% is the ceiling on all feature work combined.** Weather, park, umpire,
> catcher framing, rest, handedness: they are competing for shares of that.

The headroom that existed has largely been spent, and the lineage shows it —
`analysis/model_lineage.py`, over 3,165 held-out league starts:

| model | model error | share of its MSE |
|---|---|---|
| season / last-5 blend (until 2026-08-04) | 0.588 K | 6.5% |
| Marcel regression | 0.413 K | 3.3% |
| Marcel + opponent (in force) | **0.307 K** | **1.9%** |

### Skill dies at the first book, not gradually

The selection effect is the binding constraint, not accuracy. Correlation
between projection and outcome, by how many books priced the selection:

| market | unpriced | 1–2 books | 3+ books |
|---|---|---|---|
| batter total bases | **+0.192** [+0.025, +0.349] | −0.043 | −0.017 |
| pitcher strikeouts | +0.826 (n=20) | +0.432 | +0.353 |

The drop happens the moment *any* book posts a number, and a thinly-quoted
selection is already as dead as a heavily-quoted one. This is the measurement
that closes "hunt the markets the books cover lightly" as a strategy.

*Sample caveat: the strikeout cells are n≈20–26 with overlapping intervals, and
this split was chosen after seeing the data. The direction is consistent across
both markets; the magnitudes are not to be relied on.*

### Closing line value cannot currently be measured

The movement measured over every capture is positive and clears zero. Restricted
to captures that landed near an actual close, it reverses:

| close window | n | mean move | 95% CI |
|---|---|---|---|
| every capture (median 58 min out) | 456 | +0.27 | [+0.08, +0.46] |
| within 120 min | 352 | +0.23 | [+0.01, +0.46] |
| **within 60 min** | 250 | **−0.19** | [−0.43, +0.05] |
| **within 30 min** | 149 | **−0.29** | [−0.63, +0.04] |

A price read three hours out is not a close. **Until this is fixed, no change to
anything can be evaluated** — which is why it is item one below and everything
else is item two or later.

### Two features tested and closed

- **Days of rest** — nothing. Residuals at 5, 6 and 7+ days sit within ±0.09 K.
  Modern rotations barely vary it: the short-rest buckets are n=2 and n=6.
- **Home / away** — a real bias (+0.272 K, interval excluding zero) that
  produced **no measurable improvement** when applied (+0.0042 K², interval
  spanning zero). A real effect and a useful one are different things, and this
  is the cheapest available demonstration of it.

---

## 2. Do these, in this order

### Priority 1 — Get the closing capture near first pitch

**The only genuine blocker.** Median capture lands 58 minutes before first pitch
and the CLV answer flips sign between the loose and tight windows. Every other
item on this page is unfalsifiable until this is done.

The mechanism already exists: `.github/workflows/close.yml` ticks every ten
minutes and `scripts/capture_close.py` reads real first-pitch time from a free
`get_events()` call before spending anything. What is missing is that the gate
lets a capture count as a close when it is hours early.

- Target: median lead **under 15 minutes**, and record the lead on every row
  (`close_lead_minutes` already exists on the CLV frame).
- Cost: no odds quota beyond what the close job already spends; this is a
  gating change, not new infrastructure.
- Success test: the close-window table on the track record page stops
  disagreeing with itself.

### Priority 2 — Capture openers earlier, not smarter

The one place skill survives is *before* a book has priced the selection
(unpriced total bases +0.192, interval excluding zero). That points at timing
rather than modelling: if there is value anywhere, it is in the window between a
line going up and the market sharpening it.

- Log the first price seen for each selection and how long after posting it was
  captured, so "were we early" becomes a measurable quantity rather than an
  impression.
- **Hypothesis, pre-registered here:** movement measured from a genuinely early
  opener to a genuinely near close will be larger and more informative than the
  current open→close pair. It may still be zero. Write the scoring rule into
  [`PREREGISTERED_CLAIMS.md`](PREREGISTERED_CLAIMS.md) before the first sample.

### Priority 3 — Bank the data that cannot be tested yet

Weather, park, umpire assignment, catcher. All cheap to record now and worthless
without a season of them behind them. Collect through the winter and spring so
the question is answerable in 2027 rather than being exactly where it is today.

Expected value against strikeouts specifically is low — see the 0.9% ceiling —
so this is banking optionality, not a funded bet. Record it, do not model it,
and do not put it on a page until it has been tested.

---

## 3. Do not do these, and why

Each of these is closed by a measurement, not by an opinion.

| Idea | Closed by |
|---|---|
| Add features to the strikeout model | 0.9% ceiling; 98.1% of error is Poisson |
| Rest days / pitch-count limits | tested 2026-09-07, residuals flat within ±0.09 K |
| Home/away or day/night adjustments | real bias, no measurable MSE improvement |
| Hunt thinly-priced markets | skill dies at the first book, not gradually |
| Add a third prop market | the same selection applies wherever a book quotes |
| Chase edge in the playoffs | see below |

### The playoffs are the worst hunting ground of the year

Fewest games, maximum market attention, sharpest lines, and every prop priced by
everyone. Given that a *single* book pricing a selection is enough to erase the
measurable edge, October is precisely where not to look for one.

What October is good for is a **validation window**: a clean, high-attention
sample against which to test whether the Priority 1 close-capture fix actually
works. Treat it as a test bench, not an opportunity.

---

## 4. The honest framing

On the evidence gathered to 2026-09-07, the models are near their ceiling and
the market has already priced out the skill they demonstrably have. That is a
finding, not a failure, and it is worth more than a fabricated edge would be.

What this project is unusually good at is not prediction. It is **measurement
discipline** — and on the single day this plan was written it caught five of its
own numbers being wrong or overstated: a hand-typed batting average, a
duplicated on-base formula, a hardcoded selection table two weeks stale, a
standard-error formula half its true width, and a published closing-line claim
that did not survive being asked at the right resolution.

That is the asset. The plan above is mostly about protecting it: measure at a
resolution where the answer means something, collect what cannot yet be tested,
and decline to ship the things that measurement has closed.

---

## 5. Status of the claims on this page

| Claim | Status |
|---|---|
| 0.9% feature ceiling | **measured**, recomputed every build |
| model lineage improvements | **measured**, paired bootstrap, 3,165 starts |
| selection effect exists | **measured**, gap significant in both markets |
| skill dies at the first book | **exploratory**, post-hoc split, small K cells |
| CLV unmeasurable at current close | **measured** |
| earlier openers carry value | **hypothesis**, not yet tested |

Anything marked exploratory or hypothesis must be pre-registered in
[`PREREGISTERED_CLAIMS.md`](PREREGISTERED_CLAIMS.md) with its scoring rule fixed
before it is tested, or it does not go on a page.
