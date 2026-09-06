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

import config
from analysis.streaks import played_in_order
from data import career_saves, pitching_leaders
from viz import theme


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


def _col(x: pd.DataFrame, name: str) -> float:
    """A column's total, or zero when the cache does not carry it."""
    return float(x[name].sum()) if name in x.columns else 0.0


def _slash(x: pd.DataFrame) -> dict[str, float]:
    """
    AVG / OBP / SLG and the counting stats behind them.

    On-base percentage is (H + BB + HBP) / (AB + BB + HBP + SF), which is worth
    spelling out because this used to be (H + BB) / PA and that is wrong twice
    over: it drops hit-by-pitch from the numerator while leaving it in the
    denominator, and PA also carries sacrifice bunts, which the official
    denominator excludes. Both errors push the figure down. On Gasper's games
    since his return it understated on-base by 47 points and OPS with it --
    1.406 against a true 1.453 -- and the rarer a walk-and-plunk profile is, the
    worse it gets. Checked against MLB's own season line: this lands within a
    few points, the old form was 28 off.

    Strikeout rate stays per plate appearance, which is what K% means.
    """
    ab, h, bb = _col(x, "ab"), _col(x, "h"), _col(x, "bb")
    hr, d, t = _col(x, "hr"), _col(x, "doubles"), _col(x, "triples")
    hbp, sf = _col(x, "hbp"), _col(x, "sac_fly")
    pa = _col(x, "pa") or (ab + bb + hbp + sf)
    on_base_chances = ab + bb + hbp + sf
    if ab <= 0 or pa <= 0 or on_base_chances <= 0:
        return {}
    tb = (h - d - t - hr) + 2 * d + 3 * t + 4 * hr
    obp = (h + bb + hbp) / on_base_chances
    slg = tb / ab
    return {
        "g": len(x), "ab": ab, "hr": hr, "rbi": _col(x, "rbi"),
        "so": _col(x, "so"), "pa": pa,
        "avg": h / ab, "obp": obp, "slg": slg,
        "ops": obp + slg, "k_rate": _col(x, "so") / pa,
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
    what it changed <em>to</em>. A .{round(after['avg'] * 1000):03d} average and
    {after['slg']:.3f} slugging on {int(after['ab'])} at-bats are rates this
    sample cannot place; where they settle, and whether the strikeout rate stays
    down once the batted-ball luck turns, is not something these numbers
    answer.</p>
    """


# ----------------------------------------------------------------------
# Drawing helpers
#
# All inline SVG, for the reason _bar_pair already gives: these pages are
# tens of kilobytes and a charting library would make them megabytes. Each
# one takes a viewBox and no fixed width, so it scales to the phone the
# site is mostly read on rather than forcing a horizontal scroll.
#
# The labelling rule is deliberate. A chart that needs a legend to be read
# has usually failed; these carry the one or two numbers that make the
# shape legible and leave the rest to the prose.
# ----------------------------------------------------------------------

_BRASS, _PARCHMENT, _MUTED = theme.BRASS, theme.PARCHMENT, theme.INK_MUTED
_GREEN, _CRIMSON, _GRID = theme.OUTFIELD_GREEN, theme.FENWAY_CRIMSON, theme.TURF_GRID


def _svg(inner: str, w: int, h: int, max_w: int = 480) -> str:
    # Capped, not merely responsive. An SVG on a viewBox scales in both
    # directions, so a 360x128 chart in a 1160px card renders 412px tall and
    # swamps the prose it belongs to -- while _bar_pair's HTML bars stay 15px
    # whatever the width. The cap keeps the two kinds of figure the same size
    # on a desktop and changes nothing on a phone, where 100% is already less.
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="auto" '
            f'style="width:100%;max-width:{max_w}px;display:block;margin:14px 0" '
            f'role="img" aria-hidden="true">{inner}</svg>')


def _ladder(rows: list[tuple[str, float, bool]], marker: float | None = None,
            marker_label: str = "", label: str = "") -> str:
    """
    Ranked bars, tallest first. `rows` is (name, value, is_us).

    Built from the same .cmp markup _bar_pair uses rather than as an SVG, so a
    leaderboard and a two-bar comparison are the same object at every width.
    The SVG version scaled its type and bar height with the container and was
    three times life size on a desktop.

    The optional marker is a threshold rule drawn inside the track -- a club
    boundary, a playoff cut -- so the picture carries it without a caption.
    """
    if not rows:
        return ""
    top_val = max(v for _, v, _ in rows) or 1.0
    whole = all(float(v).is_integer() for _, v, _ in rows)
    num = (lambda v: f"{v:g}") if whole else (lambda v: f"{v:.2f}")
    head = f'<div class="cmp-label">{label}</div>' if label else ""
    out = []
    for name, val, us in rows:
        col = _BRASS if us else _GRID
        weight = "600" if us else "400"
        tint = _PARCHMENT if us else _MUTED
        rule = ""
        if marker is not None:
            rule = (f'<b style="position:absolute;left:{100.0 * marker / top_val:.1f}%;'
                    f'top:0;bottom:0;width:2px;background:{_CRIMSON};'
                    f'opacity:0.9"></b>')
        out.append(
            f'<div class="cmp-row">'
            f'<span class="cmp-name" style="flex:0 0 96px;color:{tint};'
            f'font-weight:{weight}">{name}</span>'
            f'<span class="cmp-bar" style="position:relative">'
            f'<i style="width:{100.0 * val / top_val:.1f}%;background:{col}"></i>{rule}'
            f'</span>'
            f'<span class="cmp-num" style="font-weight:{weight}">{num(val)}</span>'
            f'</div>')
    foot = ""
    if marker is not None and marker_label:
        foot = (f'<div class="cmp-foot">&#9474; {marker_label}</div>')
    return f'<div class="cmp">{head}{"".join(out)}{foot}</div>'


def _label_y(y: float, h: int, below: float = 15, above: float = 13) -> float:
    """Below the point when there is room, above it when there is not."""
    return y + below if y + below <= h - 3 else y - above


def _run_chart(values: list[int], low_i: int) -> str:
    """
    Games over .500, game by game -- the shape of a season in one line.

    A won-lost record is a scalar and hides everything about how it was
    arrived at; 78-65 says nothing about having been fourteen under in June.
    The zero line is what the eye reads against, so it is drawn first and
    the area is filled from it, red below and green above.
    """
    if not values:
        return ""
    w, h, pad = 360, 128, 10
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)

    def X(i: int) -> float:
        return pad + (w - 2 * pad) * (i / max(n - 1, 1))

    def Y(v: float) -> float:
        return pad + (h - 2 * pad) * (1 - (v - lo) / span)

    zero_y = Y(0)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(values))
    out = [
        f'<polygon points="{X(0):.1f},{zero_y:.1f} {pts} {X(n-1):.1f},{zero_y:.1f}" '
        f'fill="{_GREEN}" opacity="0.16"/>',
        f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{w-pad}" y2="{zero_y:.1f}" '
        f'stroke="{_MUTED}" stroke-width="1" stroke-dasharray="2,3"/>',
        f'<polyline points="{pts}" fill="none" stroke="{_BRASS}" stroke-width="2" '
        f'stroke-linejoin="round"/>',
        f'<circle cx="{X(low_i):.1f}" cy="{Y(values[low_i]):.1f}" r="3.5" fill="{_CRIMSON}"/>',
        # The low point is by definition at the bottom of the plot, so a label
        # placed under it falls outside the viewBox and is clipped away.
        f'<text x="{X(low_i):.1f}" y="{_label_y(Y(values[low_i]), h):.1f}" '
        f'text-anchor="middle" font-size="10" fill="{_CRIMSON}" '
        f'font-family="monospace">{values[low_i]:+d}</text>',
        f'<circle cx="{X(n-1):.1f}" cy="{Y(values[-1]):.1f}" r="3.5" fill="{_PARCHMENT}"/>',
        f'<text x="{X(n-1):.1f}" y="{Y(values[-1]) - 8:.1f}" text-anchor="end" '
        f'font-size="10" fill="{_PARCHMENT}" font-family="monospace">{values[-1]:+d}</text>',
    ]
    return _svg("".join(out), w, h)


def _event_strip(flags: list[int], mark_from: int) -> str:
    """
    One tick per game, filled where something happened.

    For a streak the calendar is the argument: eight home runs read as a hot
    stretch in a table and as a cluster here, which is a different claim and
    the one worth making. `mark_from` divides the season at the break.
    """
    if not flags:
        return ""
    n = len(flags)
    w, h = 360, 34
    gap = 1.0
    bw = max((w - 8 - gap * (n - 1)) / n, 1.2)
    out = []
    for i, f in enumerate(flags):
        x = 4 + i * (bw + gap)
        if f:
            out.append(f'<rect x="{x:.2f}" y="4" width="{bw:.2f}" height="18" rx="1" '
                       f'fill="{_BRASS}"/>')
        else:
            out.append(f'<rect x="{x:.2f}" y="12" width="{bw:.2f}" height="3" rx="1" '
                       f'fill="{_GRID}"/>')
    out.append(f'<line x1="4" y1="{h-9}" x2="{w-4}" y2="{h-9}" stroke="{_GRID}" '
               f'stroke-width="1"/>')
    dx = 4 + mark_from * (bw + gap) - gap / 2
    out.append(f'<line x1="{dx:.2f}" y1="0" x2="{dx:.2f}" y2="{h-6}" stroke="{_CRIMSON}" '
               f'stroke-width="2"/>')
    return _svg("".join(out), w, h)


def _bar_trio(label: str, items: list[tuple[str, float]], fmt: str = "{:.3f}",
              highlight: int = -1) -> str:
    """Three or more bars on one scale, for a split _bar_pair cannot express."""
    if not items:
        return ""
    top = max(abs(v) for _, v in items) or 1.0
    rows = []
    for i, (name, val) in enumerate(items):
        col = _BRASS if i == highlight else _GRID
        rows.append(
            f'<div class="cmp-row"><span class="cmp-name">{name}</span>'
            f'<span class="cmp-bar"><i style="width:{100.0 * abs(val) / top:.1f}%;'
            f'background:{col}"></i></span>'
            f'<span class="cmp-num">{fmt.format(val)}</span></div>')
    return f'<div class="cmp"><div class="cmp-label">{label}</div>{"".join(rows)}</div>'


# ----------------------------------------------------------------------
# Posts
# ----------------------------------------------------------------------

def chapman_400(ctx: dict[str, Any]) -> str:
    """A closer one save from a number only eight men have reached."""
    leaders = ctx.get("saves_leaders")
    if leaders is None or leaders.empty:
        return "<p>The all-time leaderboard is unavailable in this build.</p>"

    name = "Aroldis Chapman"
    his = leaders[leaders["player_name"].str.contains("Chapman", na=False)]
    if his.empty:
        return "<p>He is not on the leaderboard this build fetched.</p>"
    career = int(his.iloc[0]["saves"])
    rank = int(leaders["saves"].gt(career).sum()) + 1

    # The club is counted, never listed by hand: the men above him are still
    # active and still saving games, so who is in and how many there are both
    # move. next_milestone treats a total already on a round number as having
    # arrived at it rather than approaching it.
    target = career_saves.nearest_milestone(career, 50)
    club = career_saves.club_at(leaders, target)
    to_go = target - career
    arrived = to_go <= 0

    p = ctx["pitching"]
    mine = p[p["player_name"].str.contains("Chapman", na=False)] if not p.empty else p
    sv = int(mine["save"].sum()) if len(mine) else 0
    bs = int(mine["blown_save"].sum()) if len(mine) else 0
    outs = float(mine["ip_outs"].sum()) if len(mine) else 0.0
    ip = outs / 3.0
    era = float(mine["er"].sum()) * 9.0 / ip if ip else 0.0
    k9 = float(mine["so"].sum()) * 9.0 / ip if ip else 0.0
    conv = sv / (sv + bs) if (sv + bs) else 0.0

    rows = [(n.split()[-1], float(v), n == name)
            for n, v in zip(leaders["player_name"].head(11),
                            leaders["saves"].head(11))]

    # No claim about being the Nth man *to reach* it: this ranks by career
    # total, and the order in which a club was joined is not the order it is
    # listed in. Membership is what the data supports.
    lede = (f"<strong>{name} has {career} career saves.</strong> "
            + (f"He is one of {len(club)} pitchers who have reached {target}."
               if arrived else
               f"He is {to_go} from {target}, a number {len(club)} pitchers "
               f"in the history of the game have reached."))

    return f"""
    <p class="lede">{lede}</p>

    <div class="stat-row">
      {_stat("Career saves", f"{career}", f"{_ordinal(rank)} all-time")}
      {_stat(("In the " + str(target) + " club") if arrived else ("From " + str(target)),
             f"{len(club)}" if arrived else f"{to_go}",
             "members, with him" if arrived
             else ("one save" if to_go == 1 else f"{to_go} saves"))}
      {_stat("This season", f"{sv}", f"{conv:.0%} converted, {bs} blown")}
    </div>

    {_ladder(rows, marker=float(target), marker_label=str(target))}

    <p>{"The line he has crossed is drawn in red" if arrived
        else "The bar he is short of is drawn in red"}. He is
    <strong>{_age(ctx, "Chapman") or "&mdash;"}</strong>, still closing, and
    still striking out
    <strong>{k9:.1f} per nine</strong> across {ip:.0f} innings with a
    <strong>{era:.2f}</strong> ERA.</p>

    <p class="caveat">A save is the most argued-over number in the sport &mdash;
    it rewards being handed a three-run lead and says nothing about the innings
    a reliever did not get. It is worth exactly what a counting stat is worth.
    What it does measure honestly is durability: {career} of them means only
    {rank - 1} men have ever been trusted with more.</p>
    """


def _age(ctx: dict[str, Any], surname: str) -> int | None:
    """Age off the roster cache, so a birthday is not typed into prose."""
    try:
        import config as _cfg
        r = pd.read_parquet(
            _cfg.CACHE_DIR / f"roster_{ctx['team_id']}_{ctx['season']}.parquet")
        hit = r[r["player_name"].str.contains(surname, na=False)]
        return int(hit.iloc[0]["age"]) if not hit.empty else None
    except Exception:                                       # noqa: BLE001
        return None


def gasper_september(ctx: dict[str, Any]) -> str:
    """The revisit: the streak's own prediction, tested."""
    bat = ctx["batting"]
    g = bat[bat["player_name"].str.contains("Gasper", na=False)].sort_values("game_date")
    if g.empty:
        return "<p>No games on record.</p>"

    dates = pd.to_datetime(g["game_date"])
    gaps = dates.diff().dt.days.fillna(0)
    if gaps.max() < 14:
        return "<p>No absence long enough to split his season around.</p>"
    at = int(gaps.idxmax())
    split_date = str(g.loc[at, "game_date"])
    pos = int(g.index.get_indexer([at])[0])

    since = g[g["game_date"] >= split_date]
    # September is the month the original post named, so it is the month that
    # settles it -- not a trailing-N window chosen after the fact.
    month = f"{ctx['season']}-09"
    sept = since[since["game_date"].astype(str).str.startswith(month)]
    early = since[~since["game_date"].astype(str).str.startswith(month)]
    before = _slash(g[g["game_date"] < split_date])
    a_all, a_early, a_sept = _slash(since), _slash(early), _slash(sept)
    if not before or not a_all or not a_sept:
        return "<p>Not enough on either side of the break yet.</p>"

    flags = [1 if h > 0 else 0 for h in g["hr"]]

    return f"""
    <p class="lede">The note above splits Mickey Gasper's season around a
    {int(gaps.max())}-day absence. A month on, the half after the break has a
    third part: he is hitting
    <strong>.{round(a_sept['avg'] * 1000):03d}</strong> in September, with
    {int(a_sept['hr'])} home runs in {int(a_sept['ab'])} at-bats.</p>

    <div class="stat-row">
      {_stat("Home runs since", f"{int(a_all['hr'])}", f"in {int(a_all['ab'])} AB")}
      {_stat("September", f".{round(a_sept['avg'] * 1000):03d}", f"{int(a_sept['hr'])} HR, {int(a_sept['ab'])} AB")}
      {_stat("Before the break", f"{int(before['hr'])}", f"{int(before['g'])} games")}
    </div>

    {_event_strip(flags, pos)}

    <p>Every game he has played, in order; a filled bar is a home run and the
    red line is the {int(gaps.max())}-day absence. The cluster to the right of it
    is the whole of his power this season.</p>

    {_bar_trio("Slugging", [("Before", before["slg"]), ("Streak", a_early["slg"]),
                            ("September", a_sept["slg"])], highlight=2)}
    {_bar_trio("Strikeout rate", [("Before", before["k_rate"]), ("Streak", a_early["k_rate"]),
                                  ("September", a_sept["k_rate"])], fmt="{:.1%}", highlight=2)}

    <p><strong>Both rates have come off the streak.</strong> The slugging is
    down from {a_early['slg']:.3f} to {a_sept['slg']:.3f}, still above the
    {before['slg']:.3f} he posted before the break. The strikeout rate has moved
    the other way: {before['k_rate']:.1%} before the absence,
    {a_early['k_rate']:.1%} during the streak, and
    <strong>{a_sept['k_rate']:.1%}</strong> in September &mdash; higher than
    either.</p>

    <p class="caveat">{int(a_sept['ab'])} September at-bats is a smaller sample
    than the {int(a_early['ab'])} it is being set against, and both rest on a
    part-time catcher's playing time. Nothing in {int(a_all['ab'])} at-bats
    separates a rate that has changed from one that has not settled, in either
    direction.</p>
    """


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _rank_since(league: pd.DataFrame, team_id: int, after: str) -> tuple[int, int]:
    """
    Where a team's record since `after` ranks in the whole league.

    "The best stretch in baseball" is a claim, and this file's whole rule is
    that a claim with a number in it gets counted at build time or does not get
    made. Returns (0, 0) when the league results are not loaded, so the caller
    can drop the sentence rather than guess.
    """
    if league is None or league.empty:
        return 0, 0
    since = league[league["game_date"] > after]
    rec: dict[int, list[int]] = {}
    for h, a, hs, as_ in zip(since["home_team_id"], since["away_team_id"],
                             since["home_score"], since["away_score"]):
        if pd.isna(hs) or pd.isna(as_) or hs == as_:
            continue
        home_won = hs > as_
        for tid, won in ((int(h), home_won), (int(a), not home_won)):
            rec.setdefault(tid, [0, 0])
            rec[tid][0 if won else 1] += 1
    pcts = {t: w / (w + l) for t, (w, l) in rec.items() if w + l}
    if team_id not in pcts:
        return 0, 0
    better = sum(1 for t, p in pcts.items() if p > pcts[team_id])
    return better + 1, len(pcts)


def the_turnaround(ctx: dict[str, Any]) -> str:
    """Fourteen under in June; the shape of what happened next."""
    games = ctx["games"]
    if games.empty:
        return "<p>No games on record.</p>"
    g = played_in_order(games)
    res = [1 if r == "W" else 0 for r in g["result"]]
    if not res:
        return "<p>No decided games yet.</p>"

    cum, run = [], 0
    for r in res:
        run += 1 if r else -1
        cum.append(run)
    low_i = int(min(range(len(cum)), key=lambda i: cum[i]))
    low = cum[low_i]
    low_date = str(g.iloc[low_i]["game_date"])

    w_all, l_all = sum(res), len(res) - sum(res)
    after = res[low_i + 1:]
    w_a, l_a = sum(after), len(after) - sum(after)
    w_b, l_b = sum(res[:low_i + 1]), (low_i + 1) - sum(res[:low_i + 1])
    pct_a = w_a / len(after) if after else 0.0
    pct_b = w_b / (low_i + 1)

    rank, of = _rank_since(ctx.get("league"), ctx["team_id"], low_date)
    if rank == 1:
        claim = " &mdash; the best record in baseball over that stretch"
    elif rank:
        claim = f" &mdash; the {_ordinal(rank)} best record in baseball since"
    else:
        claim = ""

    return f"""
    <p class="lede">On {low_date} this team was <strong>{w_b}-{l_b}</strong>,
    {abs(low)} games under .500. It has gone
    <strong>{w_a}-{l_a}</strong> since{claim}.</p>

    <div class="stat-row">
      {_stat("Low-water mark", f"{low:+d}", low_date)}
      {_stat("Since", f"{w_a}-{l_a}", f".{round(pct_a * 1000):03d}")}
      {_stat("Now", f"{cum[-1]:+d}", f"{w_all}-{l_all}")}
    </div>

    {_run_chart(cum, low_i)}

    <p>Games above .500 after every game played. The red dot is the bottom, the
    swing from there to now is <strong>{cum[-1] - low} games</strong>, and the
    line does the thing a won-lost record cannot: {w_all}-{l_all} describes both
    the team that started this season and the one playing now, and they are not
    the same team.</p>

    {_bar_trio("Winning percentage",
               [("To the low", pct_b), ("Since", pct_a)],
               fmt="{:.3f}", highlight=1)}

    <p class="caveat">A run this long is not luck, and it is not proof either.
    Some of it is a schedule and some of it is a bullpen that stopped losing
    games it led. The one thing the shape does settle is that the season
    average is describing two different teams at once &mdash; which is why every
    projection on this site is built from recent form rather than a season line.</p>
    """


def the_wildcard(ctx: dict[str, Any]) -> str:
    """Where this leaves them, counted from every league result."""
    lg = ctx.get("league")
    if lg is None or lg.empty:
        return "<p>League results are unavailable in this build.</p>"

    rec: dict[int, list[int]] = {}
    for home, away, hs, as_ in zip(lg["home_team_id"], lg["away_team_id"],
                                   lg["home_score"], lg["away_score"]):
        if pd.isna(hs) or pd.isna(as_) or hs == as_:
            continue
        home_won = hs > as_
        for tid, won in ((int(home), home_won), (int(away), not home_won)):
            rec.setdefault(tid, [0, 0])
            rec[tid][0 if won else 1] += 1

    rows = []
    for abbr, info in config.TEAMS.items():
        if info["id"] not in rec:
            continue
        w, l = rec[info["id"]]
        if w + l == 0:
            continue
        rows.append({"abbr": abbr, "id": info["id"], "league": info["league"],
                     "division": info["division"], "w": w, "l": l,
                     "pct": w / (w + l)})
    df = pd.DataFrame(rows)
    me = config.TEAMS.get(ctx["team_abbr"], {})
    league = me.get("league", "AL")
    al = df[df["league"] == league].sort_values("pct", ascending=False).reset_index(drop=True)
    if al.empty:
        return "<p>No league results to rank.</p>"

    leaders = {d: al[al["division"] == d].iloc[0]["abbr"]
               for d in al["division"].unique()}
    wc = al[~al["abbr"].isin(leaders.values())].reset_index(drop=True)
    if len(wc) < 4:
        return "<p>Not enough teams outside the division leads to draw a race.</p>"

    mine = al[al["abbr"] == ctx["team_abbr"]]
    if mine.empty:
        return "<p>This team is not in the league table.</p>"
    mine = mine.iloc[0]
    in_wc = ctx["team_abbr"] in set(wc.head(3)["abbr"])
    is_leader = ctx["team_abbr"] in leaders.values()

    cut = wc.iloc[2]
    gb = ((cut["w"] - mine["w"]) + (mine["l"] - cut["l"])) / 2.0
    first = wc.iloc[3]
    margin = ((mine["w"] - first["w"]) + (first["l"] - mine["l"])) / 2.0

    bars = [(r["abbr"], round(r["pct"] * 1000), r["abbr"] == ctx["team_abbr"])
            for _, r in wc.head(7).iterrows()]

    where = ("holding the second wildcard" if in_wc and not is_leader
             else "leading the division" if is_leader else f"{gb:.1f} back")
    return f"""
    <p class="lede">Counted from every result in the {league} this season, they
    are <strong>{int(mine['w'])}-{int(mine['l'])}</strong> &mdash; {where}, with
    <strong>{len(wc) - 3}</strong> teams chasing the three spots.</p>

    <div class="stat-row">
      {_stat("Record", f"{int(mine['w'])}-{int(mine['l'])}", f".{round(mine['pct'] * 1000):03d}")}
      {_stat("Wildcard", "IN" if in_wc else f"{gb:+.1f}", "of three spots" if in_wc else "behind the cut")}
      {_stat("Cushion", f"{margin:+.1f}", f"on {first['abbr']}, first out")}
    </div>

    {_ladder(bars, marker=float(round(cut['pct'] * 1000)), marker_label="cut")}

    <p>Wildcard contenders by winning percentage, division leaders removed. The
    red line is the third spot; everyone left of it is currently out. The gaps
    are what matter this late &mdash; {first['abbr']} is
    {margin:.1f} games back, which with the season nearly run is a different
    problem from being {margin:.1f} back in June.</p>

    <p class="caveat">Head-to-head tiebreakers, games in hand and strength of
    remaining schedule are all missing from this: it is a straight count of
    wins and losses from the league's own results. It will disagree with an
    official standings page by whatever those are worth, and it refreshes
    itself every build rather than being read off one once.</p>
    """


def _game_bars(values: list[float], split: int = -1) -> str:
    """
    One bar per game, left to right.

    For a sample small enough to show whole, this beats an average: seven
    games that read .323 in a table are four good ones and three blanks here,
    and the difference between those two pictures is the entire caveat.
    """
    if not values:
        return ""
    w, h, pad = 360, 78, 12
    n = len(values)
    top = max(values) or 1.0
    slot = (w - 2 * pad) / n
    bw = min(slot * 0.62, 26)
    base = h - 18
    out = [f'<line x1="{pad}" y1="{base}" x2="{w - pad}" y2="{base}" '
           f'stroke="{_GRID}" stroke-width="1"/>']
    for i, v in enumerate(values):
        x = pad + slot * i + (slot - bw) / 2
        bh = (base - 8) * (v / top)
        col = _BRASS if v > 0 else _GRID
        out.append(f'<rect x="{x:.1f}" y="{base - bh:.1f}" width="{bw:.1f}" '
                   f'height="{max(bh, 1.5):.1f}" rx="2" fill="{col}"/>')
        if v:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{base - bh - 3:.1f}" '
                       f'text-anchor="middle" font-size="9" fill="{_MUTED}" '
                       f'font-family="monospace">{v:g}</text>')
    return _svg("".join(out), w, h)


