"""
Walk-forward backtest of the win-probability baseline.

Every game is projected using only the games played before it — both teams'
runs totalled as of the morning of, the way `scripts/backfill_predictions.py`
truncates its inputs. Nothing here reads today's standings, because today's
standings contain the result of every game being projected.

What it reports, and the order matters: how the model does against *outcomes*
first, and only then how it does against the *market*. There are 131 games with
a result and 28 with a stored moneyline, so the first question has a real
sample and the second does not. A conclusion drawn from 28 games about a market
this liquid would be noise wearing a number.

Usage:
    python scripts/backtest_win_probability.py --min-prior 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

import config  # noqa: E402
from analysis import scoring  # noqa: E402
from analysis.win_probability import win_probability  # noqa: E402
from client.mlb_client import MLBClient  # noqa: E402
from client.odds_math import no_vig_probability  # noqa: E402
from data import league_games as lg  # noqa: E402
from data import odds_history  # noqa: E402


def market_probabilities(team_name: str) -> dict[str, float]:
    """
    De-vigged win probability per event, from the last pre-game moneyline.

    Averaged across every book that priced it: one book's number is that book's
    opinion plus its margin, and the consensus is the benchmark the rest of this
    project already measures against.
    """
    hist = odds_history.load_history()
    if hist.empty:
        return {}
    h = hist[hist["market"] == "h2h"]
    if h.empty:
        return {}
    h = h[h["captured_at"].astype(str) < h["commence_time"].astype(str)]

    out: dict[str, float] = {}
    for event_id, g in h.groupby("event_id"):
        last = g[g["captured_at"] == g["captured_at"].max()]
        fair = []
        for book, bg in last.groupby("book"):
            mine = bg[bg["player"] == team_name]
            theirs = bg[bg["player"] != team_name]
            if mine.empty or theirs.empty:
                continue
            a, b = mine.iloc[0]["over_odds"], theirs.iloc[0]["over_odds"]
            if pd.isna(a) or pd.isna(b):
                continue
            fair.append(no_vig_probability(a, b)[0])
        if fair:
            out[str(event_id)] = sum(fair) / len(fair)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=config.SEASON)
    ap.add_argument("--min-prior", type=int, default=20,
                    help="games each side must have played before it is projected")
    args = ap.parse_args()

    client = MLBClient()
    league = lg.load_league_games(args.season, client=client)
    if league.empty:
        print("No league games cached; run with a client that can reach the API.")
        return 1

    games = pd.read_parquet(config.CACHE_DIR / f"games_{config.TEAM_ID}_{args.season}.parquet")
    games = games[games["result"].notna()].sort_values(["game_date", "game_number"])

    preds, actual, rows = [], [], []
    for r in games.itertuples():
        date = str(r.game_date)
        rs, ra, n = lg.team_runs_before(league, config.TEAM_ID, before=date)
        ors, ora, on = lg.team_runs_before(league, int(r.opponent_id), before=date)
        if n < args.min_prior or on < args.min_prior:
            continue
        p = win_probability(rs, ra, n, ors, ora, on, is_home=bool(r.is_home))
        if p is None:
            continue
        won = 1 if str(r.result).upper().startswith("W") else 0
        preds.append(p); actual.append(won)
        rows.append({"game_date": date, "opponent_id": int(r.opponent_id),
                     "is_home": bool(r.is_home), "model_p": p, "won": won})

    if not preds:
        print("Nothing to score.")
        return 1

    frame = pd.DataFrame(rows)
    print(f"=== against OUTCOMES · {len(preds)} games "
          f"(min {args.min_prior} prior games each side) ===")
    print(f"  base rate (actual win%)  : {sum(actual)/len(actual):.4f}")
    print(f"  mean projection          : {sum(preds)/len(preds):.4f}")
    print(f"  Brier                    : {scoring.brier(preds, actual):.4f}")
    print(f"  Brier of always-base-rate: {scoring.brier([sum(actual)/len(actual)]*len(actual), actual):.4f}")
    disc = scoring.discrimination(preds, actual)
    print(f"  AUC                      : {disc.get('auc', float('nan')):.4f}")
    cal = scoring.calibration(preds, actual, bins=4)
    print(f"  recalibration slope      : {cal.get('slope', float('nan')):+.3f}")
    print(f"  {scoring.sample_verdict(len(preds))}")

    # --- and only now, the market ---
    team_name = config.TEAMS.get(config.TEAM_ABBR, {}).get("name", config.TEAM_NAME)
    market = market_probabilities(team_name)
    if not market:
        print("\n=== against the MARKET ===\n  No stored moneylines to compare against.")
        return 0

    games_by_date = {}
    hist = odds_history.load_history()
    h = hist[hist["market"] == "h2h"][["event_id", "commence_time"]].drop_duplicates()
    for r in h.itertuples():
        games_by_date.setdefault(str(r.commence_time)[:10], str(r.event_id))

    paired = [(row["model_p"], market[games_by_date[row["game_date"]]], row["won"])
              for _, row in frame.iterrows()
              if row["game_date"] in games_by_date
              and games_by_date[row["game_date"]] in market]
    print(f"\n=== against the MARKET · {len(paired)} games ===")
    if len(paired) < 5:
        print("  Too few overlapping games to say anything. Recorded, not concluded.")
        return 0
    mp = [p for p, _, _ in paired]; kp = [k for _, k, _ in paired]; y = [w for _, _, w in paired]
    vs = scoring.versus_market(mp, kp, y)
    print(f"  model Brier  : {vs.get('model_brier', float('nan')):.4f}")
    print(f"  market Brier : {vs.get('market_brier', float('nan')):.4f}")
    gap = vs.get("gap")
    if gap is not None:
        print(f"  gap          : {gap:+.4f}  CI [{vs.get('ci_low', float('nan')):+.4f}, "
              f"{vs.get('ci_high', float('nan')):+.4f}]")
    print(f"  mean |model - market| : {sum(abs(a-b) for a,b in zip(mp,kp))/len(mp)*100:.2f} pts")
    print(f"\n  {len(paired)} games is not a verdict on a market this liquid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
