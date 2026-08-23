"""
Social preview cards.

The regression this guards: no page carried Open Graph or Twitter Card tags, so
every link shared to X, LinkedIn, Slack, Discord or iMessage rendered as a bare
URL with no title, image or summary. The site looked broken everywhere it was
shared, and nothing in the build would have noticed.

The failure modes here are all silent — a relative image URL, an unescaped
quote, a missing tag — so each gets its own assertion.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from viz import theme

DOCS = Path(__file__).resolve().parent.parent / "docs"

REQUIRED = [
    'name="description"',
    'property="og:type"',
    'property="og:title"',
    'property="og:description"',
    'property="og:url"',
    'property="og:image"',
    'name="twitter:card"',
    'name="twitter:title"',
    'name="twitter:description"',
    'name="twitter:image"',
]


class TestSocialMeta:
    @pytest.mark.parametrize("tag", REQUIRED)
    def test_every_required_tag_is_emitted(self, tag):
        assert tag in theme.social_meta("dashboard", "Test Title")

    def test_the_image_url_is_absolute(self):
        """A relative og:image silently yields no card at all — scrapers do not
        resolve relative paths."""
        html = theme.social_meta("dashboard", "Test Title")
        image = re.search(r'property="og:image" content="([^"]+)"', html).group(1)
        assert image.startswith("https://")

    def test_the_page_url_is_absolute_and_page_specific(self):
        html = theme.social_meta("record", "Track Record")
        url = re.search(r'property="og:url" content="([^"]+)"', html).group(1)
        assert url.startswith("https://")
        assert url.endswith(theme.PAGES["record"][0])

    def test_each_page_gets_its_own_description(self):
        board = theme.social_meta("board", "Board")
        record = theme.social_meta("record", "Record")
        assert board != record

    def test_an_unregistered_slug_still_produces_a_usable_card(self):
        """Degrade to the site blurb rather than emitting an empty description."""
        html = theme.social_meta("not-a-page", "Something")
        desc = re.search(r'name="description" content="([^"]+)"', html).group(1)
        assert len(desc) > 40

    def test_a_quote_in_the_title_cannot_truncate_the_tag(self):
        """An unescaped quote closes the attribute and swallows the rest."""
        html = theme.social_meta("dashboard", 'The "Big" Game')
        assert '"Big"' not in html
        assert "&quot;Big&quot;" in html

    def test_an_ampersand_is_escaped(self):
        html = theme.social_meta("dashboard", "Models & Method")
        assert "Models &amp; Method" in html

    def test_the_card_type_matches_the_image_shape(self):
        """
        The card image is a 739x712 logo. summary_large_image crops to roughly
        1.91:1 and would cut the top and bottom off it; a large card needs a
        purpose-made ~1200x630 image first.
        """
        assert theme.SOCIAL_CARD_TYPE == "summary"

    def test_every_registered_page_has_a_description_written_for_it(self):
        for slug in theme.PAGES:
            assert slug in theme.PAGE_DESCRIPTIONS, f"{slug} has no social description"

    @pytest.mark.parametrize("slug", sorted(theme.PAGE_DESCRIPTIONS))
    def test_descriptions_are_a_sensible_length_for_a_feed(self, slug):
        """Under ~60 chars says nothing; much over 200 is truncated by X."""
        assert 60 < len(theme.PAGE_DESCRIPTIONS[slug]) <= 250


class TestGeneratedPagesCarryTheCard:
    @pytest.mark.parametrize("slug", list(theme.PAGES))
    def test_each_built_page_has_og_tags(self, slug):
        path = DOCS / theme.PAGES[slug][0]
        if not path.exists():
            pytest.skip(f"{path.name} not built in this environment")
        html = path.read_text(encoding="utf-8")
        assert 'property="og:title"' in html, f"{path.name} would share as a bare URL"
        assert 'property="og:image"' in html

    def test_the_landing_page_has_og_tags(self):
        """The URL most likely to be shared."""
        index = DOCS / "index.html"
        if not index.exists():
            pytest.skip("index.html not present")
        html = index.read_text(encoding="utf-8")
        assert 'property="og:title"' in html
        assert 'content="https://dirtywater.corygarms.com/images/sox_retro_logo.png"' in html
