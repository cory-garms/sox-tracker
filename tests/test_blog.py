"""
The notebook, and the one property that makes it worth having.

A post is a function of the caches, not prose with numbers typed into it. That
is the constraint the format exists under: this site rebuilds eight pages a
night, and a post carrying hand-typed figures would start drifting away from
the pages those figures came from the next time the team played. The Bello
piece cites a 0.99 ERA; the day that becomes 1.20, the post has to say 1.20 or
it is lying beside eight pages that are not.

The other property is containment. One post that cannot find a column must not
take the notebook down with it -- the rest of the entries are still true.
"""

from __future__ import annotations

import pandas as pd
import pytest

import blog_report
from blog.posts import POSTS, Post
from viz import theme


def _pitching(rows):
    return pd.DataFrame(rows, columns=["game_date", "player_name", "is_starter",
                                       "ip_outs", "h", "er", "bb", "so", "hr"])


BELLO = _pitching([
    ("2026-04-01", "Brayan Bello", True, 15, 8, 6, 5, 3, 2),
    ("2026-04-08", "Brayan Bello", True, 12, 7, 5, 4, 2, 1),
    ("2026-06-01", "Brayan Bello", False, 18, 3, 1, 1, 5, 0),
    ("2026-06-08", "Brayan Bello", False, 15, 2, 0, 0, 4, 0),
])


def _raise(msg):
    def _boom(*a, **k):
        raise RuntimeError(msg)
    return _boom


