# 🎲 Odds Sprint — Handoff for the Next Agent

> Updated 2026-07-25 after the consistency sprint. General project state lives in
> [HANDOFF_GUIDE.md](HANDOFF_GUIDE.md); this document covers only live odds.

---

## 1. TL;DR

The live odds pipeline works end to end. Two prop models — strikeouts and batter
total bases — are debugged, backtested against held-out data, and guarded by
their own measured error bars. Neither currently calls a side, which is the
accurate description of what they can prove rather than a fault. Every other
section of the page has had its invented lines and hand-picked thresholds
removed. Every build's prices are now logged to
`data/cache/odds_history.parquet`, so the page can report line movement.

`ODDS_API_KEY` is set both locally (`.env`) and as a GitHub Actions secret, so CI
builds with real lines. Cost is now **2 credits per build** — one per prop market
— which is ~240/month against the 500 quota.

---

## 2. The API key

`ODDS_API_KEY` lives in **`.env` in the repo root**. It is 32 characters and
confirmed working.

- `.env` is gitignored (`.gitignore:11`) and **untracked**. Keep it that way.
- Never print, echo, log, or paste the value anywhere.
- `config.py` loads it with `python-dotenv` (`load_dotenv(..., override=False)`),
  so a real environment variable always beats the file and a stale local `.env`
  can never shadow the CI secret. Both directions were verified.

---

## 3. Verified facts (measured 2026-07-25)

Run `python scripts/verify_odds.py` to reproduce.

```
✓ 15 upcoming MLB events        quota: 500 remaining / 0 used
✓ Event: Toronto Blue Jays @ Boston Red Sox
    id=e7cd26360ce2edd30f37cdfc01391fd5   commence_time=2026-07-25T20:11:00Z
✓ Game lines (DraftKings): h2h BOS -109 | TOR -110 · totals O/U 7.5 -110
✓ pitcher_strikeouts: Dylan Cease 7.5 · Sonny Gray 4.5 (O -137 / U +108)
✓ batter_total_bases: 7 players
```

Player props **are** available on this key — an earlier note claiming they were
paid-tier-only was wrong. Quota is 500/month; `get_events()` is free and each
build costs roughly one credit per prop market.

---

## 4. ✅ The strikeout model — resolved

The model claimed **+2.00 K edge and +36% EV** on Sonny Gray against a
DraftKings line of 4.5. Treated as a bug report, it was three bugs.

**1. Innings were read as decimals.** `ip` is baseball notation — `6.1` is six
and one *third*, not six and one tenth. Summing the column lost a third of an
inning per partial start: across the team's 2026 starts it understated the
total by **13.5 IP** and inflated every K/9 by ~2.7%. `ip_outs` is the
unambiguous field. `analysis.betting._innings()` now derives from it.

**2. The projection compounded recency.** It blended K/9 across season and
last-5, then multiplied by the **last-5 innings alone** — so a pitcher who was
both striking out more *and* going deeper had two hot streaks multiplied
together. Innings are now blended with the same weights, and that weight comes
from the innings behind the rolling split rather than a flat 0.6 on ~30 innings.

**3. EV came from an invented constant.** The 0.12-win-probability-per-K
sensitivity was never fitted to anything, and it anchored on the book's own
de-vigged price, so the model could never truly disagree with the market. It is
now a Poisson distribution around the projection, which also handles pushes on
whole-number lines.

### ⚠️ The old leading hypothesis was wrong — do not chase it again

The previous handoff said Gray was probably on a short leash and the book was
pricing ~4 innings. **The game logs refute this.** His last five starts are
21, 22, 18, 18 and 18 outs — a full, healthy workload.

The real explanation is simpler and worth internalising:

| | |
| :--- | ---: |
| Gray's actual season rate | **5.00 K/start** over 18 starts |
| DraftKings' de-vigged implied expectation | **~4.9 K** |
| Old model | 6.50 |
| Fixed model | 5.66 |

