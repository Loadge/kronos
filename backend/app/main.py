"""FastAPI application entry point. Wires routers, static files, and the SPA shell."""

from __future__ import annotations

import hashlib

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware

from app.config import STATIC_DIR, TEMPLATES_DIR
from app.routers import (
    admin,
    analytics,
    backup,
    clock,
    entries,
    export,
    freelance,
    fx,
    holidays,
    plans,
    timesheet,
)
from app.routers import (
    config as config_router,
)
from app.routers import (
    templates as templates_router,
)

app = FastAPI(
    title="Kronos",
    description="Personal hours tracker",
    version="1.0.0",
)

# app.js alone is ~130 KB and a year of entries is a few hundred KB of JSON: gzip cuts
# both to a fifth. A proxy that already compresses leaves an encoded body alone.
app.add_middleware(GZipMiddleware, minimum_size=1000)


def _vendor_version() -> str:
    """A short content hash of the vendored libraries, used as their URL query string.

    With it the browser may keep ``/static/vendor/*`` for a year: bumping a library
    changes the hash, so the page asks for a new URL and the old cache is never hit.
    """
    digest = hashlib.sha1()
    for path in sorted((STATIC_DIR / "vendor").glob("*")):
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


VENDOR_VERSION = _vendor_version()


class VendorCacheMiddleware:
    """Long cache for the vendored libraries.

    ``/static/vendor/*`` only changes when a library is bumped, and then the page links
    it under a new ``?v=`` (see ``_vendor_version``), so the browser may keep it for a
    year; everything else keeps Starlette's ETag / Last-Modified revalidation. Pure
    ASGI, no body buffering.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/static/vendor/"):
            await self.app(scope, receive, send)
            return

        async def send_with_cache(message) -> None:
            if message["type"] == "http.response.start" and message.get("status") == 200:
                headers = [(k, v) for k, v in message["headers"] if k.lower() != b"cache-control"]
                headers.append((b"cache-control", b"public, max-age=31536000, immutable"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cache)


app.add_middleware(VendorCacheMiddleware)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

app.include_router(entries.router)
app.include_router(analytics.router)
app.include_router(export.router)
app.include_router(config_router.router)
app.include_router(admin.router)
app.include_router(backup.router)
app.include_router(holidays.router)
app.include_router(templates_router.router)
app.include_router(plans.router)
app.include_router(timesheet.router)
app.include_router(clock.router)
app.include_router(fx.router)
app.include_router(freelance.router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request):
    # Starlette ≥0.35 expects (request, name) ordering; the old (name, {"request": ...})
    # form breaks Jinja's template cache lookup.
    return templates.TemplateResponse(request, "index.html", {"vendor_v": VENDOR_VERSION})


@app.get("/manifest.json", include_in_schema=False)
def manifest():
    return FileResponse(STATIC_DIR / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Must be served from scope root (not /static/) so it can control all pages.
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}
