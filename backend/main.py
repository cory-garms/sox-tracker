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
# HTML Dashboard Serving (with Edge Caching)
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


# Root landing page
@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def root_page():
    return _serve_page(f"tonights_board_{config.TEAM_ABBR}_{config.SEASON}.html")


# Exact HTML filename routes
@app.api_route(f"/tonights_board_{config.TEAM_ABBR}_{config.SEASON}.html", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/board", methods=["GET", "HEAD"], include_in_schema=False)
def page_board():
    return _serve_page(f"tonights_board_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.api_route(f"/models_{config.TEAM_ABBR}_{config.SEASON}.html", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/models", methods=["GET", "HEAD"], include_in_schema=False)
def page_models():
    return _serve_page(f"models_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.api_route(f"/matchup_{config.TEAM_ABBR}_{config.SEASON}.html", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/matchup", methods=["GET", "HEAD"], include_in_schema=False)
def page_matchup():
    return _serve_page(f"matchup_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.api_route(f"/method_{config.TEAM_ABBR}_{config.SEASON}.html", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/method", methods=["GET", "HEAD"], include_in_schema=False)
def page_method():
    return _serve_page(f"method_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.api_route(f"/dashboard_{config.TEAM_ABBR}_{config.SEASON}.html", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/dashboard", methods=["GET", "HEAD"], include_in_schema=False)
def page_dashboard():
    return _serve_page(f"dashboard_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.api_route(f"/leaders_{config.TEAM_ABBR}_{config.SEASON}.html", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/leaders", methods=["GET", "HEAD"], include_in_schema=False)
def page_leaders():
    return _serve_page(f"leaders_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.api_route(f"/streak_records_{config.TEAM_ABBR}_{config.SEASON}.html", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/streaks", methods=["GET", "HEAD"], include_in_schema=False)
def page_streaks():
    return _serve_page(f"streak_records_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.api_route(f"/betting_{config.TEAM_ABBR}_{config.SEASON}.html", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/betting", methods=["GET", "HEAD"], include_in_schema=False)
def page_betting():
    return _serve_page(f"betting_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.api_route("/index.html", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/index", methods=["GET", "HEAD"], include_in_schema=False)
def page_index():
    return _serve_page("index.html")


# Static files mount (for /images/..., /static/..., etc.)
if DOCS_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DOCS_DIR)), name="static")
    app.mount("/images", StaticFiles(directory=str(DOCS_DIR / "images") if (DOCS_DIR / "images").exists() else str(DOCS_DIR)), name="images")