**The book was right.** Its number matched the pitcher's season rate almost
exactly. The model was chasing five starts of noise.

### The model's error bar — the number that matters

A walk-forward backtest (project each start using only the starts before it,
71 held-out starts) gives:

```
total RMSE            2.63 K
irreducible Poisson   2.20 K     <- a perfect projection would still scatter this much
model's own error     1.43 K     <- MODEL_ERROR_K in analysis/betting.py
```

**Nothing smaller than 1.43 K is a signal.** That is also the honest ceiling on
any edge this model can claim to have found.

### ⛔ The model no longer calls sides — this is deliberate

Look at the two thresholds in `analysis/betting.py` together:

```python
MIN_EDGE_K           = MODEL_ERROR_K   # 1.43 — floor: clear your own noise
MAX_PLAUSIBLE_EDGE_K = 1.5             # ceiling: past here you are a bug
```

**They are almost the same number.** Any edge big enough to clear this model's
noise floor is already big enough to look implausible against a liquid market,
so there is no honest window left to recommend from. The K table therefore
publishes the projection, the line, and the gap — and **no bet**. Rows inside
the error bar read `NO CALL ⚖️` and publish no EV; rows past the ceiling read
`REVIEW ⚠️`.

That is not a bug, it is the accurate description of a model with ±1.43 K of
error. Cory chose this over shipping recommendations the backtest cannot
support. The band is written as two named constants rather than switched off,
so **recommendations resume on their own once `MODEL_ERROR_K` is re-measured
lower** — but only after the accuracy actually improves.

The backtest also found that **no weighting scheme meaningfully beat a plain
season average** (MAE 2.03–2.06 across every variant tried). Do not spend
effort tuning the blend weights; the return is not there.

### Which pitcher markets this key actually returns

Probed one market at a time against the live BOS/TOR event on 2026-07-25
(7 credits). Result:

| Market | Status |
| :--- | :--- |
| `pitcher_strikeouts` | ✅ in use |
| `pitcher_outs` | ✅ available — **see below** |
| `pitcher_hits_allowed` | ✅ available |
| `pitcher_walks` | ✅ available |
| `pitcher_earned_runs` | ✅ available |
| `pitcher_strikeouts_alternate` | ✅ available (long-odds ladder, one-sided) |
| `pitcher_record_a_win` | supported, no lines posted at probe time |
| `pitcher_saves` | ❌ **not a market on The Odds API** |

**There is no save market**, so a closer prop (the "Chapman save" idea) cannot be
built from this provider. `pitcher_record_a_win` is the nearest thing and was
empty when probed.

### 🔑 `pitcher_outs` independently validates half the model

DraftKings posted **Sonny Gray 17.5 outs, O -177 / U +132** — a de-vigged 59.7%
on the over, so the book expects roughly **6.0 IP**. The fixed model projects
**5.93 IP**. Those agree almost exactly.

That isolates the disagreement precisely. The innings half of the projection is
sound; the entire gap is in the strikeout *rate*:

| | K/9 |
| :--- | ---: |
| Model's blended rate | 8.59 |
| Gray's season rate | 7.97 |
| **What DK is pricing** (~4.9 K over ~6 IP) | **~7.35** |

The book is pricing Gray **below his own season rate** — which is exactly what
an opponent adjustment against a low-strikeout Toronto lineup would look like.
This is strong corroboration that roadmap item 1 is the missing piece, and it
means future work should target K/9, not innings.

`pitcher_outs` is also worth considering as a direct input: anchoring projected
innings on the market's own outs line would remove a source of model error
entirely. Cory has not decided on this.

### The one thing that would make this model useful again

The **missing opponent adjustment** (`roadmap.md` item 1) — there is still no
opponent K-rate, park, or platoon context. It is the highest-value remaining
work and the only obvious route to a smaller error bar. It needs opponent
batting data the fetcher does not currently cache.

