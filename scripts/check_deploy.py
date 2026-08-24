"""
Is the live site actually serving what is in the repository?

On 2026-08-23 a build failed on a schema change and Render did what Render
does: it kept the last deploy that worked. The site returned 200s throughout,
every page loaded, and it silently stopped updating. It was found a day later
by accident, and by then fourteen commits had never reached production.

Nothing in the repo could have caught it, because every check ran against the
repo. The tests passed, the workflows were green, the data was committed. The
only thing that was wrong was the thing nobody was looking at: what the running
service was serving.

Two independent failures, deliberately reported separately:

  stale deploy   the site is on an older commit than master  (2026-08-23)
  stale data     the right commit, serving a cache nobody refreshed

Exit codes: 0 healthy, 1 stale, 2 unreachable. Unreachable is its own code so a
network blip in CI is distinguishable from a genuine regression.

Usage:
    python scripts/check_deploy.py --url https://dirtywater.corygarms.com \\
        --expect-commit "$(git rev-parse HEAD)" --commit-age-minutes 45
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Any

OK, STALE, UNREACHABLE = 0, 1, 2

# How far behind the newest game the cache may fall before it is stale. Two
# days rather than one: an off day is normal and a west-coast game finishing
# after midnight UTC is not a failure.
DEFAULT_MAX_DATA_AGE_DAYS = 2

# How long a deploy is allowed to take before a commit mismatch counts. Render
# free-plan builds run several minutes, and the check is scheduled, so a
# just-pushed commit would otherwise flag every time.
DEFAULT_COMMIT_GRACE_MINUTES = 45


def fetch_health(url: str, timeout: float = 30.0) -> dict[str, Any]:
    """The live /healthz payload. Raises on anything that is not a clean read."""
    endpoint = url.rstrip("/") + "/healthz"
    req = urllib.request.Request(endpoint, headers={"User-Agent": "dirtywater-deploy-check"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise urllib.error.HTTPError(endpoint, resp.status, "not 200", resp.headers, None)
        return json.loads(resp.read().decode("utf-8"))


def data_age_days(data_through: str | None, today: date | None = None) -> int | None:
    """Days between the newest game the site knows about and today."""
    if not data_through:
        return None
    try:
        seen = datetime.strptime(str(data_through)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return ((today or datetime.now(timezone.utc).date()) - seen).days


def evaluate(
    health: dict[str, Any],
    expect_commit: str = "",
    commit_age_minutes: float | None = None,
    grace_minutes: int = DEFAULT_COMMIT_GRACE_MINUTES,
    max_data_age_days: int = DEFAULT_MAX_DATA_AGE_DAYS,
    today: date | None = None,
) -> tuple[int, list[str]]:
    """
    Grade a health payload. Returns (exit_code, human-readable findings).

    Pure, so the failure this exists to catch can be tested without a network
    or a broken deployment to point it at.
    """
    problems: list[str] = []

    live = str(health.get("commit") or "").strip()
    want = str(expect_commit or "").strip()
    if want and live and live != "unknown":
        if not (live.startswith(want) or want.startswith(live)):
            # Inside the grace window a mismatch is just a deploy in progress.
            if commit_age_minutes is None or commit_age_minutes >= grace_minutes:
                problems.append(
                    f"STALE DEPLOY: serving {live[:12]}, master is {want[:12]}"
                    + (f" ({commit_age_minutes:.0f}m ago)" if commit_age_minutes is not None else "")
                )
    elif want and (not live or live == "unknown"):
        problems.append(
            "STALE DEPLOY: the site reports no commit, so it is running a build "
            "from before /healthz reported one"
        )

    age = data_age_days(health.get("data_through"), today=today)
    if age is None:
        problems.append("STALE DATA: the site reports no data_through at all")
    elif age > max_data_age_days:
        problems.append(
            f"STALE DATA: newest game is {health.get('data_through')}, {age} days old"
        )

    return (STALE if problems else OK), problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="https://dirtywater.corygarms.com")
    ap.add_argument("--expect-commit", default="")
    ap.add_argument("--commit-age-minutes", type=float, default=None)
    ap.add_argument("--grace-minutes", type=int, default=DEFAULT_COMMIT_GRACE_MINUTES)
    ap.add_argument("--max-data-age-days", type=int, default=DEFAULT_MAX_DATA_AGE_DAYS)
    args = ap.parse_args()

    try:
        health = fetch_health(args.url)
    except Exception as e:
        print(f"::error::Could not reach {args.url}/healthz — {type(e).__name__}: {e}")
        return UNREACHABLE

    code, problems = evaluate(
        health,
        expect_commit=args.expect_commit,
        commit_age_minutes=args.commit_age_minutes,
        grace_minutes=args.grace_minutes,
        max_data_age_days=args.max_data_age_days,
    )

    print(f"live commit   : {health.get('commit')}")
    print(f"data through  : {health.get('data_through')}")
    print(f"expected      : {args.expect_commit[:12] or '(not checked)'}")

    if code == OK:
        print("✓ the site is serving current code and current data")
        return OK

    for p in problems:
        print(f"::error::{p}")
    return code


if __name__ == "__main__":
    sys.exit(main())
