# 🎲 Sports Betting & Prop Intelligence Roadmap — `sox_tracker`

A strategic feature roadmap for transforming **`sox_tracker`** into an elite pre-game betting intelligence & prop model suite.

---

## 🎯 1. Player Prop Betting Intelligence

### ⚾ Pitcher Strikeout Over/Under Model (`O/U K's`)
- **Opposing Lineup K-Rate Matching**: Compare starting pitcher K/9 against opposing team strikeout rates vs. RHP/LHP over the last 15 games.
- **Pitch Count & Innings Limit Predictor**: Projected strikeouts based on pitch-count limits, 3-day rest, and 5-start rolling K% per 100 pitches.

### 💥 Batter Total Bases (TB) & Home Run Props
- **Pitch Type Matchup Matrix**: Match batter pitch-type OPS (e.g., Devers vs. 4-Seam Fastballs > 95mph) against opposing starter's pitch mix via Baseball Savant Statcast.
- **Stadium & Park Factor Adjustments**: Factor in Fenway Park Green Monster HR/2B park factors vs. road venue dimensions.

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
- **Contextual O/U Hit Rates**: Track Over/Under trends for Day vs. Night games, Home vs. Away, and Weather/Wind factors.

---

## 🚀 4. Proposed 5th HTML Page: `betting_BOS_2026.html`

A standalone interactive Plotly page (`betting_report.py`) featuring:
1. **Top +EV Prop Recommendations** (Pitcher K's, Batter TB, NRFI).
2. **First 5 Innings (F5) Starter Matchup Card**.
3. **Over/Under & Moneyline Trend Dashboard**.
