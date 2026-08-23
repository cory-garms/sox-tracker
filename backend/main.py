"""
Main FastAPI application for dirtywater.corygarms.com.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import config
from backend.api.routes import router as api_router
from backend.database import init_db
from backend.services.scheduler import start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("dirtywater")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager: initialize database and background scheduler."""
    log.info("Starting dirtywater backend on %s...", config.DATABASE_URL)
    try:
        init_db()
    except Exception as e:
        log.error("Database init warning: %s", e)

    sched = None
    try:
        sched = start_scheduler()
    except Exception as e:
        log.error("Scheduler start warning: %s", e)

    yield

    if sched and hasattr(sched, "running") and sched.running:
        try:
            sched.shutdown()
        except Exception:
            pass
    log.info("dirtywater backend shutdown complete.")


app = FastAPI(
    title="dirtywater · Boston Red Sox Analytics & Betting Suite",
    description="Live betting intelligence, model predictions, closing line value, and team performance tracking.",
    version="2026.1",
    lifespan=lifespan,
)

# CORS Configuration for dirtywater.corygarms.com and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST API
app.include_router(api_router)


# ---------------------------------------------------------------------------
# HTML Page Serving (with Cloudflare Edge Cache Headers)
# ---------------------------------------------------------------------------

DOCS_DIR = config.ROOT_DIR / "docs"


def _serve_page(filename: str) -> Response:
    """Serve an HTML dashboard using FileResponse with Edge caching headers."""
    path = DOCS_DIR / filename
    if not path.exists():
        return HTMLResponse(
            f"<h1>Page {filename} is generating...</h1><p>Please check back shortly.</p>",
            status_code=404,
        )

    headers = {
        "Cache-Control": "public, max-age=30, s-maxage=120, stale-while-revalidate=300",
    }
    return FileResponse(path, media_type="text/html", headers=headers)



ALIASES: dict[str, str] = {
    "board": f"tonights_board_{config.TEAM_ABBR}_{config.SEASON}.html",
    "models": f"models_{config.TEAM_ABBR}_{config.SEASON}.html",
    "matchup": f"matchup_{config.TEAM_ABBR}_{config.SEASON}.html",
    "method": f"method_{config.TEAM_ABBR}_{config.SEASON}.html",
    "dashboard": f"dashboard_{config.TEAM_ABBR}_{config.SEASON}.html",
    "leaders": f"leaders_{config.TEAM_ABBR}_{config.SEASON}.html",
    "streaks": f"streak_records_{config.TEAM_ABBR}_{config.SEASON}.html",
    "betting": f"betting_{config.TEAM_ABBR}_{config.SEASON}.html",
    "index": "index.html",
}


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def root_page():
    """Default landing page -> Tonight's Board."""
    return _serve_page(f"tonights_board_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.api_route("/{page_name:path}", methods=["GET", "HEAD"], include_in_schema=False)
def serve_dashboard_page(page_name: str):
    """
    Catch-all router to serve any dashboard HTML page, whether requested via
    exact filename (e.g. models_BOS_2026.html), clean slug (e.g. /models), or static asset.
    """
    # 1. Check if exact file exists in docs/
    target = DOCS_DIR / page_name
    if target.is_file():
        media_type = "text/html" if page_name.endswith(".html") else None
        headers = {
            "Cache-Control": "public, max-age=30, s-maxage=120, stale-while-revalidate=300",
        }
        return FileResponse(target, media_type=media_type, headers=headers)

    # 2. Check if appending .html matches a file
    if not page_name.endswith(".html"):
        target_html = DOCS_DIR / f"{page_name}.html"
        if target_html.is_file():
            return _serve_page(f"{page_name}.html")

    # 3. Check clean aliases (e.g. /board, /models, /dashboard)
    slug = page_name.lower().strip("/")
    if slug in ALIASES:
        return _serve_page(ALIASES[slug])

    return HTMLResponse(
        f"<h1>Page '{page_name}' Not Found</h1><p><a href='/'>Return to Tonight's Board</a></p>",
        status_code=404,
    )


# Mount static assets if docs directory exists
if DOCS_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DOCS_DIR)), name="static")

