"""
Refresh navigation bars across all docs/*.html files to match viz/theme.py.
"""

from __future__ import annotations

import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viz import theme

DOCS = ROOT / "docs"

NAV_REGEX = re.compile(r'<div class="nav-bar">.*?</div>\s*</div>', re.DOTALL)

# docs/index.html is hand-maintained rather than generated from theme.PAGES, so
# it never picks anything up at build time -- and it is the URL most likely to
# be shared, which makes it the worst page to be missing analytics from. The
# markers let this run be idempotent: the tag is replaced between them, not
# appended, so repeated runs cannot stack up copies.
ANALYTICS_START = "<!-- analytics:start -->"
ANALYTICS_END = "<!-- analytics:end -->"
ANALYTICS_REGEX = re.compile(
    re.escape(ANALYTICS_START) + r".*?" + re.escape(ANALYTICS_END), re.DOTALL
)


def refresh_all_navs():
    for slug, (filename, _, _) in theme.PAGES.items():
        path = DOCS / filename
        if not path.exists():
            print(f"Skipping {filename} (not found)")
            continue

        content = path.read_text(encoding="utf-8")
        new_nav = theme.nav_bar(slug)

        if NAV_REGEX.search(content):
            updated = NAV_REGEX.sub(new_nav, content, count=1)
            path.write_text(updated, encoding="utf-8")
            print(f"✓ Updated nav in {filename}")
        else:
            print(f"! No nav-bar found in {filename}")


def sync_analytics(paths=None) -> int:
    """
    Keep the analytics tag current in the hand-maintained pages.

    Generated pages call theme.analytics_tag() at build time and need nothing
    here. index.html is written by hand, so without this it is the one page
    that never gets counted.

    With ANALYTICS_SRC unset this writes an empty block, which is how the tag
    gets *removed* again -- turning analytics off must actually turn it off,
    not leave a stale script tag behind in a file nobody regenerates.
    """
    block = f"{ANALYTICS_START}\n{theme.analytics_tag()}\n  {ANALYTICS_END}"
    changed = 0
    for path in (paths if paths is not None else [DOCS / "index.html"]):
        if not path.exists():
            print(f"Skipping {path.name} (not found)")
            continue
        content = path.read_text(encoding="utf-8")
        if ANALYTICS_REGEX.search(content):
            updated = ANALYTICS_REGEX.sub(block, content, count=1)
        elif "</head>" in content:
            updated = content.replace("</head>", f"  {block}\n</head>", 1)
        else:
            print(f"! No <head> in {path.name}")
            continue
        if updated != content:
            path.write_text(updated, encoding="utf-8")
            changed += 1
            print(f"✓ Analytics tag synced in {path.name}")
    return changed


if __name__ == "__main__":
    refresh_all_navs()
    sync_analytics()
