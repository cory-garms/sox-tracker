"""
Theme invariants.

The chart palette was validated against the data-viz colour criteria; these
tests protect the structural rules that keep that validation meaningful.
"""

from __future__ import annotations

import re

import pytest

from viz import theme


class TestCategoricalPalette:
    def test_hue_order_is_fixed(self):
        """
        Colour follows the entity, not its rank — so the order is part of the
        contract, not an implementation detail.
        """
        assert theme.CATEGORICAL == (
            theme.OUTFIELD_GREEN,
            theme.NAVY_BLUE,
            theme.FENWAY_CRIMSON,
            theme.SCOREBOARD_GOLD,
        )

    def test_categorical_returns_hues_in_order(self):
        assert [theme.categorical(i) for i in range(4)] == list(theme.CATEGORICAL)

    def test_raises_rather_than_cycling_past_the_validated_set(self):
        """
        Cycling would silently reuse a hue for a different series. Failing loudly
        forces the caller to fold into "Other" or switch to the ramp.
        """
        with pytest.raises(IndexError, match="validated"):
            theme.categorical(len(theme.CATEGORICAL))

    def test_every_colour_is_a_six_digit_hex(self):
        for colour in theme.CATEGORICAL:
            assert re.fullmatch(r"#[0-9a-fA-F]{6}", colour), colour

    def test_hues_are_distinct(self):
        assert len(set(theme.CATEGORICAL)) == len(theme.CATEGORICAL)

    def test_rejected_out_of_band_colours_are_not_in_use(self):
        """
        #F3C010 (L=0.83) and #58A6FF (L=0.715) fail the dark-mode lightness band
        and were replaced. Guard against them creeping back.
        """
        lowered = {c.lower() for c in theme.CATEGORICAL}
        assert "#f3c010" not in lowered
        assert "#58a6ff" not in lowered


class TestSemanticColours:
    def test_win_and_loss_are_distinct(self):
        assert theme.WIN != theme.LOSS

    def test_semantic_colours_come_from_the_validated_set(self):
        for colour in (theme.WIN, theme.LOSS, theme.ALERT):
            assert colour in theme.CATEGORICAL


class TestSequentialRamp:
    def test_ramp_runs_light_to_dark(self):
        def luminance(hex_colour: str) -> float:
            h = hex_colour.lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        lums = [luminance(c) for c in theme.SEQUENTIAL_GREEN]

        assert lums == sorted(lums, reverse=True)

    def test_endpoints_map_to_the_ends_of_the_ramp(self):
        n = 5
        assert theme.sequential(0, n) == theme.SEQUENTIAL_GREEN[0]
        assert theme.sequential(n - 1, n) == theme.SEQUENTIAL_GREEN[-1]

    def test_single_step_is_a_mid_tone(self):
        assert theme.sequential(0, 1) in theme.SEQUENTIAL_GREEN

    def test_never_indexes_past_the_ramp(self):
        for n in range(1, 12):
            for i in range(n):
                assert theme.sequential(i, n) in theme.SEQUENTIAL_GREEN


class TestPlotlyConfig:
    def test_responsive_is_enabled(self):
        """Without this a figure bakes in its render width and clips on a phone."""
        assert theme.PLOTLY_CONFIG["responsive"] is True

    def test_layout_uses_the_validated_colourway(self):
        assert theme.LAYOUT_BASE["colorway"] == list(theme.CATEGORICAL)

    def test_legend_sits_below_the_plot(self):
        """Keeps the full width available for the plot on narrow screens."""
        assert theme.LAYOUT_BASE["legend"]["y"] < 0


class TestPageCSS:
    def test_css_renders_without_unresolved_placeholders(self):
        css = theme.page_css()

        assert "{" in css                      # real CSS braces survive
        assert "{PRESS_BOX}" not in css        # ...but no f-string leftovers
        assert "None" not in css

    def test_includes_the_mobile_table_pattern(self):
        css = theme.page_css()

        assert ".table-scroll" in css
        assert "position: sticky" in css
        assert ".scroll-hint" in css

    def test_defines_a_narrow_screen_breakpoint(self):
        assert "@media (max-width:" in theme.page_css()

    def test_fonts_link_requests_the_display_faces(self):
        assert "Alfa+Slab+One" in theme.FONTS_LINK
        assert "Share+Tech+Mono" in theme.FONTS_LINK
