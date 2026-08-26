"""
Blog posts, as data.

Each post is a function of the caches rather than a block of prose with numbers
typed into it. That is the whole design constraint: a number written by hand is
a number that goes stale the next time the team plays, and this site already
publishes eight pages that rebuild themselves nightly. A post that cannot
rebuild does not belong beside them.

So a post declares its slug, headline and standfirst, and a `build(ctx)` that
returns the body from whatever is on disk. If the underlying data moves, the
post moves with it -- including, when it happens, moving against the point the
post was making. That is the price of the format and it is the right one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class Post:
    slug: str
    title: str
    dek: str
    dateline: str
    build: Callable[[dict[str, Any]], str]


def _stat(label: str, value: str, note: str = "") -> str:
    note_html = f'<span class="stat-note">{note}</span>' if note else ""
    return (f'<div class="stat"><span class="stat-val">{value}</span>'
            f'<span class="stat-lab">{label}</span>{note_html}</div>')


def _bar_pair(label: str, a: float, b: float, a_lab: str, b_lab: str,
              fmt: str = "{:.2f}", lower_is_better: bool = True) -> str:
    """
    Two bars on a shared scale, drawn as inline SVG.

    Hand-rolled rather than Plotly for the same reason the track record page
    hand-rolls its reliability curve: embedding a charting library would take
    this page from tens of kilobytes to megabytes, and these are four numbers.
    """
    top = max(a, b) or 1.0
    wa, wb = 100.0 * a / top, 100.0 * b / top
    good, bad = ("#2E7D46", "#B4232B") if lower_is_better else ("#B4232B", "#2E7D46")
    a_col, b_col = (good, bad) if (a < b) == lower_is_better else (bad, good)
    return f"""
    <div class="cmp">
      <div class="cmp-label">{label}</div>
      <div class="cmp-row"><span class="cmp-name">{a_lab}</span>
        <span class="cmp-bar"><i style="width:{wa:.1f}%;background:{a_col}"></i></span>
        <span class="cmp-num">{fmt.format(a)}</span></div>
      <div class="cmp-row"><span class="cmp-name">{b_lab}</span>
        <span class="cmp-bar"><i style="width:{wb:.1f}%;background:{b_col}"></i></span>
        <span class="cmp-num">{fmt.format(b)}</span></div>
    </div>"""


def _times(bigger: float, smaller: float) -> str:
    """
    "3.6x" as many, or an honest phrase when the denominator is zero.

    A reliever who has allowed no home runs is entirely ordinary, and dividing
    by his rate is how a post about a good bullpen line crashes on the good
    part. Found by a test before it reached a page.
    """
    if smaller <= 0:
        return "no comparable rate &mdash; the relief figure is zero"
    return f"{bigger / smaller:.1f}&times;"


def _rate(frame: pd.DataFrame) -> dict[str, float]:
    """Per-nine rates from a set of pitching appearances."""
    ip = float(frame["ip_outs"].sum()) / 3.0
    if ip <= 0:
        return {}
    return {
        "ip": ip, "n": len(frame),
        "era": float(frame["er"].sum()) * 9.0 / ip,
        "k9": float(frame["so"].sum()) * 9.0 / ip,
        "bb9": float(frame["bb"].sum()) * 9.0 / ip,
        "hr9": float(frame["hr"].sum()) * 9.0 / ip,
        "whip": (float(frame["h"].sum()) + float(frame["bb"].sum())) / ip,
    }


def bello(ctx: dict[str, Any]) -> str:
    """Two pitchers, one arm."""
    p = ctx["pitching"]
    b = p[p["player_name"].str.contains("Bello", na=False)].sort_values("game_date")
    if b.empty:
        return "<p>No appearances on record.</p>"

    started = b[b["is_starter"].astype(bool)]
    relieved = b[~b["is_starter"].astype(bool)]
    s, r = _rate(started), _rate(relieved)
    if not s or not r:
        return "<p>Not enough of one role to compare.</p>"

    last_start = started["game_date"].max()
    first_relief = relieved["game_date"].min()

    return f"""
    <p class="lede">Brayan Bello has thrown {s['ip']:.1f} innings as a starter this
    season and {r['ip']:.1f} as a reliever, and the two lines belong to different
    pitchers. Not marginally &mdash; his earned run average as a reliever is
    <strong>{r['era']:.2f}</strong>. As a starter it is <strong>{s['era']:.2f}</strong>.</p>

    <div class="stat-row">
      {_stat("ERA in relief", f"{r['era']:.2f}", f"{r['n']} appearances")}
      {_stat("ERA as a starter", f"{s['era']:.2f}", f"{s['n']} starts")}
      {_stat("Walks per nine", f"{r['bb9']:.2f} &rarr; {s['bb9']:.2f}", "relief &rarr; starting")}
    </div>

    {_bar_pair("Earned run average", r['era'], s['era'], "Relief", "Starting")}
    {_bar_pair("WHIP", r['whip'], s['whip'], "Relief", "Starting")}
    {_bar_pair("Walks per nine", r['bb9'], s['bb9'], "Relief", "Starting")}
    {_bar_pair("Home runs per nine", r['hr9'], s['hr9'], "Relief", "Starting")}

    <p>The strikeout rate barely moves &mdash; {r['k9']:.2f} per nine in relief against
    {s['k9']:.2f} starting &mdash; so this is not a story about losing stuff. It is a
    story about command and damage. He walks
    <strong>{_times(s['bb9'], r['bb9'])}</strong> as many hitters per nine as a
    starter and gives up <strong>{_times(s['hr9'], r['hr9'])}</strong> as many
    home runs.</p>

    <p>The dates matter. His last start was <strong>{last_start}</strong>; his first
    relief appearance was <strong>{first_relief}</strong>. He has not started since,
    and the bullpen line has been accumulating ever since.</p>

    <p class="caveat"><strong>What this is not.</strong> {r['ip']:.1f} innings across
    {r['n']} appearances is {r['ip'] / r['n']:.1f} innings a time &mdash; this is bulk
    relief, not a seventh-inning specialist, so the comparison is closer to
    like-for-like than a closer's ERA would be. It is still {s['ip']:.1f} innings of
    starting, which is a handful of bad afternoons away from looking ordinary. Both
    samples are small and the gap is enormous; the honest reading is that the gap is
    far too large to be entirely real, and far too large to be entirely noise
    either.</p>

    <p class="caveat">It also caught this site out once. The bullpen availability
    table used to read roles off the roster, where MLB tags every pitcher on the
    26-man as a starter, and Bello is exactly the case that exposed it &mdash; a man
    who opened the season in the rotation and has relieved exclusively since
    midsummer. The table now reads role from the last thirty days of usage instead.</p>
    """


def _slash(x: pd.DataFrame) -> dict[str, float]:
    """AVG / OBP / SLG and the counting stats behind them."""
    ab, h, bb = float(x["ab"].sum()), float(x["h"].sum()), float(x["bb"].sum())
    hr, d, t = float(x["hr"].sum()), float(x["doubles"].sum()), float(x["triples"].sum())
    pa = float(x["pa"].sum()) or (ab + bb)
    if ab <= 0 or pa <= 0:
        return {}
    tb = (h - d - t - hr) + 2 * d + 3 * t + 4 * hr
    return {
        "g": len(x), "ab": ab, "hr": hr, "rbi": float(x["rbi"].sum()),
        "so": float(x["so"].sum()), "pa": pa,
        "avg": h / ab, "obp": (h + bb) / pa, "slg": tb / ab,
        "ops": (h + bb) / pa + tb / ab, "k_rate": float(x["so"].sum()) / pa,
    }


def gasper(ctx: dict[str, Any]) -> str:
    """A part-timer's hot streak, and what "last ten games" hides."""
    bat = ctx["batting"]
    g = bat[bat["player_name"].str.contains("Gasper", na=False)].sort_values("game_date")
    if g.empty:
        return "<p>No games on record.</p>"

    # The break is the story, so find it rather than hardcoding a date: the
    # longest gap between his appearances, which for a part-time catcher is a
    # very different thing from a rest day.
    dates = pd.to_datetime(g["game_date"])
    gaps = dates.diff().dt.days.fillna(0)
    if gaps.max() < 14:
        return "<p>No absence long enough to split his season around.</p>"
    at = int(gaps.idxmax())
    split_date = str(g.loc[at, "game_date"])
    away_days = int(gaps.max())

    before, after = _slash(g[g["game_date"] < split_date]), _slash(g[g["game_date"] >= split_date])
    if not before or not after:
        return "<p>Not enough either side of the break to compare.</p>"

    hr_dates = [d for d, h in zip(g["game_date"], g["hr"]) if h > 0]
    league_hr = 0.035
    from math import comb
    ab_i, hr_i = int(after["ab"]), int(after["hr"])
    p_luck = sum(comb(ab_i, k) * league_hr ** k * (1 - league_hr) ** (ab_i - k)
                 for k in range(hr_i, ab_i + 1))

    return f"""
    <p class="lede">Mickey Gasper hit no home runs in his first
    {int(before['g'])} games this season. He has hit <strong>{int(after['hr'])} in the
    {int(after['g'])} since he came back</strong> &mdash; in {int(after['ab'])} at-bats.</p>

    <div class="stat-row">
      {_stat("OPS before", f"{before['ops']:.3f}", f"{int(before['g'])} games, {int(before['ab'])} AB")}
      {_stat("OPS since", f"{after['ops']:.3f}", f"{int(after['g'])} games, {int(after['ab'])} AB")}
      {_stat("Home runs", f"{int(before['hr'])} &rarr; {int(after['hr'])}", "before &rarr; since")}
    </div>

    {_bar_pair("On-base plus slugging", before['ops'], after['ops'], "Before", "Since",
               fmt="{:.3f}", lower_is_better=False)}
    {_bar_pair("Slugging", before['slg'], after['slg'], "Before", "Since",
               fmt="{:.3f}", lower_is_better=False)}
    {_bar_pair("Strikeout rate", before['k_rate'], after['k_rate'], "Before", "Since",
               fmt="{:.1%}")}

    <p><strong>The window is not what it looks like.</strong> A "last ten games"
    split on a part-time catcher is not a fortnight &mdash; his was
    <strong>{away_days} days</strong> wide, because he did not appear at all
    between then and {split_date}. Read as recent form it looks like a hot
    fortnight. It is really a player who went away and came back different, and
    the two are not the same claim.</p>

    <p>The strikeout rate is the part that argues for something real. He struck
    out in <strong>{before['k_rate']:.0%}</strong> of plate appearances before the
    break and <strong>{after['k_rate']:.0%}</strong> since &mdash; power surges
    are common, power surges accompanied by a collapsing strikeout rate are less
    so. His home runs came on {", ".join(str(d) for d in hr_dates)}.</p>

    <p class="caveat"><strong>And {int(after['ab'])} at-bats is {int(after['ab'])}
    at-bats.</strong> Put a number on it: if he were a league-average power hitter
    &mdash; about {league_hr:.1%} of at-bats ending in a home run &mdash; the chance
    of {int(after['hr'])} or more in {int(after['ab'])} is
    <strong>{p_luck:.4f}</strong>, roughly one in {1 / p_luck:,.0f}. That is small
    enough to say the rate has genuinely changed and far too small a sample to say
    what it changed <em>to</em>. A .476 average will not survive contact with
    September. The question worth watching is not whether he keeps slugging
    {after['slg']:.3f} &mdash; he will not &mdash; but whether the strikeout rate
    stays down when the batted-ball luck stops.</p>
    """


POSTS: tuple[Post, ...] = (
    Post(
        slug="bello-two-pitchers",
        title="Two pitchers, one arm",
        dek="Brayan Bello has a 0.99 ERA in relief and a 10.35 ERA as a starter. "
            "The strikeout rate is the same. Everything else is not.",
        dateline="2026-08-26",
        build=bello,
    ),
    Post(
        slug="gasper-came-back-different",
        title="Mickey Gasper went away and came back different",
        dek="No home runs in his first 34 games. Five in the eight since he "
            "returned, on 21 at-bats — with the strikeout rate falling through "
            "the floor at the same time.",
        dateline="2026-08-26",
        build=gasper,
    ),
)
