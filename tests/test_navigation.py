"""
Site navigation.

The regression this guards: the nav used to be five identical copies of one
link, pasted into five generators. A nav maintained in five files is a nav that
eventually differs in five files, so it now has one definition and these tests
hold the generators to it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from viz import theme

DOCS = Path(__file__).resolve().parent.parent / "docs"


class TestPageRegistry:
    def test_every_page_declares_a_known_mode(self):
        for slug, (_, _, mode) in theme.PAGES.items():
            assert mode in theme.MODE_LABELS, f"{slug} has an unregistered mode"

    def test_every_mode_has_a_landing_page(self):
        for mode in theme.MODE_LABELS:
            landing = theme._mode_landing(mode)
            assert landing != "index.html", f"{mode} has no pages"
            assert landing.endswith(".html")

    def test_registered_filenames_exist_on_disk(self):
        for slug, (filename, _, _) in theme.PAGES.items():
            assert (DOCS / filename).exists(), f"{slug} -> {filename} not built"


class TestNavBar:
    def test_marks_exactly_one_mode_active(self):
        for slug in theme.PAGES:
            html = theme.nav_bar(slug)
            assert html.count("mode-seg active") == 1, slug

    def test_the_active_mode_is_the_current_page_s_mode(self):
        for slug, (_, _, mode) in theme.PAGES.items():
            html = theme.nav_bar(slug)
            active = re.search(r'mode-seg active">([^<]+)', html).group(1)
            assert active == theme.MODE_LABELS[mode], slug

    def test_shows_only_the_current_mode_s_pages(self):
        """
        Scoped to the page links, not the whole bar: the mode switch itself
        must link to the other mode's landing page, since that is the toggle.
        """
        for slug, (_, _, mode) in theme.PAGES.items():
            html = theme.nav_bar(slug)
            links = re.search(r'<div class="nav-pages">(.*?)</div>', html, re.S).group(1)
            for other, (filename, _, other_mode) in theme.PAGES.items():
                if other_mode == mode:
                    continue
                assert f'href="{filename}"' not in links, \
                    f"{slug} leaked {other} into its page links"

    def test_the_switch_reaches_the_other_mode(self):
        for slug, (_, _, mode) in theme.PAGES.items():
            html = theme.nav_bar(slug)
            switch = re.search(r'<div class="mode-switch".*?</div>', html, re.S).group(0)
            for other_mode in theme.MODE_LABELS:
                if other_mode == mode:
                    continue
                assert f'href="{theme._mode_landing(other_mode)}"' in switch, slug

    def test_the_current_page_is_not_a_link_to_itself(self):
        for slug, (filename, _, _) in theme.PAGES.items():
            html = theme.nav_bar(slug)
            assert f'href="{filename}"' not in html, slug
            assert 'nav-page current' in html, slug

    def test_the_inactive_mode_links_to_its_landing_page(self):
        html = theme.nav_bar("betting")
        assert theme._mode_landing(theme.MODE_SEASON) in html

    def test_an_unknown_slug_still_renders_something_navigable(self):
        """A page that forgot to register itself must not lose its nav."""
        html = theme.nav_bar("not-a-page")
        assert "mode-switch" in html
        assert "index.html" in html
        assert html.count("mode-seg active") == 1


class TestGeneratedPagesCarryTheNav:
    @pytest.mark.parametrize("slug", list(theme.PAGES))
    def test_page_contains_the_switch_with_the_right_mode(self, slug):
        filename, _, mode = theme.PAGES[slug]
        path = DOCS / filename
        if not path.exists():
            pytest.skip(f"{filename} not built in this environment")
        html = path.read_text(encoding="utf-8")
        assert "mode-switch" in html, f"{filename} has no mode switch"
        active = re.search(r'mode-seg active">([^<]+)', html).group(1)
        assert active == theme.MODE_LABELS[mode]

    def test_no_page_still_carries_the_old_single_link_nav(self):
        for filename, _, _ in theme.PAGES.values():
            path = DOCS / filename
            if not path.exists():
                continue
            assert "Back to Suite Index" not in path.read_text(encoding="utf-8"), filename

    def test_index_links_to_every_registered_page(self):
        index = DOCS / "index.html"
        if not index.exists():
            pytest.skip("index.html not present")
        html = index.read_text(encoding="utf-8")
        for slug, (filename, _, _) in theme.PAGES.items():
            assert f'href="{filename}"' in html, f"index.html does not link {slug}"
