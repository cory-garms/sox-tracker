"""
One analytics tag per page, from one definition.

The tag was hardcoded into five report files -- the same five-way duplication
viz/theme.py exists to prevent, and with the same result: betting_BOS_2026.html
was missed and has never been counted. Consolidating it means a page cannot be
built without it, and cannot be built with two of it.

Counting twice is worse than not counting: it does not look broken, it looks
like traffic.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import config
from viz import theme

DOCS = Path(__file__).resolve().parent.parent / "docs"


@pytest.fixture
def analytics(monkeypatch):
    def _set(src="https://gc.zgo.at/count.js", site="https://x.goatcounter.com/count"):
        monkeypatch.setattr(config, "ANALYTICS_SRC", src)
        monkeypatch.setattr(config, "ANALYTICS_SITE", site)
    return _set


class TestTheTag:
    def test_it_renders_when_configured(self, analytics):
        analytics()
        tag = theme.analytics_tag()
        assert "gc.zgo.at/count.js" in tag
        assert 'data-goatcounter="https://x.goatcounter.com/count"' in tag

    def test_it_is_async_so_it_cannot_block_the_page(self, analytics):
        analytics()
        assert "async" in theme.analytics_tag()

    def test_no_src_means_no_tag_at_all(self, analytics):
        """
        Turning it off must actually remove the request. These pages are
        standalone files and a mirror; a stale script tag would keep calling
        out from someone's downloaded copy.
        """
        analytics(src="")
        assert theme.analytics_tag() == ""

    def test_a_src_with_no_site_still_renders(self, analytics):
        """Not every provider uses a data attribute."""
        analytics(site="")
        tag = theme.analytics_tag()
        assert "gc.zgo.at" in tag
        assert "data-goatcounter" not in tag

    def test_a_quote_in_the_site_cannot_break_out_of_the_attribute(self, analytics):
        analytics(site='" onload="alert(1)')
        tag = theme.analytics_tag()
        assert 'onload="alert(1)"' not in tag
        assert "&quot;" in tag

    def test_exactly_one_script_element(self, analytics):
        analytics()
        assert theme.analytics_tag().count("<script") == 1


class TestBuiltPagesCarryItExactlyOnce:
    @pytest.mark.parametrize("slug", list(theme.PAGES))
    def test_each_built_page_is_counted_once(self, slug):
        path = DOCS / theme.PAGES[slug][0]
        if not path.exists():
            pytest.skip(f"{path.name} not built in this environment")
        html = path.read_text(encoding="utf-8")
        n = len(re.findall(r"<script[^>]*goatcounter", html))
        assert n == 1, f"{path.name} has {n} analytics tags; two reads as traffic"

    def test_the_landing_page_is_counted(self):
        """The URL most likely to be shared, and it is not generated."""
        index = DOCS / "index.html"
        if not index.exists():
            pytest.skip("index.html not present")
        html = index.read_text(encoding="utf-8")
        assert len(re.findall(r"<script[^>]*goatcounter", html)) == 1


class TestNoReportHardcodesIt:
    @pytest.mark.parametrize("name", [
        "matchup_report.py", "streak_report.py", "leaders_report.py",
        "betting_report.py", "viz/dashboard.py",
    ])
    def test_the_tag_comes_from_theme_not_a_literal(self, name):
        """
        The regression: a sixth page gets added, someone copies the head from a
        fifth, and the copy drifts. betting_BOS_2026.html is the page that
        already proved this happens.
        """
        src = (Path(__file__).resolve().parent.parent / name).read_text(encoding="utf-8")
        assert "gc.zgo.at" not in src, f"{name} hardcodes the analytics tag"
        assert "theme.analytics_tag()" in src, f"{name} does not emit one at all"
