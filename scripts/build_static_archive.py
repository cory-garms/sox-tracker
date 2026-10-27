"""Package committed reports for offseason hosting, using only the standard library.

Run from any directory: python scripts/build_static_archive.py
The output is disposable; the original reports and data remain untouched.
"""

from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "offseason"
ROUTES = {
    "index": "index.html",
    "board": "tonights_board_BOS_2026.html",
    "tonights_board": "tonights_board_BOS_2026.html",
    "betting": "tonights_board_BOS_2026.html",
    "models": "models_BOS_2026.html",
    "matchup": "matchup_BOS_2026.html",
    "method": "method_BOS_2026.html",
    "track_record": "track_record_BOS_2026.html",
    "record": "track_record_BOS_2026.html",
    "dashboard": "dashboard_BOS_2026.html",
    "leaders": "leaders_BOS_2026.html",
    "notebook": "notebook_BOS_2026.html",
    "blog": "notebook_BOS_2026.html",
    "streaks": "streak_records_BOS_2026.html",
    "streak_records": "streak_records_BOS_2026.html",
}
NOTICE = '''<aside aria-label="Season archive" style="background:#153d32;color:#fff;
padding:14px 18px;text-align:center;font:16px/1.5 system-ui,sans-serif">
<strong>2026 season archive</strong> &middot; Updates paused for the offseason.
Reports retain their original timestamps. Matchups, projections and odds are historical.
<a href="/" style="color:#ffe3a0;text-decoration:underline">All reports</a></aside>'''


def build():
    source = ROOT / "docs"
    # Fail before replacing any output if a required report is missing.
    for filename in set(ROUTES.values()):
        if not (source / filename).is_file():
            raise FileNotFoundError(source / filename)
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    for page in source.glob("*.html"):
        html = page.read_text()
        html, count = re.subn(r"(<body\b[^>]*>)", lambda m: m[0] + NOTICE,
                              html, count=1, flags=re.IGNORECASE)
        if count != 1:
            raise ValueError(f"Missing body: {page}")
        (OUTPUT / page.name).write_text(html)
    shutil.copytree(source / "images", OUTPUT / "images")
    # Full pages at directory URLs preserve bookmarks without server routing.
    # A base URL keeps the original relative navigation and images working.
    for route, filename in ROUTES.items():
        directory = OUTPUT / route
        directory.mkdir()
        html = (OUTPUT / filename).read_text().replace("<head>", '<head><base href="/">', 1)
        (directory / "index.html").write_text(html)
    (OUTPUT / ".nojekyll").touch()
    (OUTPUT / "CNAME").write_text("dirtywater.corygarms.com\n")
    (OUTPUT / "404.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Report not found · Dirty Water</title><body>'
        '<h1>Report not found</h1><p><a href="/">Browse the 2026 archive</a></p></body></html>'
    )
    print(f"Static archive: {OUTPUT}")


if __name__ == "__main__":
    build()
