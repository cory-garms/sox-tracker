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


if __name__ == "__main__":
    refresh_all_navs()
