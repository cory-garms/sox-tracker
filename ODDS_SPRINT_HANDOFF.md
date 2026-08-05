# 🎲 Odds — Handoff for the Next Agent

> Rewritten **2026-07-27** at the end of the market-pricing sprint. General
> project state lives in [HANDOFF_GUIDE.md](HANDOFF_GUIDE.md); the prioritised
> backlog lives in [ODDS_PAGE_PLAN.md](ODDS_PAGE_PLAN.md). This document is what
> you need to not break anything.

---

## 1. TL;DR

The page no longer relies on its own models to be right about anything.

The two prop models — strikeouts and batter total bases — still decline to call
sides, which remains the accurate description of what they can prove. What
changed on 2026-07-27 is that the page acquired a source of edge that does not
route through a model at all: **every US book is now priced against every other
one**, and **promotions are valued exactly**. On the first live night the
consensus found nothing mispriced across 32 selections, which is the correct
result for a retail bettor at a liquid book and is what the page now says.

The betting side also became its own interface: a mode switch at the top of the
site, and three pages behind it — a board you read in the ninety seconds before
a bet, a models page, and a method page nobody has to read.

There is now a real measurement loop. Bets are logged, closing prices are
captured near first pitch, and CLV is computed. **That loop, not the models, is
the thing to protect.**

---

## 2. The rule this repo runs on

Unchanged, and every mistake made during this sprint was a violation of it:

> **A number is only published when something real stands behind it.** A
> projection is real work; an edge requires a line a book actually quoted; a
> *recommendation* requires the model's error to have been measured against
> held-out data and to be smaller than the edge claimed.

Corollary that bit repeatedly on 2026-07-27: **only identical bets are
comparable.** An Over 10.0 is not an Over 9.5. A pre-game price is not an
in-play price. A 34-minute-out snapshot is not a close.

---

## 3. The API key and the budget

`ODDS_API_KEY` lives in **`.env`** (gitignored, untracked) and as a GitHub
Actions secret. `config.py` loads it with `python-dotenv(override=False)` so a
real environment variable always beats the file. Never print or paste the value.

**The Odds API bills per market × region, never per bookmaker.** Verified
against the `x-requests-last` header: a one-book and a six-book request for the
same market each cost exactly 1 credit. This is why `all_books=True` is the
default on `OddsAPIClient` and why the consensus table is free.

```
refresh.yml   3 credits x 4 builds/day       = 12/day
close.yml     4 credits x ~1 capture/day     =  4/day
                                              ~480/month against 500
```

Cory's stated position (2026-07-27) is that the quota is **not** the binding
constraint and the plan tier can be upgraded if the CLV record justifies it. Do
not contort a design to save a credit. Do still count them before adding a
market, because 480/500 leaves little room for manual runs.

---

## 4. What exists now — the map

### Pages (all under the "Gambling Takes" mode switch)

| Page | File | What it is |
| :--- | :--- | :--- |
| Tonight's Board | `tonights_board_BOS_2026.html` | Movers, your position vs the close, consensus, promos, quoted props at a glance |
| Models & Method | `models_BOS_2026.html` | The strikeout and TB models, F5, NRFI, usage/form |
| How This Works | `method_BOS_2026.html` | Every methodological note, collected automatically |
| Today's Matchup | `matchup_BOS_2026.html` | Probables, platoon splits, first pitch |

`betting_BOS_2026.html` is a redirect stub; the URL was public for months.

**Navigation is generated from one place** — `viz/theme.PAGES` plus
`theme.nav_bar()`. It was previously five pasted copies of one link. Add a page
by registering it there; tests enforce that generators, the index and the
registry agree.

### Modules added 2026-07-27

| File | Purpose |
| :--- | :--- |
| `data/bet_log.py` | Bets (real and paper), graded against the close; CLV summary |
| `data/opponent.py` | League-wide hitting **game logs**, opponent K factor |
| `scripts/capture_close.py` | Near-close odds capture, gated on a free schedule read |
| `scripts/backtest_pitcher_k.py` | Walk-forward K backtest; prints `MODEL_ERROR_K` |
| `scripts/measure_early_win_lift.py` | Measures the early-win token's value |
| `scripts/merge_odds_history.py` | **Lossless** union of two odds histories |
| `scripts/log_bet.py` | CLI: log, grade, summarise |
| `.github/workflows/close.yml` | Runs the capture every 20 min in MLB's start window |