Re-run the backtest (`walk-forward, project each start from prior starts only,
decompose RMSE against Poisson scatter`) after any modelling change, and update
`MODEL_ERROR_K` from the measurement — never by hand.

---

## 4b. ✅ The batter total-bases model — now measured too

This was the largest remaining piece of the same disease the strikeout model was
cured of. The old version called `OVER 1.5 🔥` whenever a projection cleared 1.65
or a ten-game hit rate cleared 60%. **The 1.5 was invented** — no book price, no
edge, no EV — and both thresholds were picked by hand.
`OddsAPIClient.batter_total_base_lines()` had existed and been tested for weeks,
returning real DraftKings lines, and was called by nothing.

### What changed

1. **Real lines.** `fetch_book_lines()` makes one trip to the provider for the
   whole page and hands both markets to the models, which is also the only
   sane place to log the snapshot from.
2. **The edge is in probability, not bases.** Every hitter is posted at 1.5;
   DraftKings had seven of them at 1.5 with prices from +124 to +152. The book
   moves the *price*, so "projection minus line" would have ranked hitters by
   quality the price already charges for — which is exactly what the old
   `proj_tb >= 1.65` rule was doing. The model compares its own
   over-probability to the de-vigged price.
3. **A distribution, not a point estimate.** Total bases are not Poisson — a
   home run pays four at once — so the model convolves per-plate-appearance
   outcomes (out / 1B / 2B / 3B / HR) and mixes over how often the hitter has
   had each number of appearances.
4. **Starts only.** A prop is offered on a hitter who is *in the lineup*. The old
   model averaged over bench and pinch-hit games, dividing every regular's
   production by games they never batted in.
5. **Rates regressed to the team's own.** A hitter's per-PA mix is shrunk toward
   the team's measured mix with a 50-PA prior — swept out of sample, not chosen.

### The error bar — measured, and it says the same thing

`python scripts/backtest_batter_tb.py` reproduces all of this: walk-forward over
the 2026 cached starts, projecting each start from only the starts before it, 714
held out.

```
parameter noise (bootstrap)   0.049   <- MODEL_ERROR_TB_PROB, in probability
calibration resolution        0.043       (measured gap 0.032, below its own
                                            noise floor — so unresolvable finer)
demonstrated information      0.051   <- MAX_PLAUSIBLE_EDGE_TB_PROB
                                          (recalibration slope 0.74 x sd 0.069)
AUC                           0.57    <- 0.50 is a coin flip
Brier skill vs the base rate  +0.012
```

**The floor and the ceiling nearly meet again** — 4.9 points of noise against 5.1
points of demonstrated opinion — so the total-bases table publishes the line,
both probabilities and the gap, and **no bet**, exactly as the strikeout table
does. Rows inside the band read `NO CALL ⚖️`; rows past the ceiling read
`REVIEW ⚠️` and publish no EV. On 2026-07-25 Wilyer Abreu came out `NO CALL`
(+2.4 points) and Ceddanne Rafaela `REVIEW` (+6.4 points).

That the two models arrived at the same shape independently is worth noting: it
is what a model with no opponent, park or platoon context looks like when it is
honestly measured against a market that has all three.

The backtest also found that recency weighting buys nothing here either — the
0.4-season / 0.6-last-10 blend was *worse* out of sample (MAE 1.297) than a plain
season rate (1.281). Do not spend effort tuning blend weights on this page.

---

## 4c. ✅ The rest of the page

- **First 5 Innings.** The `OVER 4.5 🟢` call is gone. It compared a prorated
  full-start ERA — not a measured first-five split, as the code comment already
  admitted — against a 4.5 no book had quoted. The estimate is still published
  and labelled as an estimate. A separate bug went with it: an unreadable ERA
  used to fall back to a flat **4.00**, inventing a number in precisely the
  situation where the page knew nothing. It now reports nothing.
