"""
The Odds API client — live sportsbook lines for MLB game markets and player props.

Wraps https://api.the-odds-api.com/v4/ with retry logic, rate limiting, and
quota tracking.  Requires a free API key from https://the-odds-api.com/ supplied
via the ODDS_API_KEY environment variable.

Why this exists: DraftKings' public sportsbook endpoints are served behind an
Akamai edge that returns 403 to non-browser clients regardless of headers or API
version, so they cannot be polled directly.  The Odds API aggregates DraftKings
(among other books) and is reachable with a key.

Endpoint reference: https://the-odds-api.com/liveapi/guides/v4/
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import REQUEST_TIMEOUT, REQUEST_DELAY

log = logging.getLogger(__name__)

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "baseball_mlb"

# Markets. Game-level markets come back on the main odds endpoint; player props
# are per-event and are gated to paid tiers on The Odds API.
MARKET_H2H = "h2h"
MARKET_TOTALS = "totals"
MARKET_SPREADS = "spreads"
MARKET_PITCHER_KS = "pitcher_strikeouts"
MARKET_BATTER_TB = "batter_total_bases"


class OddsAPIError(RuntimeError):
    """Raised when the odds provider cannot be used (missing key, quota, auth)."""


class OddsAPIClient:
    """Thin, stateful wrapper around The Odds API v4."""

    def __init__(
        self,
        api_key: str | None = None,
        bookmaker: str = "draftkings",
        all_books: bool = True,
    ) -> None:
        self.api_key = api_key or os.environ.get("ODDS_API_KEY", "")
        # `bookmaker` stays the book we actually bet at and price against; the
        # rest of the market is pulled only to benchmark it.
        self.bookmaker = bookmaker
        # The Odds API bills per market x region, never per bookmaker — verified
        # against the x-requests-last header on 2026-07-27, where a single-book
        # and a six-book request for the same market each cost exactly 1 credit.
        # Narrowing to one book therefore buys nothing and discards the only
        # benchmark on the page that does not depend on a model being right.
        self.all_books = all_books
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._last_call: float = 0.0
        # Populated from response headers after each call.
        self.requests_remaining: int | None = None
        self.requests_used: int | None = None

    @property
    def configured(self) -> bool:
        """True when an API key is present. Callers should degrade gracefully if False."""
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _get(self, path: str, params: dict | None = None) -> Any:
        if not self.configured:
            raise OddsAPIError(
                "ODDS_API_KEY is not set — get a free key at https://the-odds-api.com/"
            )

        self._throttle()
        url = f"{ODDS_API_BASE}{path}"
        query = {"apiKey": self.api_key, **(params or {})}
        log.debug("GET %s %s", url, {k: v for k, v in query.items() if k != "apiKey"})

        resp = self._session.get(url, params=query, timeout=REQUEST_TIMEOUT)
        self._last_call = time.monotonic()

        # Quota headers are returned on every successful call.
        self.requests_remaining = _safe_int(resp.headers.get("x-requests-remaining"))
        self.requests_used = _safe_int(resp.headers.get("x-requests-used"))

        if resp.status_code == 401:
            raise OddsAPIError("The Odds API rejected the key (401). Check ODDS_API_KEY.")
        if resp.status_code == 429:
            raise OddsAPIError("The Odds API quota exhausted (429). Try again next cycle.")
        if resp.status_code == 422:
            # Unsupported market for the current plan — caller decides whether that's fatal.
            raise OddsAPIError(f"The Odds API rejected the request (422): {resp.text[:200]}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Game-level markets
    # ------------------------------------------------------------------

    def get_events(self) -> list[dict[str, Any]]:
        """Upcoming MLB events (id, commence_time, home/away team). Costs 0 quota."""
        return self._get(f"/sports/{SPORT_KEY}/events") or []

    def get_game_odds(
        self,
        markets: str = f"{MARKET_H2H},{MARKET_TOTALS}",
        regions: str = "us",
        odds_format: str = "american",
    ) -> list[dict[str, Any]]:
        """Moneyline / totals / spreads for all upcoming MLB games."""
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
        }
        if not self.all_books:
            params["bookmakers"] = self.bookmaker
        return self._get(f"/sports/{SPORT_KEY}/odds", params) or []

    def find_event(
        self,
        team_name: str,
        events: list[dict] | None = None,
        upcoming_only: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """
        Next event involving `team_name` (e.g. "Boston Red Sox"). Matching is
        substring-based so "Red Sox" also works.

        `upcoming_only` skips events that have already started. The feed does
        not: measured 2026-08-27, /events listed a game 81 minutes underway and
        listed it *first*, because the ordering is by commence_time and a game
        stays until it settles rather than until it starts.

        On a single-game day that costs nothing -- there is one Red Sox event
        and it is the right one either way. On a split doubleheader it decides
        whether the nightcap gets a closing price at all: the opener carries the
        earlier commence_time, so it keeps being returned for as long as the
        provider lists it, and the caller reads a first pitch hours in the past
        and declines to capture. That failure prints the same line as a healthy
        skip. The next such date is 2026-08-29 at Yankee Stadium, games at 17:05Z
        and 23:15Z.

        Left off by default. The board wants whatever game is current, including
        one in progress; only the closing capture needs the game that has not
        started yet.
        """
        events = events if events is not None else self.get_events()
        needle = team_name.lower()
        now = now or datetime.now(timezone.utc)
        # The Odds API returns events in commence_time order.
        for ev in events:
            home = str(ev.get("home_team", "")).lower()
            away = str(ev.get("away_team", "")).lower()
            if needle not in home and needle not in away:
                continue
            if upcoming_only and not _starts_after(ev, now):
                continue
            return ev
        return None

    # ------------------------------------------------------------------
    # Player props (per-event; paid tiers only)
    # ------------------------------------------------------------------

    def get_event_props(
        self,
        event_id: str,
        markets: str = MARKET_PITCHER_KS,
        regions: str = "us",
        odds_format: str = "american",
    ) -> dict[str, Any]:
        """
        Player prop markets for a single event. Returns {} when the plan does not
        include props rather than raising, so the report can fall back cleanly.
        """
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
        }
        if not self.all_books:
            params["bookmakers"] = self.bookmaker
        try:
            return self._get(f"/sports/{SPORT_KEY}/events/{event_id}/odds", params) or {}
        except OddsAPIError as e:
            log.info("Player props unavailable for event %s: %s", event_id, e)
            return {}

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def pitcher_strikeout_lines(self, event_id: str) -> dict[str, dict[str, Any]]:
        """
        Map of pitcher name -> {"line": float, "over_odds": int, "under_odds": int}
        for the strikeout prop market. Empty dict when props aren't available.
        """
        payload = self.get_event_props(event_id, markets=MARKET_PITCHER_KS)
        return _parse_player_lines(payload, MARKET_PITCHER_KS, book=self.bookmaker)

    def batter_total_base_lines(self, event_id: str) -> dict[str, dict[str, Any]]:
        """Map of batter name -> line/odds for the total-bases prop market."""
        payload = self.get_event_props(event_id, markets=MARKET_BATTER_TB)
        return _parse_player_lines(payload, MARKET_BATTER_TB, book=self.bookmaker)


# ---------------------------------------------------------------------------
# Module-level parsing helpers
# ---------------------------------------------------------------------------

def _starts_after(event: dict, now: datetime) -> bool:
    """
    True when this event's first pitch is still ahead of `now`.

    An event with no parseable commence_time counts as upcoming. The only
    caller uses this to *skip* events, and dropping one on a malformed
    timestamp would turn a bad field into a missed capture; the window check
    downstream still refuses to spend on it.
    """
    raw = (event or {}).get("commence_time")
    if not raw:
        return True
    try:
        start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start > now


def _safe_int(val: Any, default: int | None = None) -> int | None:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def parse_player_lines_by_book(
    payload: dict, market_key: str
) -> dict[str, dict[str, dict[str, Any]]]:
    """
    Flatten The Odds API's bookmakers -> markets -> outcomes nesting into
    {player_name: {book_title: {"line": float, "over_odds": int,
                                "under_odds": int, "last_update": str}}}.

    Keying by book is the primitive rather than a detail: several books price
    the same player at different numbers, so collapsing them into one entry per
    player would blend a DraftKings line with a Bovada price and produce a quote
    that exists nowhere. Callers that want a single book should ask for it.

    `last_update` is the bookmaker's own ISO-8601 timestamp for when it last
    moved these prices. It is carried through because a statically built page
    can only ever show odds as of its last build, and must say which moment
    that was rather than implying the numbers are live.
    """
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for book in payload.get("bookmakers", []) or []:
        book_title = book.get("title", book.get("key", ""))
        book_updated = book.get("last_update")
        for market in book.get("markets", []) or []:
            if market.get("key") != market_key:
                continue
            # Market-level timestamps are more precise when present.
            updated = market.get("last_update") or book_updated
            for outcome in market.get("outcomes", []) or []:
                # `description` carries the player name; `name` is Over/Under.
                player = outcome.get("description") or outcome.get("name", "")
                if not player:
                    continue
                side = str(outcome.get("name", "")).lower()
                entry = out.setdefault(player, {}).setdefault(
                    book_title, {"line": None, "book": book_title, "last_update": updated}
                )
                point = outcome.get("point")
                if point is not None:
                    entry["line"] = float(point)
                if side == "over":
                    entry["over_odds"] = _safe_int(outcome.get("price"))
                elif side == "under":
                    entry["under_odds"] = _safe_int(outcome.get("price"))
    # Drop anything we couldn't pin a numeric line to.
    return {
        player: {b: e for b, e in books.items() if e.get("line") is not None}
        for player, books in out.items()
        if any(e.get("line") is not None for e in books.values())
    }


def parse_two_way_by_book(
    payload: dict, market_key: str = MARKET_H2H
) -> dict[str, dict[str, dict[str, Any]]]:
    """
    Same shape as parse_player_lines_by_book, for team markets like the
    moneyline where the two outcomes are team names rather than Over/Under.

    Each team is emitted as its own entry with `over_odds` set to its price and
    `under_odds` to the opposing team's, so a moneyline de-vigs through exactly
    the same two-sided path as a prop and needs no special case downstream.

    `line` carries the outcome's point where the market has one and is None
    where it does not. A moneyline genuinely has no number; a total and a spread
    very much do, and dropping theirs is not a simplification but a silent
    correctness bug. It produced one: on 2026-07-27 DraftKings posted a total of
    10.0 while six of eight books were on 9.5, and with the point discarded the
    consensus compared the two as the same bet and reported DK's Over as +0.27%
    EV. Priced against the two books actually on 10.0 it was -5.56%. The whole
    point of the consensus table is that only identical bets are comparable.
    """
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for book in payload.get("bookmakers", []) or []:
        title = book.get("title", book.get("key", ""))
        updated = book.get("last_update")
        for market in book.get("markets", []) or []:
            if market.get("key") != market_key:
                continue
            outcomes = [o for o in (market.get("outcomes") or []) if o.get("name")]
            if len(outcomes) != 2:
                continue          # three-way or malformed; nothing to de-vig against
            stamp = market.get("last_update") or updated
            for this, other in (outcomes, outcomes[::-1]):
                point = this.get("point")
                out.setdefault(str(this["name"]), {})[title] = {
                    "line": float(point) if point is not None else None,
                    "book": title,
                    "last_update": stamp,
                    "over_odds": _safe_int(this.get("price")),
                    "under_odds": _safe_int(other.get("price")),
                }
    return out


def _parse_player_lines(
    payload: dict, market_key: str, book: str = "draftkings"
) -> dict[str, dict[str, Any]]:
    """
    Single-book view of `parse_player_lines_by_book` — {player: line/odds} for
    the named book only. Matching is case-insensitive on both the API's key and
    its display title ("draftkings" and "DraftKings" both resolve).
    """
    needle = book.replace("_", " ").lower()
    result: dict[str, dict[str, Any]] = {}
    for player, books in parse_player_lines_by_book(payload, market_key).items():
        for title, entry in books.items():
            if title.replace("_", " ").lower() == needle:
                result[player] = entry
                break
    return result