def anthony_back(ctx: dict[str, Any]) -> str:
    """The lineup gets a bat back, and what seven games can and cannot say."""
    bat = ctx["batting"]
    # Matched exactly. A substring match on "Anthony" also catches Anthony
    # Seigler, which silently merges two players' seasons into one line and
    # makes the absence at the centre of this post disappear.
    a = bat[bat["player_name"] == "Roman Anthony"].sort_values("game_date")
    if a.empty:
        return "<p>No games on record.</p>"

    dates = pd.to_datetime(a["game_date"])
    gaps = dates.diff().dt.days.fillna(0)
    if gaps.max() < 21:
        return "<p>No absence long enough to write about.</p>"
    at = int(gaps.idxmax())
    back = str(a.loc[at, "game_date"])
    days = int(gaps.max())
    last_before = str(a.loc[:at].iloc[-2]["game_date"])

    before, since = _slash(a[a["game_date"] < back]), _slash(a[a["game_date"] >= back])
    if not before or not since:
        return "<p>Not enough either side of the absence to compare.</p>"

    # Total bases per game since the return, so the shape of a seven-game
    # sample is visible rather than averaged away.
    back_games = a[a["game_date"] >= back]
    tb = [float((r["h"] - r["doubles"] - r["triples"] - r["hr"])
                + 2 * r["doubles"] + 3 * r["triples"] + 4 * r["hr"])
          for _, r in back_games.iterrows()]

    # What the team did without him, which is the context that stops this
    # reading as a rescue: the turnaround on the chart above happened while he
    # was on the shelf.
    games = ctx["games"]
    out_span = games[(games["game_date"] > last_before) & (games["game_date"] < back)]
    ow, ol = int((out_span["result"] == "W").sum()), int((out_span["result"] == "L").sum())

    # Described from the numbers, not from looking at the picture once: the
    # shape of seven games changes with the eighth, and a sentence about it
    # typed by hand is wrong by tomorrow.
    _tb_total = sum(tb)
    _n_hot = sum(1 for v in tb if v > 0)
    _tail = 0
    for v in reversed(tb):
        if v:
            break
        _tail += 1
    _tail_note = (f", and the last {_tail} are blank" if _tail > 1
                  else ", and the most recent one is blank" if _tail == 1 else "")

    return f"""
    <p class="lede">Roman Anthony played his last game before the injury on
    {last_before} and his next one <strong>{days} days later</strong>, on
    {back}. In the {int(since['g'])} games since he has hit
    <strong>.{round(since['avg'] * 1000):03d}</strong> with an OPS of
    <strong>{since['ops']:.3f}</strong>.</p>

    <div class="stat-row">
      {_stat("Days out", f"{days}", f"{last_before} &rarr; {back}")}
      {_stat("Since", f".{round(since['avg'] * 1000):03d}", f"{int(since['g'])} games, {int(since['ab'])} AB")}
      {_stat("Slugging", f"{since['slg']:.3f}", f"was {before['slg']:.3f}")}
    </div>

    {_game_bars(tb)}

    <p>Total bases in each game since he came back. The average is doing a lot
    of work in a sample this size: <strong>{_n_hot} of the {int(since['g'])}
    games</strong> produced all {_tb_total:g} of them{_tail_note}, which is what
    {int(since['ab'])} at-bats looks like when you do not round it off.</p>

    {_bar_trio("Slugging", [("Before", before["slg"]), ("Since", since["slg"])],
               highlight=1)}
    {_bar_trio("On-base plus slugging", [("Before", before["ops"]), ("Since", since["ops"])],
               highlight=1)}
    {_bar_trio("Strikeout rate", [("Before", before["k_rate"]), ("Since", since["k_rate"])],
               fmt="{:.1%}", highlight=1)}

    <p><strong>The strikeout rate has not moved, and that matters.</strong> It
    was {before['k_rate']:.0%} before the absence and {since['k_rate']:.0%}
    since &mdash; so unlike the other returning bat on this page, there is no
    contact-quality signal underneath the slash line. What has changed is what
    happens when he connects: {before['slg']:.3f} slugging before,
    {since['slg']:.3f} since, on {int(since['hr'])} home runs in
    {int(since['ab'])} at-bats.</p>

    <p class="caveat"><strong>And the team did not need him to be good.</strong>
    While he was out they went <strong>{ow}-{ol}</strong> &mdash; the run charted
    further up this page happened without him in the lineup. That cuts both ways:
    it means this is a good team getting a bat back rather than a rescue, and it
    means {int(since['ab'])} at-bats of anybody is not what turned the season.
    Seven games is seven games, and the honest verdict is that he is healthy and
    hitting the ball hard, which is all a sample this size can support.</p>
    """