def _offline(monkeypatch):
    """No test in this file is allowed to depend on a live provider."""
    monkeypatch.setattr(blog_report, "MLBClient", lambda *a, **k: object())
    monkeypatch.setattr(blog_report.league_games, "load_league_games",
                        lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(blog_report.career_saves, "load_leaders",
                        lambda *a, **k: pd.DataFrame())


class TestPostsAreComputed:
    def test_every_post_is_registered_with_the_fields_a_page_needs(self):
        assert POSTS
        for post in POSTS:
            assert isinstance(post, Post)
            assert post.slug and post.title and post.dek and post.dateline

    def test_slugs_are_unique(self):
        """They are HTML ids; two of one would break in-page links silently."""
        slugs = [p.slug for p in POSTS]
        assert len(slugs) == len(set(slugs))

    def test_the_numbers_come_from_the_data_not_the_prose(self):
        """
        The load-bearing test. Feed the post a different season and the figures
        it prints must change -- otherwise they were typed in, and the notebook
        is decoration that will drift away from the rest of the site.
        """
        from blog.posts import bello
        a = bello({"pitching": BELLO})
        worse = BELLO.copy()
        worse.loc[worse.is_starter, "er"] *= 3          # a far worse starter
        b = bello({"pitching": worse})
        assert a != b, "post output did not move when its input did"

    def test_a_post_with_no_data_says_so_rather_than_inventing(self):
        from blog.posts import bello
        out = bello({"pitching": _pitching([])})
        assert "No appearances" in out

    def test_a_role_with_no_innings_is_refused_not_divided_by_zero(self):
        from blog.posts import bello
        only_relief = BELLO[~BELLO.is_starter]
        out = bello({"pitching": only_relief})
        assert "Not enough" in out


class TestOnePostCannotTakeThePageDown:
    def test_a_raising_post_is_contained(self):
        def boom(ctx):
            raise KeyError("column that moved")

        html = blog_report.render_post(
            Post("x", "T", "D", "2026-08-26", boom), {})
        assert "could not be built" in html
        assert "KeyError" in html
        assert "<section" in html          # still a well-formed section

    def test_a_missing_cache_yields_empty_frames_not_a_crash(self, monkeypatch):
        class NoCache:
            def __init__(self, **kw): pass
            def load(self, name): raise FileNotFoundError(name)

        monkeypatch.setattr(blog_report, "Fetcher", NoCache)
        _offline(monkeypatch)
        ctx = blog_report.build_context("BOS", 2026)
        assert ctx["pitching"].empty and ctx["batting"].empty

    def test_an_unreachable_provider_leaves_the_other_posts_alone(self, monkeypatch):
        """
        build_context reaches the network for the league table and the all-time
        saves list. Neither is allowed to take the page down: a post that cannot
        be built says so, and the ones reading local caches still build.
        """
        monkeypatch.setattr(blog_report, "MLBClient", lambda *a, **k: object())
        monkeypatch.setattr(blog_report.league_games, "load_league_games",
                            _raise("league down"))
        monkeypatch.setattr(blog_report.career_saves, "load_leaders",
                            _raise("leaders down"))
        ctx = blog_report.build_context("BOS", 2026)
        assert ctx["league"].empty and ctx["saves_leaders"].empty

    def test_the_posts_that_need_the_network_say_so_when_it_is_gone(self):
        from blog.posts import chapman_400, the_wildcard
        empty = pd.DataFrame()
        assert "unavailable" in chapman_400(
            {"saves_leaders": empty, "pitching": empty, "season": 2026,
             "team_id": 111})
        assert "unavailable" in the_wildcard(
            {"league": empty, "team_abbr": "BOS", "team_id": 111})


class TestItIsPartOfTheSite:
    def test_the_notebook_is_registered(self):
        assert "notebook" in theme.PAGES
        filename, label, mode = theme.PAGES["notebook"]
        assert filename.startswith("notebook_")
        assert mode == theme.MODE_SEASON

    def test_it_has_a_social_description_like_every_other_page(self):
        assert "notebook" in theme.PAGE_DESCRIPTIONS

    def test_the_page_carries_the_nav_and_a_canonical(self):
        html = blog_report.generate_blog_html("BOS", 2026)
        assert 'class="nav-bar"' in html
        assert 'rel="canonical"' in html
        assert html.count("<html") == 1

    @pytest.mark.parametrize("post", POSTS, ids=lambda p: p.slug)
    def test_each_post_reaches_the_rendered_page(self, post):
        html = blog_report.generate_blog_html("BOS", 2026)
        assert f'id="{post.slug}"' in html
        assert post.title in html


class TestAClaimWithANumberInItIsCounted:
    """
    The new posts make three claims that would be ordinary prose anywhere else
    and are load-bearing here: how many pitchers have reached a milestone, where
    a run ranks in the league, and how a small sample is shaped. Each is counted
    at build time, so each must move with its input and disappear without it.
    """

    def _league(self, rows):
        return pd.DataFrame(
            [{"game_pk": i, "game_date": d, "home_team_id": h,
              "away_team_id": a, "home_score": hs, "away_score": as_}
             for i, (d, h, a, hs, as_) in enumerate(rows)])

    def test_the_league_rank_is_computed_from_results(self):
        from blog.posts import _rank_since
        # 111 wins both its games; 110 loses both. Two teams, we are first.
        lg = self._league([("2026-07-01", 111, 110, 5, 1),
                           ("2026-07-02", 110, 111, 2, 9)])
        assert _rank_since(lg, 111, "2026-06-30") == (1, 2)
        assert _rank_since(lg, 110, "2026-06-30") == (2, 2)

    def test_the_rank_respects_the_window(self):
        """A run is a run *since* a date; games before it must not count."""
        from blog.posts import _rank_since
        lg = self._league([("2026-05-01", 111, 110, 0, 9),   # before the window
                           ("2026-07-02", 111, 110, 9, 0)])
        assert _rank_since(lg, 111, "2026-06-30")[0] == 1

    def test_no_league_data_means_no_claim_rather_than_a_guess(self):
        from blog.posts import _rank_since
        assert _rank_since(pd.DataFrame(), 111, "2026-06-30") == (0, 0)
        assert _rank_since(None, 111, "2026-06-30") == (0, 0)

    def test_a_team_absent_from_the_window_is_not_ranked_first_by_default(self):
        """The failure this guards: an empty record scoring as an unbeaten one."""
        from blog.posts import _rank_since
        lg = self._league([("2026-07-02", 110, 109, 9, 0)])
        assert _rank_since(lg, 111, "2026-06-30") == (0, 0)

    def test_the_ordinal_reads_as_english(self):
        from blog.posts import _ordinal
        assert [_ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)] == [
            "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]