- **Home runs / RBI.** The `🚀 HIGH` badge (two homers in ten games, or one per
  18 PA) is gone; the section is labelled as the usage-and-form leaderboard it
  always was. The rates underneath are fine and were kept.
- **Market vs model, rendered.** Both prop tables now show the book's de-vigged
  probability beside the model's, and — because a fourteen-column table on a
  390px phone hides everything past column two — repeat it in prose above the
  table.

---

## 5. What the code does now

- `client/odds_api_client.py` — The Odds API v4 wrapper, confirmed against a
  live payload. `_parse_player_lines()` carries the bookmaker's `last_update`
  through. `batter_total_base_lines()` is finally wired up.
- `client/odds_math.py` — conversion, de-vig, EV. Unchanged.
- `analysis/betting.py` — `fetch_book_lines()` (one provider trip for the whole
  page), `_innings()`, `_poisson_over_push()`, `_prop_ev()`, the strikeout guard
  and its constants; `project_batter_tb()`, `_tb_pmf()`, `_pmf_over_push()` and
  the total-bases guard and its constants.
- `data/odds_history.py` — append-only snapshot log and `line_movement()`.
- `scripts/backtest_batter_tb.py` — the measurement behind the total-bases
  constants. Re-run it after any change to that model and copy what it prints.
- `betting_report.py` — timestamp banner, movement notes, the model-vs-market
  read, REVIEW states, error-bar notes.
- `client/draftkings_client.py` — dormant, 403-blocked. Leave it alone.

**230 tests, all passing, fully offline** (`pytest`, ~0.7s).

> Environment note: this repo's deps have gone missing from the system Python
> before now, and `pip install -r requirements.txt` fixes it. Pandas imports also
> emit NumPy 1.x/2.x ABI warnings from system numexpr/bottleneck; they are noise.

---

## 6. Deployment

GitHub Pages serves a file, so the page shows odds **as of its last build**.

1. ✅ **Lines are timestamped.** The page prints "Lines as of HH:MM UTC" from
   the bookmaker's `last_update`, plus its own build time, and says the odds do
   not update after publication. When the book sends no timestamp it says so
   rather than inventing one.
2. ✅ **Builds run near first pitch.** `refresh.yml` runs at 07:00, 12:00, 15:00
   and 17:30 ET — a build within ~90 minutes of every common start time. At 2
   credits a build that is ~240/month against the 500 quota, up from ~120 now
   that total bases is priced as well.
3. ✅ **The repo secret is set.** CI builds with real lines.
4. ⚠️ **Check the history file is actually being committed.** `refresh.yml` now
   runs `git add data/cache/odds_history.parquet` alongside `docs/`; before that
   line the runner would have taken a snapshot and thrown it away with the
   workspace. Confirm after the first scheduled run that the file grows — it is
   the one artefact on this page that cannot be reconstructed later.

---

## 7. Ground rules

- **Mobile first.** Verify at ~390px (`--window-size=390,N`). Chromium under
  snap cannot write to `/tmp` — screenshot into a non-hidden home directory.
- **Never sort games by `game_pk`.** Use `analysis.streaks.played_in_order()`.
- **Styling lives in `viz/theme.py`.** The validated contract is `CATEGORICAL`
  (the chart palette) — do not reorder or extend it; there is deliberately no
  5th hue. Badge classes are separate and safe to add to.
- **Never invent a number to fill a slot.** If data is unavailable, the page
  says so. This includes model constants: `MODEL_ERROR_K`, `MODEL_ERROR_TB_PROB`
  and `MAX_PLAUSIBLE_EDGE_TB_PROB` are all outputs of a backtest, and the last
  two are printed by `scripts/backtest_batter_tb.py`. Any new threshold needs the
  same treatment or it does not ship.
- **Treat "our model beat the market" as a bug report.** It was right twice.
- Run `pytest` before committing. Each test class docstring names the bug it
  guards against; keep that convention.
