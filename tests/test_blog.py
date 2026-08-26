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
        ctx = blog_report.build_context("BOS", 2026)
        assert ctx["pitching"].empty and ctx["batting"].empty


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