---

## 5. Things that will bite you

### 5a. Never resolve an `odds_history.parquet` conflict by picking a side

It is committed from three directions (page builds, closing capture, local runs)
and **cannot be reconstructed**. `--ours`, `--theirs`, `git checkout` and
`-X theirs` all destroy data: merging the two versions in flight on 2026-07-27
gave 193 rows where one side had 159 and the other 162.

```bash
git show :2:data/cache/odds_history.parquet > /tmp/ours.parquet
git show :3:data/cache/odds_history.parquet > /tmp/theirs.parquet
python scripts/merge_odds_history.py /tmp/ours.parquet /tmp/theirs.parquet
git add data/cache/odds_history.parquet
```

### 5b. In-play prices are in the log, on purpose

Every build snapshots, and builds run during games. Anything that compares
prices over time **must** go through `odds_history.pre_game_only()`. Skipping it
reported Yoshida −101 → +155 as a 10.2-point line move; it was a lineup having
batted. Movers, `line_movement()` and grading all filter; new consumers must too.

### 5c. `board_` is a substring of `dashboard_`

Which is why the file is `tonights_board_BOS_2026.html`. Matching page filenames
by containment produced two failures in one sitting — a nav test false positive
and a `sed` that rewrote `dashboard_` into `dashtonights_board_`. **Match on
`href="…"` exactly.**

### 5d. Grading must keep re-running

`grade_from_history()` deliberately has no "already graded, skip" guard. The
last pre-game snapshot improves as first pitch approaches and then freezes
forever. Re-adding that guard would pin whichever early snapshot landed first
and present it as final.

### 5e. The Odds API's coverage is not the book's offering

DraftKings prices home runs; the feed does not carry that market. Do not
conclude a market does not exist because the payload lacks it — check the app.

### 5f. A silent `.get()` fallback adjusted for the wrong opponent for weeks

`betting_report` read tonight's opponent as `preview["opponent"]["id"]`. The
preview has never had a nested `opponent` dict — the key is **`opponent_id`,
flat** — so the lookup returned `None` on every build and fell through to a
fallback that uses *the last game in the cache*.

Which is right for as long as a series is in progress, and wrong on exactly the
day a series turns over. Fixed 2026-08-05, after it applied a Dodgers K rate
(factor 0.933) to a White Sox game (1.066) and produced an UNDER call at
+18.2% EV that the correct factor does not support — a 0.66 K swing in the
projection. Nothing was staked on it.

Two lessons worth more than the fix:

- **A fallback that cannot announce itself hides the bug it is covering.** This
  one had a perfectly reasonable comment above it saying it existed for when the
  opponent "cannot be resolved". It ran every single time.
- **A blunt model hides its own input errors.** It survived this long because the
  page recommended nothing regardless of the factor. The week the model started
  calling sides is the week the bug produced a bet. Expect more of these now that
  inputs actually move the output — `tests/test_opponent_resolution.py` pins this
  one.

---

## 6. Measured constants — outputs, never settings

| Constant | Value | Measured by |
| :--- | ---: | :--- |
| `MODEL_ERROR_K` | **0.45** K | `scripts/backtest_league_k.py`, 2,347 held-out starts |
| `MAX_PLAUSIBLE_EDGE_K` | 1.5 K | ceiling; above it the model is reporting a bug |
| `MODEL_ERROR_TB_PROB` | 0.049 | `scripts/backtest_batter_tb.py`, 714 held-out starts |
| `EARLY_WIN_LIFT_2RUN` | **+0.1028** | `scripts/measure_early_win_lift.py`, 3,172 team-games |

**The recommendation window is 0.45 → 1.5 K.** As of 2026-08-04 the strikeout
page calls sides for the first time. Nothing in the gating logic changed to
allow that — only the measurement did, exactly as this section previously said
it would. Recommendations must never resume by editing the constant.

### The opponent adjustment does work — the old test could not see it

This section previously read "the opponent adjustment did not work", on the
strength of a backtest over 73 Boston starts where baseline and adjusted both
measured 1.39 K. **That conclusion was an artefact of the sample size**, and the
note recording it said as much without acting on it.

`pitcher_strikeout_model` projects a starter from his own game log and knows
nothing about Boston, so it can be backtested on every starter in the league:
2,347 held-out starts instead of 73, standard error ±0.12 K instead of ±0.41 K.
On that sample, as a paired bootstrap over the same starts (95% CI on the MSE
gap, K²):

