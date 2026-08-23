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



@app.get("/", include_in_schema=False)
def root_page():
    """Default landing page -> Tonight's Board."""
    return _serve_page(f"tonights_board_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.get("/board", include_in_schema=False)
def board_page():
    return _serve_page(f"tonights_board_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.get("/models", include_in_schema=False)
def models_page():
    return _serve_page(f"models_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.get("/method", include_in_schema=False)
def method_page():
    return _serve_page(f"method_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.get("/matchup", include_in_schema=False)
def matchup_page():
    return _serve_page(f"matchup_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page():
    return _serve_page(f"dashboard_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.get("/leaders", include_in_schema=False)
def leaders_page():
    return _serve_page(f"leaders_{config.TEAM_ABBR}_{config.SEASON}.html")


@app.get("/streaks", include_in_schema=False)
def streaks_page():
    return _serve_page(f"streak_records_{config.TEAM_ABBR}_{config.SEASON}.html")


# Mount static assets if docs directory exists
if DOCS_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DOCS_DIR)), name="static")
