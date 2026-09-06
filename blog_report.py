"""
Build the notebook page: short, stats-backed observations about the season.

One page with each post as a section rather than a file per post. With a handful
of posts that is the whole of what a per-post route would buy, at none of the
cost -- one route, one registry entry, one social card. It splits the day the
count makes scrolling silly, and not before.

Every number on the page is computed at build time from the same caches the rest
of the site reads, so a post cannot quietly go stale while the team keeps
playing. See blog/posts.py for why that is the constraint rather than a
convenience.

Usage:
    python blog_report.py --team BOS --season 2026
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

import pandas as pd

import config
from betting_report import _shell
from blog.posts import POSTS
from client.mlb_client import MLBClient
from data import career_saves, league_games, pitching_leaders
from data.fetcher import Fetcher

log = logging.getLogger(__name__)


def _blog_css() -> str:
    """Post-specific styling. Everything else comes from theme.page_css()."""
    return """
    .post { margin-bottom: clamp(34px, 6vw, 52px); }
    .post-head { border-bottom: 1px solid #C5A059; padding-bottom: 10px; margin-bottom: 14px; }
    .post h2 { margin-bottom: 4px; }
    .post .dek { color: #9DB0A5; font-size: 0.95rem; line-height: 1.55; }
    .post .dateline {
      font-family: 'Share Tech Mono', monospace; font-size: 0.75rem;
      color: #9DB0A5; letter-spacing: 0.06em;
    }
    .post p { line-height: 1.65; margin-bottom: 12px; }
    .post p.lede { font-size: 1.02rem; }
    .post p.caveat {
      font-size: 0.88rem; color: #9DB0A5; border-left: 2px solid #C5A059;
      padding-left: 12px;
    }
    .stat-row {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px; margin: 18px 0;
    }
    .stat {
      background: #152620; border: 1px dashed #C5A059; border-radius: 3px;
      padding: 12px; text-align: center;
    }
    .stat-val {
      display: block; font-family: 'Share Tech Mono', monospace;
      font-size: 1.5rem; color: #F6F1E3;
    }
    .stat-lab {
      display: block; font-family: 'Graduate', Georgia, serif;
      font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase;
      color: #C5A059; margin-top: 4px;
    }
    .stat-note { display: block; font-size: 0.72rem; color: #9DB0A5; margin-top: 2px; }
    .cmp { margin: 14px 0; }
    .cmp-label {
      font-family: 'Graduate', Georgia, serif; font-size: 0.72rem;
      letter-spacing: 0.08em; text-transform: uppercase; color: #C5A059;
      margin-bottom: 6px;
    }
    .cmp-row { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }
    .cmp-name {
      flex: 0 0 68px; font-size: 0.8rem; color: #9DB0A5; text-align: right;
    }
    .cmp-bar {
      flex: 1 1 auto; height: 15px; background: rgba(255,255,255,0.05);
      border-radius: 2px; overflow: hidden;
    }
    .cmp-bar i { display: block; height: 100%; }
    .cmp-num {
      flex: 0 0 56px; font-family: 'Share Tech Mono', monospace;
      font-size: 0.85rem; color: #F6F1E3;
    }
    .cmp-foot {
      font-family: 'Share Tech Mono', monospace; font-size: 0.72rem;
      color: #BD3039; margin-top: 4px; padding-left: 104px;
    }
    """


def build_context(team_abbr: str, season: int) -> dict:
    """Everything a post may read, loaded once."""
    team_id = config.TEAMS.get(team_abbr, {}).get("id", config.TEAM_ID)
    fetcher = Fetcher(team_id=team_id, season=season)
    ctx: dict = {"team_abbr": team_abbr, "season": season, "team_id": team_id}
    for name in ("pitching", "batting", "games"):
        try:
            ctx[name] = fetcher.load(name)
        except FileNotFoundError:
            ctx[name] = pd.DataFrame()

    # Two sources that are not this team's season caches, and so are not the
    # Fetcher's to hand out.
    #
    # Both refetch themselves when stale and fall back to disk when the network
    # is gone, so a local build with no connectivity renders yesterday's copy
    # rather than failing. `league_games` needs the client passed in or it will
    # happily serve whatever is on disk forever -- nothing else in the nightly
    # build reads it, so before this its cache had been sitting twelve days old
    # while every page around it rebuilt hourly. A standings post on that would
    # have published a record eleven games out of date and looked entirely
    # plausible doing it.
    client = MLBClient()
    try:
        ctx["league"] = league_games.load_league_games(season, client=client)
    except Exception as e:                                  # noqa: BLE001
        log.warning("League games unavailable (%s); standings posts will skip", e)
        ctx["league"] = pd.DataFrame()
    try:
        ctx["saves_leaders"] = career_saves.load_leaders(client=client)
    except Exception as e:                                  # noqa: BLE001
        log.warning("Career saves unavailable (%s); the milestone post will skip", e)
        ctx["saves_leaders"] = pd.DataFrame()
    try:
        ctx["kbb_leaders"] = pitching_leaders.load_leaders(season, client=client)
    except Exception as e:                                  # noqa: BLE001
        log.warning("K/BB leaders unavailable (%s); that post will skip", e)
        ctx["kbb_leaders"] = pd.DataFrame()
    return ctx


def render_post(post, ctx: dict) -> str:
    """
    One post, or an honest placeholder.

    A post that raises must not take the page down with it: the other posts are
    still true, and a notebook that vanishes because one entry could not find a
    column is worse than one that says so.
    """
    try:
        body = post.build(ctx)
    except Exception as e:                                  # noqa: BLE001
        body = (f'<p class="caveat">This post could not be built from the current '
                f'cache ({type(e).__name__}). The rest of the page is unaffected.</p>')
    return f"""
  <section class="card post" id="{post.slug}">
    <div class="post-head">
      <p class="dateline">{post.dateline}</p>
      <h2>{post.title}</h2>
      <p class="dek">{post.dek}</p>
    </div>
    {body}
  </section>"""


def generate_blog_html(team_abbr: str = config.TEAM_ABBR,
                       season: int = config.SEASON) -> str:
    ctx = build_context(team_abbr, season)
    built = datetime.now(timezone.utc).strftime("%H:%M UTC on %d %b %Y")

    intro = f"""
  <section class="card">
    <h2>What this is</h2>
    <p>Short pieces about things this season's team has actually done, with the
    numbers behind them and the sample sizes they rest on. Every figure here is
    computed when the page is built &mdash; nothing is typed in by hand, so a post
    cannot quietly go stale while the team keeps playing, and it will move against
    its own argument if the data does.</p>
    <p class="dateline">Built {built}</p>
  </section>"""

    sections = intro + "".join(render_post(p, ctx) for p in POSTS)
    return _shell(
        f"{config.TEAMS.get(team_abbr, {}).get('name', config.TEAM_NAME)} — Notebook",
        "notebook",
        "&#128211; Notebook",
        "Short, stats-backed notes on what this season's team has actually done.",
        sections,
    ).replace("</style>", _blog_css() + "\n</style>", 1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the notebook page.")
    ap.add_argument("--team", default=config.TEAM_ABBR)
    ap.add_argument("--season", type=int, default=config.SEASON)
    args = ap.parse_args()

    html = generate_blog_html(args.team, args.season)
    path = config.OUTPUT_DIR / f"notebook_{args.team}_{args.season}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    print(f"Notebook generated successfully: {path}")


if __name__ == "__main__":
    main()
