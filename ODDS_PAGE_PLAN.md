# 🎲 Odds Page — What to Build Next

> Rewritten 2026-07-25, extended 2026-07-27. Ordered by value per unit of effort,
> not by ambition. §0-§4 are the consistency sprint; §5 is the market-pricing
> sprint; §6 is what is actually left.

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

### 1c. ✅ Both starters, both lineups — done
Superseded by §5 below and delivered as a side effect of it. The consensus table
prices every player in the payload, which is both starters and both lineups, so
the opposing side is no longer parsed away. It cost nothing extra, as predicted.

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

---

## 5. Market consensus and promotions — added 2026-07-27

The page now carries the one source of edge on it that does not require a model
to be right, and it turned out to be free.

### 5a. ✅ Every US book, not just ours
`OddsAPIClient` had `bookmakers=draftkings` hardcoded on both odds calls. The
Odds API bills per **market x region** and never per bookmaker — verified
against the `x-requests-last` header on 2026-07-27, where a one-book and a
six-book request for the same market each cost exactly 1 credit. Narrowing to
one book bought nothing and discarded the only benchmark on the page that is
independent of our models.

Six US books now come back for the same credit. `parse_player_lines_by_book()`
keys by book, which was a necessary correctness fix rather than a nicety: the
old parser merged every bookmaker into one entry per player, so widening the
request without it would have blended a DraftKings line with a Bovada price and
produced a quote that exists nowhere.

### 5b. ✅ The consensus table
Each book is de-vigged on its own before the books are combined, the median is
taken rather than the mean, and **the book being priced is excluded from its own
benchmark**. Only books quoting the same number are compared, and a selection
needs at least three others before it appears.

What it found on the first night (2026-07-27, BOS at OAK): **nothing**. Every
selection priced at or behind consensus, the closest being Tolle under 5.5 at
-0.98%. That is the correct and expected answer — it is what the vig looks like
from the inside, and a table that had produced a +EV play on its first evening
would have been evidence of a bug rather than of an edge. The comparison books
are retail US books, not sharp limits, so a small positive here is noise.

### 5c. ✅ Promotion valuation
Promotions are the only positive expectation available, so they are computed
exactly rather than by feel. A profit boost rearranges to

    EV_boost = (1 + b) * EV_raw + b * (1 - p)

which is worth stating because the second term grows as the probability *falls*:
at a fair price a 50% boost returns +25% on an even-money bet and +40% on a +400
one. A boost belongs on the longest fairly-priced selection available, not the
safest, and the boosted column consequently does not rank the same way as the
raw one.

An early-win token is an *additive* bump in win probability, so its EV
contribution is `lift * decimal_odds` — it prefers long prices for a different
reason. The lift is measured, not assumed:
`scripts/measure_early_win_lift.py` walks half-inning linescores over 3,172
team-games and finds P(ever led by 2+ **or** won) - P(won) = **+0.1028**.
Checking only at half-inning boundaries is exact rather than approximate, since
only the batting team can score inside a half-inning. The script prints P(win),
which must come out at 0.5000 and is what validates the walk.

It is stored as a lift and not as a rate on purpose: a team's own P(ever up 2)
is anchored to the schedule it happened to play and cannot be set against
tonight's price, whereas the lift transfers across price levels.

### 5d. ✅ A bet log that can be graded
`data/bet_log.py` plus `scripts/log_bet.py`. Stake defaults to 0, so an idea can
be measured before it costs anything, and a paper row grades identically to a
real one. Every row stores the price taken, the model's probability at that
moment, and a `closing_price` filled in later from the odds history — which is
§2b, the CLV work, finally having somewhere to land.

**Known understatement:** "closing" means the last price this repo observed, and
the last scheduled build lands ~90 minutes before a typical first pitch. Real
CLV needs a build nearer the close. That is the next thing worth doing here.

### 5e. ✅ Closing line capture — the CLV gap closed
The understatement in §5d is fixed. `scripts/capture_close.py` plus
`.github/workflows/close.yml` capture the last *pre-game* price at any start
time, which is what CLV has to be measured against.

The design rests on one fact about the provider: **`get_events()` costs zero
quota.** So the job runs every 20 minutes across MLB's start window, reads the
real first-pitch time for free on every tick, and spends credits only when the
game is genuinely about to start — 0 credits outside the window, 3 inside it,
so ~3 per game day rather than 3 per tick. A static cron cannot follow a start
time that moves from 13:35 to 21:40 ET; a free gate polled every 20 minutes can.