def _diverging(pos: list[float], neg: list[float]) -> str:
    """
    Two counts per start, one above a shared baseline and one below.

    A ratio is a quotient and hides its own inputs: 3.97 is the same number
    whether it came from a steady eight-and-two or from one enormous night
    carrying a run of walks. Drawn this way the shape answers that without a
    legend -- gold above is a strikeout, red below is a walk, and the gap
    between the two rows is the ratio.
    """
    if not pos:
        return ""
    n = len(pos)
    w, pad = 360, 8
    top_p = max(pos) or 1.0
    top_n = max(neg) or 1.0
    up, down = 46, 24
    mid = pad + up
    h = mid + down + pad
    slot = (w - 2 * pad) / n
    bw = min(slot * 0.66, 14)
    out = [f'<line x1="{pad}" y1="{mid}" x2="{w - pad}" y2="{mid}" '
           f'stroke="{_MUTED}" stroke-width="1" opacity="0.5"/>']
    for i, (p_, n_) in enumerate(zip(pos, neg)):
        x = pad + slot * i + (slot - bw) / 2
        ph = up * (p_ / top_p)
        nh = down * (n_ / top_n)
        if p_:
            out.append(f'<rect x="{x:.1f}" y="{mid - ph:.1f}" width="{bw:.1f}" '
                       f'height="{ph:.1f}" rx="1.5" fill="{_BRASS}"/>')
        if n_:
            out.append(f'<rect x="{x:.1f}" y="{mid + 1:.1f}" width="{bw:.1f}" '
                       f'height="{nh:.1f}" rx="1.5" fill="{_CRIMSON}" opacity="0.85"/>')
    return _svg("".join(out), w, h)


