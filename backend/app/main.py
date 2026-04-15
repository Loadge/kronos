"""FastAPI application entry point. Wires routers, static files, and the SPA shell."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import STATIC_DIR, TEMPLATES_DIR
from app.routers import admin, analytics, config as config_router, entries, export

app = FastAPI(
    title="Kronos",
    description="Personal hours tracker",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

app.include_router(entries.router)
app.include_router(analytics.router)
app.include_router(export.router)
app.include_router(config_router.router)
app.include_router(admin.router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request):
    # Starlette ≥0.35 expects (request, name) ordering; the old (name, {"request": ...})
    # form breaks Jinja's template cache lookup.
    return templates.TemplateResponse(request, "index.html")


@app.get("/manifest.json", include_in_schema=False)
def manifest():
    return FileResponse(
        STATIC_DIR / "manifest.json", media_type="application/manifest+json"
    )


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}
