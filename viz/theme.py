"""
Fenway Park visual theme — the single source of truth for colour, type, and chrome
across every HTML page and Plotly figure in the suite.

Before this module each exporter carried its own copy of the palette constants,
so a design change meant editing five files and hoping they stayed in sync.
Import from here instead.

--- Colour policy ------------------------------------------------------------

Chart marks are NOT chosen by taste. `CATEGORICAL` is a fixed-order sequence
validated against the data-viz checks (OKLCH lightness band, chroma floor,
Machado-Oliveira-Fernandes CVD separation, normal-vision floor, WCAG contrast)
on the dark press-box surface:

    Lightness band       all 4 inside L 0.48-0.67
    Chroma floor         all 4 >= 0.10
    CVD separation       worst adjacent dE 12.6 (deutan)   [target >= 8]
    Normal-vision floor  worst adjacent dE 21.1            [floor  >= 15]
    Contrast vs surface  all 4 >= 3.0:1

Rules that keep it valid:
  * Assign categorical hues in fixed order. Never cycle, never generate a 5th.
  * A 5th series folds into "Other", small multiples, or a sequential ramp.
  * Ordered categories (thresholds, tiers, buckets) use SEQUENTIAL_GREEN — one
    hue light->dark — not categorical hues.
  * WIN/LOSS keep their semantic colours and are exempt from the fixed order.
  * Re-run the validator if any value here changes.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Surfaces & ink — the ballpark at night
# ---------------------------------------------------------------------------
PRESS_BOX      = "#0E1714"   # deep night-game background
MONSTER_CARD   = "#152620"   # Green Monster card / Plotly paper
MONSTER_DARK   = "#00483A"   # scoreboard slats, card headers
MIDNIGHT_NAVY  = "#0C2340"   # classic Red Sox navy
TURF_GRID      = "#244035"   # faint grid lines
BRASS          = "#C5A059"   # aged brass borders & dividers
PARCHMENT      = "#F6F1E3"   # aged ticket stock — primary ink on dark
INK_MUTED      = "#9DB0A5"   # secondary text

# ---------------------------------------------------------------------------
# Chart marks — validated, fixed order. Do not reorder casually.
# ---------------------------------------------------------------------------
OUTFIELD_GREEN = "#4E9F3D"
NAVY_BLUE      = "#4391e9"
FENWAY_CRIMSON = "#BD3039"
SCOREBOARD_GOLD = "#b08a02"

CATEGORICAL: tuple[str, ...] = (
    OUTFIELD_GREEN,
    NAVY_BLUE,
    FENWAY_CRIMSON,
    SCOREBOARD_GOLD,
)

# Semantic — meaning is fixed, so these bypass the categorical order.
WIN   = OUTFIELD_GREEN
LOSS  = FENWAY_CRIMSON
ALERT = SCOREBOARD_GOLD

# Ordered categories: one hue, light -> dark. Monotone L with ~0.10 gaps.
SEQUENTIAL_GREEN: tuple[str, ...] = (
    "#67d54f", "#44b429", "#2b9308", "#1d7101", "#105100",
)


def categorical(i: int) -> str:
    """Nth categorical hue. Raises past the validated set rather than cycling."""
    if i >= len(CATEGORICAL):
        raise IndexError(
            f"No validated {i + 1}th categorical hue — fold extra series into "
            f"'Other', use small multiples, or switch to SEQUENTIAL_GREEN."
        )
    return CATEGORICAL[i]


def sequential(i: int, n: int) -> str:
    """Step i of n along the green ramp, light -> dark."""
    if n <= 1:
        return SEQUENTIAL_GREEN[2]
    pos = round(i * (len(SEQUENTIAL_GREEN) - 1) / (n - 1))
    return SEQUENTIAL_GREEN[min(pos, len(SEQUENTIAL_GREEN) - 1)]


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
FONTS_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '  <link href="https://fonts.googleapis.com/css2?'
    'family=Alfa+Slab+One&family=Share+Tech+Mono&family=Graduate&display=swap" '
    'rel="stylesheet">'
)

FONT_DISPLAY = "'Alfa Slab One', Georgia, 'Times New Roman', serif"
FONT_STENCIL = "'Graduate', Georgia, serif"
FONT_MONO    = "'Share Tech Mono', 'Courier New', monospace"
FONT_BODY    = "Georgia, 'Iowan Old Style', 'Times New Roman', serif"

# ---------------------------------------------------------------------------
# Plotly
# ---------------------------------------------------------------------------
LAYOUT_BASE = dict(
    paper_bgcolor=MONSTER_CARD,
    plot_bgcolor=PRESS_BOX,
    font=dict(color=PARCHMENT, family="Georgia, 'Times New Roman', serif", size=13),
    xaxis=dict(gridcolor=TURF_GRID, zerolinecolor=TURF_GRID),
    yaxis=dict(gridcolor=TURF_GRID, zerolinecolor=TURF_GRID),
    colorway=list(CATEGORICAL),
    margin=dict(l=40, r=20, t=65, b=70),
    legend=dict(
        orientation="h",
        yanchor="top",
        y=-0.22,
        xanchor="center",
        x=0.5,
        bgcolor="rgba(0,0,0,0)",
        bordercolor=TURF_GRID,
    ),
    hoverlabel=dict(
        bgcolor=MONSTER_DARK,
        bordercolor=BRASS,
        font=dict(color=PARCHMENT, family="Georgia, serif"),
    ),
)


# Spread into apply() for charts plotted against a shared X axis:
#
#     theme.apply(fig, **theme.TIME_SERIES_HOVER, xaxis_title="Game Number")
#
# Plotly's default hovermode is "closest", which asks for a tap within a few
# pixels of a marker. That is a fine mouse target and a poor thumb one — on a
# phone, a 162-point trajectory line is mostly gaps. "x unified" widens the
# target to the whole column and reads every series at that game in one label,
# which is also the comparison the dual-axis charts exist to make.
#
# Deliberately opt-in: on a horizontal bar leaderboard "x unified" groups by
# value rather than by player, and on a heatmap it means nothing at all.
TIME_SERIES_HOVER = {
    "hovermode": "x unified",
    "spikedistance": -1,
    "xaxis": dict(
        showspikes=True,
        spikemode="across",
        spikethickness=1,
        spikedash="dot",
        spikecolor=BRASS,
    ),
}


# Passed to every pio.to_html call. `responsive` is what makes a figure resize
# to its container instead of baking in the width it was first rendered at —
# without it, charts render wider than a phone viewport and get clipped.
PLOTLY_CONFIG = {
    "responsive": True,
    "displaylogo": False,
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
}


def apply(fig, **extra):
    """Apply the ballpark theme to a Plotly figure."""
    fig.update_layout(**{**LAYOUT_BASE, **extra})
    # automargin lets long tick labels claim the room they need instead of
    # being clipped; title wrapping keeps headings inside a narrow viewport.
    fig.update_xaxes(gridcolor=TURF_GRID, zerolinecolor=TURF_GRID, automargin=True)
    fig.update_yaxes(gridcolor=TURF_GRID, zerolinecolor=TURF_GRID, automargin=True)
    fig.update_layout(autosize=True)
    return fig


# ---------------------------------------------------------------------------
# Page chrome — shared CSS for every exported HTML page
# ---------------------------------------------------------------------------
def page_css() -> str:
    """Vintage ballpark CSS: Green Monster header, ticket-stub cards, brass rules."""
    return f"""
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      background:
        repeating-linear-gradient(90deg,
          rgba(0,0,0,0) 0 38px,
          rgba(255,255,255,0.012) 38px 39px),
        {PRESS_BOX};
      color: {PARCHMENT};
      font-family: {FONT_BODY};
      min-height: 100vh;
      width: 100%;
      overflow-x: hidden;
      -webkit-text-size-adjust: 100%;
    }}
    body {{ padding: clamp(12px, 3vw, 28px); }}

    /* ---- navigation ---- */
    .nav-bar {{ margin-bottom: 16px; }}
    .nav-back {{
      display: inline-flex; align-items: center; gap: 6px;
      color: {PARCHMENT}; text-decoration: none;
      font-family: {FONT_STENCIL}; font-size: 0.78rem;
      letter-spacing: 0.08em; text-transform: uppercase;
      padding: 7px 14px;
      background: {MONSTER_DARK};
      border: 1px solid {BRASS};
      border-radius: 3px;
      transition: background 0.18s ease;
    }}
    .nav-back:hover {{ background: {OUTFIELD_GREEN}; color: #06120d; }}

    /* Mode switch. Two segments sharing one border so they read as one
       control with a selected half, rather than as two buttons. Each half
       takes 50% so the pair is a stable target on a narrow screen instead of
       resizing with the label text. */
    .mode-switch {{
      display: flex; width: 100%;
      border: 1px solid {BRASS}; border-radius: 3px;
      overflow: hidden; margin-bottom: 10px;
    }}
    .mode-seg {{
      flex: 1 1 50%; text-align: center;
      padding: 10px 6px;
      font-family: {FONT_STENCIL}; font-size: clamp(0.66rem, 2.5vw, 0.8rem);
      letter-spacing: 0.06em; text-transform: uppercase;
      color: {INK_MUTED}; text-decoration: none;
      background: {PRESS_BOX};
      transition: background 0.18s ease, color 0.18s ease;
      /* 44px is the usual floor for a comfortable touch target. */
      min-height: 44px; display: flex; align-items: center; justify-content: center;
    }}
    .mode-seg + .mode-seg {{ border-left: 1px solid {BRASS}; }}
    .mode-seg.active {{
      background: {MONSTER_DARK}; color: {PARCHMENT};
      box-shadow: inset 0 -3px 0 {OUTFIELD_GREEN};
    }}
    a.mode-seg:hover {{ background: {TURF_GRID}; color: {PARCHMENT}; }}

    /* Method notes. The reasoning behind a number is read once; the number is
       read every night. Collapsing the former keeps the page scannable without
       deleting anything a reader might want to audit. */
    details.method {{
      margin-top: 12px;
      border-top: 1px solid {TURF_GRID};
      padding-top: 8px;
    }}
    .method-link {{
      margin-top: 10px; font-family: {FONT_STENCIL};
      font-size: 0.62rem; letter-spacing: 0.09em; text-transform: uppercase;
    }}
    .method-link a {{ color: {INK_MUTED}; text-decoration: none; }}
    .method-link a:hover {{ color: {BRASS}; }}

    details.method > summary {{
      cursor: pointer; list-style: none;
      font-family: {FONT_STENCIL}; font-size: 0.66rem;
      letter-spacing: 0.1em; text-transform: uppercase;
      color: {INK_MUTED};
      padding: 4px 0;
    }}
    details.method > summary::-webkit-details-marker {{ display: none; }}
    details.method > summary::before {{ content: "+ "; color: {BRASS}; }}
    details.method[open] > summary::before {{ content: "- "; }}
    details.method > summary:hover {{ color: {PARCHMENT}; }}
    details.method .table-note {{ margin-top: 6px; }}

    .nav-pages {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .nav-page {{
      color: {PARCHMENT}; text-decoration: none;
      font-family: {FONT_STENCIL}; font-size: 0.7rem;
      letter-spacing: 0.06em; text-transform: uppercase;
      padding: 7px 11px;
      background: {MONSTER_CARD};
      border: 1px solid {TURF_GRID};
      border-radius: 3px;
      transition: background 0.18s ease;
    }}
    a.nav-page:hover {{ background: {MONSTER_DARK}; border-color: {BRASS}; }}
    .nav-page.current {{
      background: {MONSTER_DARK}; border-color: {BRASS}; color: {PARCHMENT};
      cursor: default;
    }}
    .nav-page.index-link {{ color: {INK_MUTED}; background: transparent; }}

    /* ---- Green Monster header ---- */
    header {{
      background:
        repeating-linear-gradient(90deg,
          rgba(0,0,0,0.16) 0 2px,
          rgba(0,0,0,0) 2px 46px),
        linear-gradient(180deg, {MONSTER_DARK} 0%, #013528 100%);
      background-color: {MONSTER_DARK};
      border: 1px solid {BRASS};
      border-bottom-width: 3px;
      border-radius: 4px;
      padding: clamp(14px, 3vw, 24px);
      margin-bottom: clamp(20px, 4vw, 32px);
      display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    }}
    .team-logo {{
      height: clamp(46px, 9vw, 64px); width: auto;
      filter: drop-shadow(0 2px 8px rgba(0,0,0,0.55));
    }}
    header h1 {{
      font-family: {FONT_DISPLAY};
      font-size: clamp(1.15rem, 3.4vw, 1.9rem);
      font-weight: 400; color: {PARCHMENT};
      line-height: 1.2; letter-spacing: 0.01em;
      display: flex; align-items: center; flex-wrap: wrap; gap: 10px;
      text-shadow: 0 2px 0 rgba(0,0,0,0.45);
    }}
    header p {{
      color: #cfe0d4; margin-top: 8px;
      font-size: clamp(0.84rem, 2.2vw, 0.98rem); line-height: 1.5;
    }}

    /* ---- scoreboard number plate ---- */
    .badge {{
      background: {SCOREBOARD_GOLD}; color: #16130a;
      font-family: {FONT_MONO}; font-weight: 400;
      padding: 4px 11px; border-radius: 2px;
      border: 1px solid rgba(0,0,0,0.35);
      box-shadow: inset 0 -2px 0 rgba(0,0,0,0.28);
      font-size: clamp(0.72rem, 1.9vw, 0.84rem);
      letter-spacing: 0.06em; white-space: nowrap;
    }}

    /* ---- ticket-stub card ---- */
    .chart-card, .card {{
      background: {MONSTER_CARD};
      border: 2px dashed {BRASS};
      border-radius: 6px;
      padding: clamp(12px, 3vw, 24px);
      margin-bottom: clamp(16px, 3vw, 28px);
      width: 100%;
      overflow-x: auto;
      position: relative;
    }}
    /* corner notches — the stub tear */
    .chart-card::before, .chart-card::after {{
      content: ""; position: absolute; top: 50%;
      width: 13px; height: 13px; border-radius: 50%;
      background: {PRESS_BOX}; transform: translateY(-50%);
    }}
    .chart-card::before {{ left: -8px; }}
    .chart-card::after  {{ right: -8px; }}

    .chart-card h2, .card h2 {{
      font-family: {FONT_STENCIL};
      font-size: clamp(0.8rem, 2vw, 1.0rem);
      font-weight: 400; color: {SCOREBOARD_GOLD};
      text-transform: uppercase; letter-spacing: 0.1em;
      margin-bottom: 18px;
      padding-bottom: 8px;
      border-bottom: 1px solid rgba(197,160,89,0.28);
    }}

    /* ---- tables ----
       Wide stat tables can't fit a phone. Rather than shrink them into
       illegibility they scroll sideways inside .table-scroll, with the player
       column pinned so you never lose track of whose row you're reading. */
    .table-scroll {{
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      position: relative;
      scrollbar-color: {BRASS} transparent;
    }}
    .table-scroll::-webkit-scrollbar {{ height: 7px; }}
    .table-scroll::-webkit-scrollbar-thumb {{
      background: {BRASS}; border-radius: 4px;
    }}
    .scroll-hint {{
      display: none;
      font-family: {FONT_STENCIL};
      font-size: 0.64rem; letter-spacing: 0.12em;
      text-transform: uppercase; color: {BRASS};
      opacity: 0.8; margin-bottom: 8px;
    }}
    .report-table {{
      width: 100%; border-collapse: collapse;
      font-size: clamp(0.78rem, 2vw, 0.9rem);
    }}
    .report-table th:first-child,
    .report-table td:first-child {{
      position: sticky; left: 0; z-index: 2;
      background: {MONSTER_CARD};
      box-shadow: 1px 0 0 rgba(197,160,89,0.28);
    }}
    .report-table th {{
      font-family: {FONT_STENCIL};
      text-transform: uppercase; letter-spacing: 0.06em;
      font-size: 0.72rem; font-weight: 400;
      color: {SCOREBOARD_GOLD};
      text-align: left; padding: 10px 8px;
      border-bottom: 2px solid {BRASS};
      white-space: nowrap;
    }}
    .report-table td {{
      padding: 9px 8px;
      border-bottom: 1px solid rgba(197,160,89,0.16);
      color: {PARCHMENT};
    }}
    .report-table tbody tr:hover {{ background: rgba(0,72,58,0.42); }}
    .report-table td:nth-child(n+2) {{ font-family: {FONT_MONO}; }}

    .prop-line, .edge-val {{ font-family: {FONT_MONO}; color: {SCOREBOARD_GOLD}; }}
    .no-line {{ color: {INK_MUTED}; }}
    .table-note {{
      margin-top: 14px; font-size: 0.82rem; line-height: 1.55;
      color: {INK_MUTED};
      border-left: 3px solid {BRASS};
      padding: 8px 0 8px 12px;
    }}
    .table-note code {{
      font-family: {FONT_MONO}; color: {SCOREBOARD_GOLD};
      background: rgba(0,0,0,0.3); padding: 1px 5px; border-radius: 2px;
    }}

    /* ---- stat tiles ---- */
    .kpi-grid, .stat-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
    }}
    .kpi-card, .stat-tile {{
      background: rgba(0,0,0,0.3);
      border: 1px solid {BRASS};
      border-radius: 4px;
      padding: 14px 12px; text-align: center;
    }}
    .kpi-value, .stat-value {{
      font-family: {FONT_MONO};
      font-size: clamp(1.1rem, 3.2vw, 1.6rem);
      color: {SCOREBOARD_GOLD}; line-height: 1.2;
    }}
    /* long values (date ranges) — step down so the tile stays one line */
    .stat-value.compact {{
      font-size: clamp(0.82rem, 2.1vw, 1.02rem);
      letter-spacing: -0.01em;
    }}
    .kpi-label, .stat-label {{
      font-family: {FONT_STENCIL};
      font-size: clamp(0.64rem, 1.8vw, 0.72rem);
      color: {INK_MUTED};
      text-transform: uppercase; letter-spacing: 0.07em;
      margin-top: 7px;
    }}

    /* ---- badges ---- */
    .rec-badge {{
      display: inline-block; padding: 3px 9px; border-radius: 2px;
      font-family: {FONT_STENCIL}; font-size: 0.72rem;
      letter-spacing: 0.04em; white-space: nowrap;
    }}
    .rec-badge.over {{ background: {OUTFIELD_GREEN}; color: #06120d; }}
    .rec-badge.under {{ background: {NAVY_BLUE}; color: #04101d; }}
    .rec-badge.neu {{ background: rgba(197,160,89,0.2); color: {BRASS}; border: 1px solid {BRASS}; }}
    /* A model disagreeing with the market by more than its own error bar —
       reported as a defect, so it must not look like a pick. */
    .rec-badge.review {{
      background: transparent; color: {FENWAY_CRIMSON};
      border: 1px dashed {FENWAY_CRIMSON};
    }}
    .delta-pos {{ color: {OUTFIELD_GREEN}; }}
    .delta-neg {{ color: {FENWAY_CRIMSON}; }}
    .delta-neu {{ color: {INK_MUTED}; }}

    .plotly-graph-div {{ width: 100% !important; }}

    footer {{
      text-align: center; color: {INK_MUTED};
      font-size: 0.82rem; margin-top: 42px; padding-top: 18px;
      border-top: 1px solid {BRASS};
    }}
    footer a {{ color: {SCOREBOARD_GOLD}; text-decoration: none; }}
    .stamp {{
      font-family: {FONT_STENCIL}; font-size: 0.68rem;
      letter-spacing: 0.18em; text-transform: uppercase;
      color: {BRASS}; opacity: 0.75; margin-top: 8px;
    }}

    @media (max-width: 700px) {{
      .scroll-hint {{ display: block; }}
      /* tighter cells so more columns land in the first screenful */
      .report-table {{ font-size: 0.76rem; }}
      .report-table th, .report-table td {{ padding: 7px 6px; }}
      .report-table th {{ font-size: 0.64rem; }}
    }}

    @media (max-width: 600px) {{
      body {{ padding: 10px 8px; }}
      .chart-card, .card {{ padding: 10px 8px; border-radius: 4px; }}
      /* the stub notches read as clipping artefacts at phone width */
      .chart-card::before, .chart-card::after {{ display: none; }}
      header {{ padding: 12px; }}
      .kpi-grid, .stat-grid {{ grid-template-columns: repeat(2, 1fr); }}
    }}
"""


# ---------------------------------------------------------------------------
# Site navigation
# ---------------------------------------------------------------------------
#
# The suite grew into two genuinely different things that happen to share a
# theme. One is a season record - what has happened, settled, and worth
# browsing. The other is a live board that is stale within the hour and exists
# to support a decision before first pitch. Reading them as one undifferentiated
# list of five pages made the betting work harder to find the moment it became
# the part with the most in it.
#
# The mode is derived from whichever page you are on rather than stored. A
# toggle that remembers a preference can disagree with the page actually being
# displayed; deriving it means the control can never be wrong, and it needs no
# storage, no script, and no hydration on a static file.

MODE_SEASON = "season"
MODE_BETTING = "betting"

MODE_LABELS = {
    MODE_SEASON: "&#128202; Season &amp; Matchup",
    MODE_BETTING: "&#127922; Odds &amp; Models",
}

# slug -> (filename, nav label, mode). Order within a mode is nav order, and the
# first entry of each mode is where its toggle lands.
PAGES: dict[str, tuple[str, str, str]] = {
    # Season & Matchup (Primary baseball stats & game intelligence)
    "matchup":   ("matchup_BOS_2026.html",        "Today's Matchup",    MODE_SEASON),
    "dashboard": ("dashboard_BOS_2026.html",     "Season Dashboard",   MODE_SEASON),
    "leaders":   ("leaders_BOS_2026.html",        "Stat Leaders",       MODE_SEASON),
    "streaks":   ("streak_records_BOS_2026.html", "Win Streaks",        MODE_SEASON),
    # Odds & Models (Secondary analytical & betting models)
    "board":     ("tonights_board_BOS_2026.html", "Tonight's Board",    MODE_BETTING),
    "models":    ("models_BOS_2026.html",         "Models &amp; Method", MODE_BETTING),
    "record":    ("track_record_BOS_2026.html",   "Track Record",       MODE_BETTING),
    "method":    ("method_BOS_2026.html",         "How This Works",     MODE_BETTING),
}


def _mode_landing(mode: str) -> str:
    """The page a mode's toggle navigates to - its first registered page."""
    for filename, _, page_mode in PAGES.values():
        if page_mode == mode:
            return filename
    return "index.html"


def nav_bar(current: str) -> str:
    """
    The mode switch and the current mode's page links.

    `current` is a key of PAGES. An unknown key degrades to the season mode with
    nothing marked active, which is the right failure for a nav: a page that
    forgot to register itself should still be navigable.

    Rendered from one place because the five generators previously carried five
    identical copies of a "Back to Suite Index" link, and a nav that has to be
    edited in five files is a nav that will eventually differ in five files.
    """
    entry = PAGES.get(current)
    mode = entry[2] if entry else MODE_SEASON

    switch = ""
    for candidate, label in MODE_LABELS.items():
        active = " active" if candidate == mode else ""
        href = "#" if candidate == mode else _mode_landing(candidate)
        # The active segment is a span, not a link to where you already are.
        if candidate == mode:
            switch += f'<span class="mode-seg{active}">{label}</span>'
        else:
            switch += f'<a href="{href}" class="mode-seg">{label}</a>'

    links = ""
    for slug, (filename, label, page_mode) in PAGES.items():
        if page_mode != mode:
            continue
        if slug == current:
            links += f'<span class="nav-page current">{label}</span>'
        else:
            links += f'<a href="{filename}" class="nav-page">{label}</a>'

    return f"""  <div class="nav-bar">
    <div class="mode-switch" role="tablist" aria-label="Section">{switch}</div>
    <div class="nav-pages">{links}
      <a href="index.html" class="nav-page index-link">All pages</a>
    </div>
  </div>"""