There is a floor as well as a ceiling on the window. Past ~2 minutes to first
pitch a delayed runner can capture *in-play* prices, which are a different
market; recording one as the close would invert the CLV of every bet on that
game. `bet_log.grade_from_history()` enforces the same rule independently, using
the last snapshot taken at or before `commence_time` rather than simply the last
one.

### 5f. Never resolve an odds_history conflict by picking a side
`data/cache/odds_history.parquet` is now committed from three directions — the
scheduled refresh, the closing capture, and local builds — so git will present
it as a binary conflict. **Every ordinary resolution of one is wrong here.**
`--ours`, `--theirs`, `git checkout` and `-X theirs` all discard one side, and
both sides routinely hold snapshots the other lacks: merging the two versions in
flight on 2026-07-27 gave 193 rows where one side had 159 and the other 162, so
either pick would have silently destroyed ~30 observations.

Use `scripts/merge_odds_history.py`, which unions on the log's own identity key
and is therefore idempotent:

    git show :2:data/cache/odds_history.parquet > /tmp/ours.parquet
    git show :3:data/cache/odds_history.parquet > /tmp/theirs.parquet
    python scripts/merge_odds_history.py /tmp/ours.parquet /tmp/theirs.parquet
    git add data/cache/odds_history.parquet

The closing-line workflow uses the same script to recover from a lost push race.

### 5g. Credit budget
    refresh.yml   3 credits x 4 builds/day   = 12/day
    close.yml     3 credits x ~1 capture/day =  3/day
                                              ~450/month against 500

The quota is no longer the binding constraint — the plan is to upgrade the tier
if the CLV record shows the models are worth feeding. What has not changed is
that **a new market still needs its own measured error bar before it can say
anything.** Breadth was never the constraint; validated accuracy is.


---

## 6. What is left — 2026-07-27

Reordered after the market-pricing sprint. The headline finding of that sprint
changes the priorities: **the models were never the binding constraint on this
page's usefulness — the absence of a market benchmark was.** With consensus
pricing and promotion valuation in place, the page is useful on nights when both
models decline to speak, which is every night so far.

### 6a. Lineup cross-check — do this first
A hitter carried a live +117 total-bases prop on 2026-07-27 while not in the
posted lineup, and nothing on the page flagged it. The lineup is one free MLB
call and is already fetched for the matchup page. Cross-reference propped
players against it and mark anyone not starting. *Effort: ~2 hours. This is a
live trap, not a hypothetical.*

### 6b. Accumulate CLV to n≈20 before touching a model
Ten graded bets is an anecdote. Twenty is roughly where the sign of a mean CLV
starts to carry information, and CLV is the only route to lowering an error bar
honestly. **Resist the urge to improve a model before the measurement can tell
you whether you did.** The 2026-07-27 opponent adjustment is the cautionary
example: principled, free, and completely invisible to a 73-start test.

### 6c. Grade parlays
A parlay is logged as one row spanning four markets; the grader works per
selection, so it never gets a closing price. Grade the legs individually and
compute the parlay's own EV separately — and note that correlated legs make the
independence assumption optimistic, sometimes badly.

### 6d. Multi-season strikeout backtest
The only way to settle whether the opponent adjustment helps. A ~0.3 K effect
against 1.39 K of model error needs far more than 73 starts to resolve. Until
then the adjustment stays in, uncredited.

### 6e. Park factors
`roadmap.md` 3c, still untouched. Sutter Health Park is a converted Triple-A
stadium and the total-bases model has no idea. Do it after 6b, so the error bar
can say whether it helped.

### 6f. Generate `docs/index.html`
It is hand-maintained while `viz/theme.PAGES` is generated. A test asserts they
agree, which catches drift but does not prevent it.

---

## 7. The finding worth carrying forward

On the first night the consensus engine ran live — 32 selections, 14 prop
markets, 6 game markets, up to 8 books — **nothing was mispriced.** The best
raw price on the board was −0.98%.

The only positive expectation available came from a **promotion**, and it was
worth more than every model on the site combined: a 50% profit boost on the
longest fairly-priced leg returned +25.4% against a slate whose four unboosted
props cost −0.13U in expectation.

That is the correct result for a retail bettor at a liquid book, and it should
be the prior. **A future sweep that reports a large edge against eight books is
more likely a bug than an opportunity** — this one did exactly that on its first
run, reporting +0.27% on a total because a 10.0 line was being compared against
books sitting on 9.5. Check that you are comparing identical bets, at
comparable timestamps, before believing any of it.
