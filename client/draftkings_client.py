"""
DraftKings Sportsbook API Client for MLB odds and player prop intelligence.

Wraps DraftKings public sportsbook REST API v2 with rate limiting, retry logic,
odds conversion, and typed helpers. No API key required.
"""

from __future__ import annotations

import logging
import time
from typing import Any
import requests
import urllib3
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import REQUEST_TIMEOUT, REQUEST_DELAY

# Suppress insecure HTTPS request warnings when SSL fallback is triggered
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)

DK_BASE_URL = "https://sportsbook-us-ma.draftkings.com/sites/US-MA-SB/api/v2"
MLB_EVENT_GROUP_ID = 84240  # DraftKings MLB Event Group ID


# ---------------------------------------------------------------------------
# Odds Calculation Utilities
# ---------------------------------------------------------------------------

def american_to_implied_prob(odds: int | float) -> float:
    """Convert American Odds (e.g., -115 or +130) to Implied Win Probability (0.0 to 1.0)."""
    try:
        odds = float(odds)
        if odds < 0:
            return abs(odds) / (abs(odds) + 100.0)
        else:
            return 100.0 / (odds + 100.0)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0.50


def american_to_decimal(odds: int | float) -> float:
    """Convert American Odds to Decimal Payout Multiplier (e.g. +100 -> 2.0)."""
    try:
        odds = float(odds)
        if odds >= 0:
            return (odds / 100.0) + 1.0
        else:
            return (100.0 / abs(odds)) + 1.0
    except (ValueError, TypeError, ZeroDivisionError):
        return 2.0


def calculate_ev(model_prob: float, american_odds: int | float) -> float:
    """
    Calculate Expected Value percentage (+EV) given model true probability (0.0-1.0)
    and sportsbook American odds.
    Formula: EV = (Model Prob * Decimal Odds) - 1.0
    Returns EV percentage (e.g., 8.0 = +8% EV).
    """
    dec_odds = american_to_decimal(american_odds)
    ev = (model_prob * dec_odds) - 1.0
    return round(ev * 100.0, 2)


# ---------------------------------------------------------------------------
# DraftKings Client
# ---------------------------------------------------------------------------

class DraftKingsClient:
    """Thin, polite client for fetching live MLB game lines & player props from DraftKings."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://sportsbook.draftkings.com",
            "Referer": "https://sportsbook.draftkings.com/",
            "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        })
        self._last_call: float = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=3),
        reraise=False,
    )
    def _get(self, endpoint: str, params: dict | None = None) -> dict[str, Any]:
        self._throttle()
        url = f"{DK_BASE_URL}{endpoint}"
        try:
            resp = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT, verify=True)
            resp.raise_for_status()
            self._last_call = time.monotonic()
            return resp.json()
        except requests.exceptions.SSLError:
            log.debug("SSL certificate verification failed for DraftKings; trying verify=False")
            try:
                resp = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT, verify=False)
                resp.raise_for_status()
                self._last_call = time.monotonic()
                return resp.json()
            except Exception as e2:
                log.debug("DraftKings API request failed (unverified fallback): %s %s -> %s", url, params, e2)
                return {}
        except Exception as e:
            log.debug("DraftKings API request failed: %s %s -> %s", url, params, e)
            return {}

    def get_mlb_event_group(self) -> dict[str, Any]:
        """Fetch primary MLB event group containing upcoming game cards and offer categories."""
        return self._get(f"/eventgroups/{MLB_EVENT_GROUP_ID}?format=json")

    def get_game_odds_by_team(self, team_name_or_abbr: str = "Red Sox") -> dict[str, Any]:
        """
        Queries live DraftKings odds for the next upcoming game involving team_name_or_abbr.
        Returns parsed game lines: Moneyline, Run Line, Total, F5, NRFI/YRFI, and Pitcher K props.
        """
        data = self.get_mlb_event_group()
        if not data:
            return {"status": "UNAVAILABLE", "source": "Model Est."}

        event_group = data.get("eventGroup", {})
        events = event_group.get("events", [])
        if not events:
            return {"status": "UNAVAILABLE", "source": "Model Est."}

        # Find match involving team keyword (e.g. "Red Sox" or "BOS")
        target_event = None
        team_kw = team_name_or_abbr.lower()

        for event in events:
            name = event.get("name", "").lower()
            if "red sox" in name or "boston" in name or team_kw in name:
                target_event = event
                break

        if not target_event:
            return {"status": "NO_UPCOMING_GAME", "source": "Model Est."}

        event_id = target_event.get("eventId")
        event_name = target_event.get("name", "Upcoming Game")
        start_date = target_event.get("startDate", "")

        # Extract market lines from display groups
        offer_categories = event_group.get("offerCategories", [])
        game_lines = {}

        for cat in offer_categories:
            cat_name = cat.get("name", "")
            if cat_name in ("Game Lines", "Main Markets"):
                component_groups = cat.get("offerSubcategoryDescriptors", [])
                for sub in component_groups:
                    offers = sub.get("offerSubcategory", {}).get("offers", [])
                    for offer_list in offers:
                        for offer in offer_list:
                            if offer.get("eventId") == event_id:
                                label = offer.get("label", "")
                                outcomes = offer.get("outcomes", [])
                                game_lines[label] = outcomes

        return {
            "status": "LIVE",
            "source": "DraftKings Live 🟢",
            "event_id": event_id,
            "event_name": event_name,
            "start_date": start_date,
            "game_lines": game_lines,
        }