```
the last-5 term earned nothing        blend vs season      [-0.018, +0.058]
regression to the league mean helps   blend vs marcel      [+0.114, +0.308]
the opponent factor helps             marcel vs marcel+opp [+0.016, +0.121]
the change as a whole                 blend vs marcel+opp  [+0.167, +0.383]
```

So the shipped model became **Marcel + opponent factor**: the pitcher's own K/9
regressed toward the league mean by the innings behind it, times the opponent
factor, times his innings per start. The season/last-5 blend is retired — it was
never better than a plain season average.

**Two traps this uncovered, both worth remembering:**

1. **`scripts/backtest_pitcher_k.py` cannot referee a modelling decision.** At 80
   starts its standard error is ±0.4 K; it reported the model error as 1.43,
   1.39 and 1.26 across runs that changed nothing. It no longer sets
   `MODEL_ERROR_K` and is kept only as a per-team sanity check.
2. **Do not bootstrap a CI on `model_err` directly.** It is
   `sqrt(max(0, mse - poisson))`, and mse (~5.24) sits barely above the Poisson
   floor (~4.97), so resamples routinely clip at zero and the CI's lower bound
   comes back as exactly `+0.00000` under every seed. That artefact hid a real
   effect. Compare on **MSE**, which has no clip; `paired_ci` does.

---

## 7. The measurement loop — protect this

1. `python scripts/log_bet.py --selection … --price … --stake …` (stake 0 = paper, grades identically)
2. `close.yml` captures the last pre-game price automatically
3. `python scripts/log_bet.py --grade` then `--summary`

**CLV needs ~20 graded bets before its sign means anything.** As of 2026-07-27
there are 10, at 20% beat-close and −0.38 mean points, which is an anecdote and
the page says so.

Known weakness: "closing" means the last price observed. The gate fires between
35 and 2 minutes before first pitch, so it is close but not the true close.

---

## 8. What the first live night actually found

Boston at Athletics, 2026-07-27. 32 selections across 14 prop and 6 game markets,
priced against up to 8 books.

- **Nothing was mispriced.** Best raw price on the board was −0.98%.
- **The only positive expectation came from a promotion.** A 50% profit boost on
  the longest fairly-priced leg was +25.4%; everything else was paying vig.
- A profit boost pays `(1+b)·EV_raw + b·(1−p)`, so it belongs on the **longest**
  fairly-priced selection, not the safest.
- Cory's position: 3.75U across 7 bets, expected +0.14U — carried entirely by
  the boost. The four unboosted props cost −0.13U in expectation.

That result is the honest baseline. A future sweep that finds a large edge
against 8 books is more likely a bug than an opportunity — check the line, the
timestamp, and whether you are comparing identical bets.

---

## 9. Open work

Highest value first. Full detail in [ODDS_PAGE_PLAN.md](ODDS_PAGE_PLAN.md).

1. **Lineup cross-check.** Nick Kurtz carried a +117 total-bases prop on
   2026-07-27 while not in the posted lineup, and nothing flagged it. One free
   MLB call. This is a live trap, not a hypothetical.
2. **Accumulate CLV to n≈20** before touching either model. This is the only
   thing that can lower an error bar honestly.
3. **Parlays cannot be graded.** Logged as one row across four markets; the
   grader works per selection. Grade the legs, treat the parlay EV separately.
4. **A multi-season K backtest** — the only way to settle whether the opponent
   adjustment helps.
5. **Park factors** (`roadmap.md` 3c) — still nothing. Sutter Health Park is a
   converted Triple-A stadium and the model has no idea.

### Deliberately not doing

- Lowering an error constant to make the page speak.
- More prop markets for breadth. Validated accuracy is the constraint.
- Anchoring a projection on the book's own numbers — that circularity was the
  original bug.
- Parlays or Kelly staking on models that cannot justify one side.

---

## 10. House style

- **Mobile first, verified.** Every UI change is checked at 390px in headless
  chromium, not eyeballed on a desktop. Doing this caught EV columns hidden
  behind a swipe.
- **Text is a cost.** The board was once 53% prose by word count. Methodology
  goes on the method page via `_method()`; the board keeps a one-line pointer.
  A justification nobody reads is decoration, not honesty.
- **Say what is not known.** Every page states when its prices were read, and
  whether they are provisional.
