# 🎲 Odds Page — What to Build Next

> Written 2026-07-25 at the end of the odds sprint. Ordered by value per unit of
> effort, not by ambition. Read §0 before building anything in §1–§3.

---

## 0. ⛔ Consistency debt — pay this first

The strikeout model now refuses to call a side unless the edge beats its own
measured error. **Three other sections on the same page still make confident
calls against lines nobody ever quoted.** That is the exact problem this branch
was created to remove; it survived because attention was on the K model.

| Section | What it does | Problem |
| :--- | :--- | :--- |
| Batter Total Bases | `OVER 1.5 🔥` when `proj_tb >= 1.65` or `l10_o15_tb_pct >= 60` | **The 1.5 line is invented.** No book price, no edge, no EV. The thresholds 1.65 and 60% are hand-picked. |
| First 5 Innings | `OVER 4.5 🟢` when projected F5 runs > 4.5 | **The 4.5 line is hardcoded.** And `f5_exp_runs` is a full-start ERA prorated to five innings — the code comment says outright it is *not* a real F5 split. |
| HR / RBI Targets | `🚀 HIGH` when `l10_hr >= 2` or `pa_per_hr <= 18` | Thresholds invented. Reads like a pick; is a heuristic. |

**The fix is already half-built.** `OddsAPIClient.batter_total_base_lines()`
exists, is tested, returns real DraftKings lines for ~7 hitters per game — and
**is called by nothing**. The lines are fetched-capable and thrown away.

**Recommended order:**

1. Wire `batter_total_base_lines()` into `batter_total_bases_model`, mirroring
   what `pitcher_strikeout_model` now does: real line, real de-vigged price,
   Poisson (or empirical) probability, and **no recommendation until that model's
   own error bar has been measured the same way**.
2. Either price the F5 card against real `totals` / `spreads`, or drop the
   `f5_line_recommendation` field. Prorated ERA against a hardcoded 4.5 should
   not be rendered as a bet.
3. Relabel the HR section as what it is — a *usage and form* leaderboard, not a
   prop target. Removing the badge is enough; the underlying rate stats are fine.

Until this is done the page's honesty is uneven, and the K model's restraint
reads as arbitrary rather than principled.

---

## 1. Cheap wins from data already in hand

### 1a. Show what the market thinks — it is already computed
`pitcher_strikeout_model` writes `book_over_prob` (de-vigged) and
`model_over_prob` to the frame. **Neither is rendered.** A reader currently sees
`4.5 (-137)` and has to do the de-vig in their head.

> Market: **54.6%** over · Model: **66.7%** over

That single line is the most actionable thing on the page and costs nothing —
the numbers exist, they just are not printed. *Effort: ~1 hour.*

### 1b. The market's own innings expectation
`pitcher_outs` is available and free-standing. DraftKings had Gray at **17.5
outs**, implying ~6.0 IP against our 5.93 projection. Showing it next to
`Proj IP` tells the reader which half of the projection the market agrees with —
and this session it agreed almost exactly, which is how we isolated the
disagreement to K-rate alone. *Effort: ~2 hours, 1 extra credit per build.*

### 1c. Both starters, not just ours
The prop payload already contains the opposing starter (Dylan Cease 7.5) at no
extra cost — same call, same credit. We cannot *project* him (only Red Sox
pitching is cached), but showing his line and the market's de-vigged probability
is honest and doubles the page's coverage. Label the missing projection clearly
rather than leaving a blank. *Effort: ~2 hours, 0 extra credits.*

### 1d. "How did the last ten projections do?"
Every ingredient is already cached: past projections are reproducible from the
game logs, and actual strikeout counts are in the box scores. A short calibration
table — projected vs actual for the starter's last ten outings — is the most
trust-building thing the page could carry, and it is the honest, reader-facing
version of `MODEL_ERROR_K`. *Effort: ~half a day.*

---

## 2. Give the page a memory

**This is the highest-leverage new capability, and it is nearly free.**

The build now runs four times a day and **discards the previous snapshot every
time**. Gray's line moved from `-137` to `-154` during this session and the page
has no idea. Persist each build's lines to `data/cache/odds_history.parquet`
(one row per event/market/player/build) and two things become possible:

### 2a. Line movement
> Opened **4.5 (-137)** at 12:00 ET → now **4.5 (-154)**. Market moving toward
> the over.

Line movement is one of the few genuinely informative public betting signals, it
requires no model at all, and it converts the static-page weakness into a
strength: a page that rebuilds four times a day is *exactly* the thing that can
track drift. *Effort: ~1 day. Storage: kilobytes per week.*

### 2b. Closing line value — the only honest scoreboard
Log the projection, the line at build time, and the closing line. After a few
weeks you can answer the question the whole sprint left open: **do this model's
disagreements predict which way the line moves?**

CLV is how professionals measure a model before risking anything on results,
because results are far noisier than line movement. It is also the only rigorous
route to lowering `MODEL_ERROR_K` — and therefore the only route to the page
recommending anything again. *Effort: ~1 day on top of 2a.*

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

### 3b. Park and platoon context
Lower value than 3a and more fiddly. Do it only after 3a is measured, so you can
tell whether it actually moved the error bar.

---

## 4. Deliberately not doing

- **A closer / save prop.** `pitcher_saves` is not a market on The Odds API
  (probed 2026-07-25). `pitcher_record_a_win` exists but was empty. There is no
  data source, so there is nothing to build.
- **Parlays or bet-sizing / Kelly staking.** A model that cannot currently
  justify a single side has no business compounding positions or sizing them.
- **More prop markets for their own sake** (`pitcher_walks`,
  `pitcher_earned_runs`, `pitcher_hits_allowed`). Each costs a credit per build
  and would need its own error bar measured before it could say anything. Breadth
  is not the constraint — validated accuracy is.
- **Anchoring our projection on the book's own numbers.** Tempting after seeing
  how well `pitcher_outs` matched, but a projection derived from the line cannot
  then be used to find an edge against that line. That circularity is the exact
  bug the first version of this model had.

---

## Suggested sequence

| Order | Item | Effort | Why here |
| :--- | :--- | :--- | :--- |
| 1 | §0 consistency debt | ~1 day | The page currently contradicts its own standard. |
| 2 | §1a market probability | ~1 hour | Highest value-to-effort on the page. |
| 3 | §2 odds history + line movement | ~1–2 days | Unlocks CLV; every day not logging is data lost forever. |
| 4 | §1c both starters, §1b outs line | ~half day | Cheap coverage once the render path is touched. |
| 5 | §3a opponent K-rate | ~2 days | The only route back to recommendations. |
| 6 | §1d calibration table | ~half day | Best done once 3a has changed the numbers. |

**Start logging odds history first if you only do one thing** — items 1, 2, 4 and
5 can be built at any time, but §2 can only ever accumulate data going forward.