def tolle_command(ctx: dict[str, Any]) -> str:
    """A first full season, told through the ratio it is built on."""
    p = ctx["pitching"]
    t = p[p["player_name"].str.contains("Tolle", na=False)].sort_values("game_date")
    if t.empty:
        return "<p>No appearances on record.</p>"

    outs = float(t["ip_outs"].sum())
    ip = outs / 3.0
    so, bb = float(t["so"].sum()), float(t["bb"].sum())
    bf = float(t["bf"].sum())
    if ip <= 0 or bb <= 0 or bf <= 0:
        return "<p>Not enough on record to compute a ratio.</p>"
    kbb = so / bb
    era = float(t["er"].sum()) * 9.0 / ip
    whip = (float(t["h"].sum()) + bb) / ip
    k_rate, bb_rate = so / bf, bb / bf
    starts = int(t["is_starter"].astype(bool).sum())

    # Where that ratio would sit among the pitchers MLB counts, and the reason
    # he is not one of them. Qualification is one inning per team game, so the
    # bar moves every day the team plays -- it is read off the schedule, never
    # typed in.
    leaders = ctx.get("kbb_leaders")
    rank, field = pitching_leaders.rank_for(leaders, kbb)
    games = ctx["games"]
    need = len(games)
    short = max(need - ip, 0.0)

    quiet = int(((t["bb"] <= 1).sum()))
    best = t.loc[t["so"].idxmax()]

    # Everyone above him, and then him -- so the bar he is on is the position
    # the sentence claims. Showing a top ten with him appended would put him
    # eleventh in the picture and seventeenth in the prose. Past twenty rows the
    # chart stops being readable on a phone, so it is dropped rather than
    # truncated into a false position.
    board = ""
    if rank and rank <= 20:
        rows = [(nm.split()[-1], float(v), False)
                for nm, v in zip(leaders["player_name"].head(rank - 1),
                                 leaders["value"].head(rank - 1))]
        rows.append((t.iloc[0]["player_name"].split()[-1], round(kbb, 2), True))
        board = _ladder(rows)

    rank_line = (f" That would be <strong>{_ordinal(rank)}</strong> among the "
                 f"{field} pitchers who have thrown enough innings to qualify."
                 if rank else "")

    return f"""
    <p class="lede">Payton Tolle has struck out <strong>{int(so)}</strong> and
    walked <strong>{int(bb)}</strong> across {starts} starts, a ratio of
    <strong>{kbb:.2f}</strong>.{rank_line}</p>

    <div class="stat-row">
      {_stat("Strikeouts / walks", f"{kbb:.2f}", f"{int(so)} and {int(bb)}")}
      {_stat("Of batters faced", f"{k_rate:.1%}", f"against {bb_rate:.1%} walked")}
      {_stat("Earned run average", f"{era:.2f}", f"{ip:.1f} IP, {whip:.2f} WHIP")}
    </div>

    {_diverging(list(t["so"].astype(float)), list(t["bb"].astype(float)))}

    <p>Every start this season: strikeouts above the line, walks below it. The
    ratio is not carried by one night &mdash; he walked one or none in
    <strong>{quiet} of the {starts}</strong>, and his biggest game
    ({int(best['so'])} strikeouts on {best['game_date']}) came with
    {int(best['bb'])} walks.</p>

    {board}

    <p class="caveat"><strong>He is not actually on that leaderboard.</strong> A
    rate qualifies at one inning per team game, which today is
    <strong>{need}</strong>; he has thrown {ip:.1f} and is about
    {short:.0f} innings short. So the bar above is where the number would fall,
    not a standing he holds &mdash; and the reason it does not count is the same
    reason it is a good number: a {_age(ctx, "Tolle") or "young"}-year-old in
    his first full season is being given fewer innings than the men above
    him.</p>
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
        dek="No home runs before a seven-week absence, and a burst of them "
            "immediately after it — with the strikeout rate falling through the "
            "floor at the same time.",
        dateline="2026-08-26",
        build=gasper,
    ),
    Post(
        slug="chapman-400",
        title="Aroldis Chapman and the 400 club",
        dek="Where this bullpen's closer sits on the all-time saves list, and "
            "how short a list it is.",
        dateline="2026-09-06",
        build=chapman_400,
    ),
    Post(
        slug="tolle-command",
        title="Payton Tolle's strikeouts, and his walks",
        dek="A first full season built on the ratio between the two, and the "
            "innings limit that keeps it off the leaderboard.",
        dateline="2026-09-06",
        build=tolle_command,
    ),
    Post(
        slug="the-turnaround",
        title="Two teams, one record",
        dek="Fourteen games under .500 in the middle of June, and one of the "
            "best stretches in baseball since. The season line describes "
            "neither team.",
        dateline="2026-09-06",
        build=the_turnaround,
    ),
    Post(
        slug="wildcard-standing",
        title="Where that actually leaves them",
        dek="The wildcard race counted from every result in the league, and "
            "how much of a cushion the run has actually bought.",
        dateline="2026-09-06",
        build=the_wildcard,
    ),
    Post(
        slug="anthony-back",
        title="Roman Anthony, four months later",
        dek="Back in the lineup after an absence that cost him most of a "
            "season, with a line that looks like a breakout and a sample that "
            "cannot yet support one.",
        dateline="2026-09-06",
        build=anthony_back,
    ),
    Post(
        slug="gasper-september",
        title="Mickey Gasper in September",
        dek="A month on from the streak: the average has come down, the home "
            "runs have not, and the strikeout rate has gone back up.",
        dateline="2026-09-06",
        build=gasper_september,
    ),
)
