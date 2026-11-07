"""FastAPI application entry point. Wires routers, static files, and the SPA shell."""

from __future__ import annotations

import hashlib

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from app.config import STATIC_DIR, TEMPLATES_DIR
from app.routers import (
    admin,
    analytics,
    backup,
    clock,
    currencies,
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
from app.version import APP_VERSION, compute_build_id

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

# One fingerprint of everything the browser loads (static files and templates), computed once
# at import: the same files always give the same id, and a deploy that changes any of them
# gives a new one. The page, the service worker and /api/version all report this value.
BUILD_ID = compute_build_id([STATIC_DIR, TEMPLATES_DIR])


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

# What the browser may load and do, as tight as the app allows. Alpine's standard build compiles
# its expressions with `new Function`, hence 'unsafe-eval'; the `:style` bindings set inline styles,
# hence 'unsafe-inline' for styles only. Nothing is loaded from another origin: the exchange rates
# and the holidays are fetched by the server, never by the page.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-eval'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "manifest-src 'self'",
        "worker-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)

SECURITY_HEADERS = {
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "x-frame-options": "DENY",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


class SecurityHeadersMiddleware:
    """The same security headers on every response: the page, the API, the static files, the errors.

    Pure ASGI, no body buffering. A header a route set itself is left alone.
    """

    def __init__(self, app) -> None:
        self.app = app
        self.extra = [
            (k.encode("latin-1"), v.encode("latin-1")) for k, v in SECURITY_HEADERS.items()
        ]

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message["headers"]}
                headers = [*message["headers"], *(h for h in self.extra if h[0] not in present)]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


# Added last, so it is the outermost layer and also covers the responses of the others.
app.add_middleware(SecurityHeadersMiddleware)

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
app.include_router(currencies.router)
app.include_router(freelance.router)


def site_origin(request: Request) -> str:
    """``scheme://host`` as the browser sent it, for the absolute URLs of the link preview.

    The scheme is ``X-Forwarded-Proto`` when a reverse proxy sets it (the server is started with
    proxy headers trusted, so ``request.url.scheme`` already follows it there; reading the header
    here keeps the page right however the app is started), the host is the ``Host`` header. Nothing
    is configured: no host name is written anywhere in the repository.
    """
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    scheme = forwarded if forwarded in ("http", "https") else request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request):
    # Starlette ≥0.35 expects (request, name) ordering; the old (name, {"request": ...})
    # form breaks Jinja's template cache lookup.
    response = templates.TemplateResponse(
        request,
        "index.html",
        {
            "vendor_v": VENDOR_VERSION,
            "app_version": APP_VERSION,
            "build": BUILD_ID,
            "origin": site_origin(request),
        },
    )
    # The shell is revalidated on every visit; the assets it links are fingerprinted per build.
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/version", include_in_schema=False)
def version():
    """What the server is running. An open page compares ``build`` with the one it loaded."""
    return JSONResponse(
        {"version": APP_VERSION, "build": BUILD_ID}, headers={"Cache-Control": "no-store"}
    )


@app.get("/manifest.json", include_in_schema=False)
def manifest():
    return FileResponse(STATIC_DIR / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Must be served from scope root (not /static/) so it can control all pages. The file
    # carries a `__BUILD__` token (the build id hashes it in that raw form); filling it in
    # gives every build its own cache name and makes the browser see a new worker.
    source = (STATIC_DIR / "sw.js").read_bytes().decode("utf-8")
    return Response(
        source.replace("__BUILD__", BUILD_ID),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


# Not for search engines. The link-preview crawlers are named first: a group that matches a
# crawler replaces the `*` one, so a pasted link still gets its title and picture.
ROBOTS_TXT = (
    "\n\n".join(
        f"User-agent: {bot}\nAllow: /"
        for bot in ("facebookexternalhit", "TelegramBot", "WhatsApp", "Twitterbot")
    )
    + "\n\nUser-agent: *\nDisallow: /\n"
)


@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots():
    return PlainTextResponse(ROBOTS_TXT)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    """A wrong address typed in a browser gets a page; the API and files keep a plain 404."""
    path = request.url.path
    wants_page = (
        exc.status_code == 404
        and not path.startswith(("/api/", "/static/"))
        and "text/html" in request.headers.get("accept", "")
    )
    if wants_page:
        return templates.TemplateResponse(
            request,
            "404.html",
            {"vendor_v": VENDOR_VERSION, "build": BUILD_ID},
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )
    return await http_exception_handler(request, exc)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}
