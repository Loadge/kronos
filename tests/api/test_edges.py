"""The edges of the app: what a pasted link looks like, the icons, the manifest, the security
headers, robots.txt and the page for a wrong address."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from app.config import STATIC_DIR
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
HTML = {"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
PASTED = "https://kronos.example.test"


def _meta(html: str, key: str) -> str:
    """The content of a <meta property|name=key> tag."""
    m = re.search(rf'<meta (?:property|name)="{re.escape(key)}" content="([^"]*)"', html)
    assert m, f"no <meta> for {key}"
    return m.group(1)


# ── security headers ─────────────────────────────────────────────────────────────────────────


class TestSecurityHeaders:
    PATHS = [
        ("/", HTML),
        ("/static/app.js?v=x", {}),
        ("/static/vendor/pico.min.css", {}),
        ("/api/version", {}),
        ("/api/entries", {}),
        ("/manifest.json", {}),
        ("/sw.js", {}),
        ("/robots.txt", {}),
        ("/healthz", {}),
        ("/timesheet", HTML),
        ("/nope", HTML),
        ("/api/nope", {}),
        ("/static/missing.png", {}),
    ]

    @pytest.mark.parametrize("path,headers", PATHS)
    def test_every_response_carries_them(self, client, path, headers):
        r = client.get(path, headers=headers)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "same-origin"
        assert r.headers["x-frame-options"] == "DENY"
        permissions = r.headers["permissions-policy"]
        for feature in ("camera", "microphone", "geolocation", "payment"):
            assert f"{feature}=()" in permissions
        assert "content-security-policy" in r.headers

    def test_the_policy_is_tight_but_lets_alpine_run(self, client):
        csp = client.get("/").headers["content-security-policy"]
        directives = {d.split()[0]: d.split()[1:] for d in csp.split("; ")}
        assert directives["default-src"] == ["'self'"]
        # Alpine's standard build compiles its expressions with `new Function`
        assert directives["script-src"] == ["'self'", "'unsafe-eval'"]
        assert "'unsafe-inline'" not in directives["script-src"]
        assert directives["style-src"] == ["'self'", "'unsafe-inline'"]
        assert directives["img-src"] == ["'self'", "data:"]
        assert directives["frame-ancestors"] == ["'none'"]
        assert directives["base-uri"] == ["'self'"]
        assert directives["form-action"] == ["'self'"]
        # nothing is loaded from another origin
        assert not re.search(r"https?:", csp)

    def test_pages_load_nothing_from_another_origin_and_run_no_inline_script(self, client):
        for path in ("/", "/timesheet", "/timesheet/freelance"):
            html = client.get(path, headers=HTML).text
            assert not re.findall(r'(?:src|href)="https?://', html), path
            assert not re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", html), path
            assert not re.findall(r'\son[a-z]+="', html), path


# ── link preview ─────────────────────────────────────────────────────────────────────────────


class TestLinkPreview:
    def test_the_urls_are_absolute_and_follow_the_proxy(self, client):
        html = client.get(
            "/", headers={"Host": "kronos.example.test", "X-Forwarded-Proto": "https"}
        ).text
        assert _meta(html, "og:image") == f"{PASTED}/static/og.png"
        assert _meta(html, "og:url") == f"{PASTED}/"

    def test_without_a_proxy_the_scheme_is_the_requests(self, client):
        html = client.get("/", headers={"Host": "kronos.example.test"}).text
        assert _meta(html, "og:image") == "http://kronos.example.test/static/og.png"

    def test_an_odd_forwarded_scheme_is_ignored(self, client):
        html = client.get(
            "/", headers={"Host": "kronos.example.test", "X-Forwarded-Proto": 'javascript"><x'}
        ).text
        assert _meta(html, "og:image").startswith("http://kronos.example.test/")

    def test_the_host_cannot_break_out_of_the_tag(self, client):
        html = client.get("/", headers={"Host": 'a.test"><script>x</script>'}).text
        assert "<script>x</script>" not in html

    def test_the_tags(self, client):
        html = client.get("/", headers={"Host": "kronos.example.test"}).text
        text = "Your hours, your balance and your year, at a glance."
        assert _meta(html, "og:type") == "website"
        assert _meta(html, "og:site_name") == "Kronos"
        assert _meta(html, "og:title") == "Kronos"
        assert _meta(html, "og:description") == text
        assert _meta(html, "description") == text
        assert _meta(html, "og:image:width") == "1200"
        assert _meta(html, "og:image:height") == "630"
        assert _meta(html, "og:image:alt")
        assert _meta(html, "twitter:card") == "summary_large_image"
        assert _meta(html, "robots") == "noindex"
        assert _meta(html, "theme-color") == "#17140f"
        assert _meta(html, "color-scheme") == "dark"

    def test_the_picture_is_1200_by_630_and_light(self):
        path = STATIC_DIR / "og.png"
        assert path.stat().st_size < 300_000
        with Image.open(path) as image:
            assert image.size == (1200, 630)

    def test_the_repository_names_no_host(self):
        """The repository is mirrored in public: a host name belongs to a deployment."""
        for rel in ("backend/app/templates/index.html", "backend/static/manifest.json"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            assert not re.search(r"https?://(?!www\.w3\.org)", text), rel


# ── robots ───────────────────────────────────────────────────────────────────────────────────


class TestRobots:
    def test_no_search_engine_may_index_it(self, client):
        r = client.get("/robots.txt")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        lines = r.text.splitlines()
        assert lines[-2:] == ["User-agent: *", "Disallow: /"]

    def test_the_link_preview_crawlers_are_named_before_the_disallow(self, client):
        text = client.get("/robots.txt").text
        for bot in ("facebookexternalhit", "TelegramBot", "WhatsApp", "Twitterbot"):
            group = re.search(rf"User-agent: {bot}\nAllow: /\n", text)
            assert group and group.start() < text.index("Disallow: /"), bot


# ── the page for a wrong address ─────────────────────────────────────────────────────────────


class TestNotFound:
    def test_a_browser_gets_a_page_in_the_kronos_look(self, client):
        r = client.get("/nope", headers=HTML)
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("text/html")
        assert "This page isn't on the dial" in r.text
        assert "Back to Kronos" in r.text
        assert 'href="/"' in r.text
        assert "/static/icon-192.png" in r.text
        assert _meta(r.text, "robots") == "noindex"

    def test_a_deeper_path_too(self, client):
        r = client.get("/some/where/else", headers=HTML)
        assert r.status_code == 404 and "This page isn't on the dial" in r.text

    def test_the_api_keeps_its_json_even_for_a_browser(self, client):
        r = client.get("/api/nope", headers=HTML)
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")
        assert r.json() == {"detail": "Not Found"}

    def test_the_smoke_negative_control_is_still_a_404(self, client):
        r = client.get("/api/__smoke_negative_control__")
        assert r.status_code == 404

    def test_a_client_that_does_not_ask_for_html_gets_json(self, client):
        r = client.get("/nope", headers={"Accept": "application/json"})
        assert r.status_code == 404
        assert r.json() == {"detail": "Not Found"}

    def test_a_missing_static_file_is_a_plain_404(self, client):
        r = client.get("/static/missing.png", headers=HTML)
        assert r.status_code == 404
        assert "This page isn't on the dial" not in r.text
        assert not r.headers["content-type"].startswith("text/html")

    def test_other_errors_are_untouched(self, client):
        r = client.post("/robots.txt", headers=HTML)
        assert r.status_code == 405


# ── icons and manifest ───────────────────────────────────────────────────────────────────────


def _size_of(entry: dict) -> tuple[int, int]:
    w, h = entry["sizes"].split("x")
    return int(w), int(h)


def _file_of(src: str) -> Path:
    assert src.startswith("/static/"), src
    return STATIC_DIR / src.removeprefix("/static/")


class TestManifest:
    @pytest.fixture
    def manifest(self, client):
        r = client.get("/manifest.json")
        assert r.status_code == 200
        return r.json()

    def test_identity(self, manifest):
        assert manifest["name"] == "Kronos"
        assert manifest["description"] == "Your hours, your balance and your year, at a glance."
        assert manifest["background_color"] == "#17140f"
        assert manifest["theme_color"] == "#17140f"

    def test_the_icons_exist_with_the_sizes_they_state(self, manifest):
        assert {i["purpose"] for i in manifest["icons"]} == {"any", "maskable"}
        for icon in manifest["icons"]:
            with Image.open(_file_of(icon["src"])) as image:
                assert image.size == _size_of(icon), icon
                assert image.format == "PNG"

    def test_the_maskable_icon_is_opaque_on_the_background(self):
        with Image.open(STATIC_DIR / "icon-maskable-512.png") as image:
            rgb = image.convert("RGB")
            assert rgb.getpixel((0, 0)) == (0x17, 0x14, 0x0F)
            assert rgb.getpixel((511, 511)) == (0x17, 0x14, 0x0F)
            # the logo stays inside the safe zone: a circle of 40% of the side
            inside = rgb.crop((51, 51, 461, 461))
            assert inside.getbbox() is not None
            corners = [(60, 60), (451, 60), (60, 451), (451, 451)]
            assert all(rgb.getpixel(p) == (0x17, 0x14, 0x0F) for p in corners)

    def test_the_apple_touch_icon_is_opaque(self):
        with Image.open(STATIC_DIR / "apple-touch-icon.png") as image:
            assert image.size == (180, 180)
            assert image.mode == "RGB"
            assert image.getpixel((0, 0)) == (0x17, 0x14, 0x0F)

    def test_the_small_icons(self):
        for name, size in (("favicon-32.png", 32), ("icon-96.png", 96)):
            with Image.open(STATIC_DIR / name) as image:
                assert image.size == (size, size), name

    def test_the_shortcuts(self, manifest):
        shortcuts = {s["url"]: s for s in manifest["shortcuts"]}
        assert list(shortcuts) == ["/#log", "/#plan", "/#days", "/#dial"]
        assert shortcuts["/#log"]["name"] == "Log a day"
        assert shortcuts["/#plan"]["name"] == "Plan"
        assert shortcuts["/#days"]["name"] == "Days"
        assert shortcuts["/#dial"]["name"] == "The year dial"
        for shortcut in shortcuts.values():
            (icon,) = shortcut["icons"]
            assert icon["src"] == "/static/icon-96.png"
            with Image.open(_file_of(icon["src"])) as image:
                assert image.size == _size_of(icon)

    def test_the_screenshots(self, manifest):
        by_form = {s["form_factor"]: s for s in manifest["screenshots"]}
        assert set(by_form) == {"wide", "narrow"}
        for shot in by_form.values():
            path = _file_of(shot["src"])
            assert path.stat().st_size < 250_000
            with Image.open(path) as image:
                assert image.size == _size_of(shot)
                assert image.format == "WEBP"
                assert shot["type"] == "image/webp"
        assert _size_of(by_form["wide"]) == (1280, 800)
        assert _size_of(by_form["narrow"]) == (390, 844)

    def test_the_page_uses_the_new_icons_and_the_old_one_is_gone(self, client):
        html = client.get("/").text
        assert 'href="/static/favicon-32.png"' in html
        assert 'href="/static/apple-touch-icon.png"' in html
        assert 'src="/static/icon-96.png"' in html
        assert not (STATIC_DIR / "icon.png").exists()
        for rel in (
            "backend/app/templates",
            "backend/static/sw.js",
            "backend/static/manifest.json",
        ):
            files = [ROOT / rel] if (ROOT / rel).is_file() else list((ROOT / rel).glob("*"))
            for file in files:
                assert "/static/icon.png" not in file.read_text(encoding="utf-8"), file

    def test_everything_the_service_worker_precaches_exists(self, client):
        source = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
        block = source.split("PRECACHE_URLS = [", 1)[1].split("];", 1)[0]
        for url in re.findall(r"'([^']+)'", block):
            url = url.replace("__BUILD__", "x")
            assert client.get(url).status_code == 200, url

    def test_the_manifest_is_valid_json_without_a_host(self):
        text = (STATIC_DIR / "manifest.json").read_text(encoding="utf-8")
        json.loads(text)
        assert "://" not in text
