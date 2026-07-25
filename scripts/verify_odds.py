#!/usr/bin/env python
"""
Diagnostic for the live odds pipeline. Run this the moment you have a key:

    export ODDS_API_KEY="..."
    python scripts/verify_odds.py

It answers, in order, the four things that can go wrong — and prints the raw
payload shape when parsing fails, so a mismatch is obvious rather than silent:

  1. Is the key accepted?
  2. Which markets does THIS plan actually include? (props are paid-tier)
  3. Does find_event() locate today's Red Sox game?
  4. Does the parsing turn the payload into usable lines?

Exits non-zero if the pipeline can't produce lines, so it can gate a build.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from client.odds_api_client import (
    MARKET_BATTER_TB,
    MARKET_H2H,
    MARKET_PITCHER_KS,
    MARKET_TOTALS,
    OddsAPIClient,
    OddsAPIError,
    _parse_player_lines,
)

TICK, CROSS, WARN = "✓", "✗", "!"


def head(text: str) -> None:
    print(f"\n{'=' * 68}\n{text}\n{'=' * 68}")


def main() -> int:
    client = OddsAPIClient(bookmaker=config.ODDS_BOOKMAKER)

    head("1. Key")
    if not client.configured:
        print(f"{CROSS} ODDS_API_KEY is not set.")
        print("  Get a free key at https://the-odds-api.com/ then:")
        print('    export ODDS_API_KEY="..."')
        return 1
    print(f"{TICK} Key present (…{client.api_key[-4:]}), bookmaker={client.bookmaker}")

    head("2. Events + quota")
    try:
        events = client.get_events()
    except OddsAPIError as e:
        print(f"{CROSS} {e}")
        return 1
    except Exception as e:
        print(f"{CROSS} Unexpected error: {type(e).__name__}: {e}")
        return 1

    print(f"{TICK} {len(events)} upcoming MLB events")
    print(f"  quota: {client.requests_remaining} remaining / {client.requests_used} used")
    if events:
        print("  sample event keys:", sorted(events[0].keys()))

    head("3. Locate today's game")
    event = client.find_event(config.TEAM_NAME, events)
    if not event:
        print(f"{CROSS} No upcoming event matched {config.TEAM_NAME!r}.")
        print("  Team names the provider is returning:")
        for ev in events[:8]:
            print(f"    {ev.get('away_team')} @ {ev.get('home_team')}  ({ev.get('commence_time')})")
        print("  -> if the name differs, that's a find_event() matching problem.")
        return 1
    print(f"{TICK} {event.get('away_team')} @ {event.get('home_team')}")
    print(f"  id={event.get('id')}  commence_time={event.get('commence_time')}")

    head("4. Game-level markets (free tier)")
    game_ok = False
    try:
        odds = client.get_game_odds(markets=f"{MARKET_H2H},{MARKET_TOTALS}")
        ours = [o for o in odds if o.get("id") == event["id"]]
        if not ours:
            print(f"{WARN} Odds returned, but none for our event id.")
        for o in ours:
            for book in o.get("bookmakers", []):
                print(f"  book: {book.get('title')}  (updated {book.get('last_update')})")
                for m in book.get("markets", []):
                    label = m.get("key")
                    prices = [
                        f"{oc.get('name')}"
                        + (f" {oc.get('point')}" if oc.get("point") is not None else "")
                        + f" @ {oc.get('price')}"
                        for oc in m.get("outcomes", [])
                    ]
                    print(f"    {label}: {'  |  '.join(prices)}")
                    game_ok = True
        print(f"{TICK} Game-level markets available" if game_ok
              else f"{CROSS} No game-level markets parsed")
    except OddsAPIError as e:
        print(f"{CROSS} {e}")
    except Exception as e:
        print(f"{CROSS} Unexpected: {type(e).__name__}: {e}")

    head("5. Player prop markets (paid tier on most plans)")
    props_ok = False
    for market, label in ((MARKET_PITCHER_KS, "pitcher strikeouts"),
                          (MARKET_BATTER_TB, "batter total bases")):
        payload = client.get_event_props(event["id"], markets=market)
        if not payload:
            print(f"{WARN} {label}: unavailable on this plan (or no lines posted yet)")
            continue
        parsed = _parse_player_lines(payload, market)
        if parsed:
            props_ok = True
            print(f"{TICK} {label}: {len(parsed)} players")
            for name, entry in list(parsed.items())[:6]:
                print(f"    {name}: {entry['line']} "
                      f"O {entry.get('over_odds')} / U {entry.get('under_odds')} "
                      f"({entry.get('book')})")
        else:
            print(f"{CROSS} {label}: payload returned but parsed to nothing — "
                  "the response shape does not match _parse_player_lines()")
            print("  raw payload (truncated):")
            print("  " + json.dumps(payload)[:900])

    head("Verdict")
    print(f"  game-level lines : {'YES' if game_ok else 'NO'}")
    print(f"  player prop lines: {'YES' if props_ok else 'NO'}")
    if props_ok:
        print("\n  -> betting_report.py will show real prop lines, edge, and EV.")
    elif game_ok:
        print("\n  -> Game-level markets work; props need a paid tier. The K table")
        print("     will keep reporting 'No line available', which is correct.")
    else:
        print("\n  -> No usable lines. Do not expect odds on the page.")
    return 0 if (game_ok or props_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
