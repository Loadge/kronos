"""The build id: one fingerprint of the files the browser loads, shown in three places.

``compute_build_id`` hashes everything under ``backend/static`` and ``backend/app/templates``.
The same value is the ``?v=`` on styles.css and app.js, the ``kronos-build`` meta tag the page
compares against, ``GET /api/version`` and the service worker's cache name. If any of those
disagreed, the "Update ready" pill would show forever or never.
"""

from __future__ import annotations

import re

from app.main import BUILD_ID
from app.version import APP_VERSION, compute_build_id

HEX10 = re.compile(r"^[0-9a-f]{10}$")


def _tree(tmp_path):
    static = tmp_path / "static"
    templates = tmp_path / "templates"
    (static / "vendor").mkdir(parents=True)
    templates.mkdir()
    (static / "app.js").write_bytes(b"console.log(1);\n")
    (static / "vendor" / "lib.js").write_bytes(b"lib")
    (templates / "index.html").write_bytes(b"<html></html>\n")
    return static, templates


class TestComputeBuildId:
    def test_ten_hex_characters(self, tmp_path):
        assert HEX10.match(compute_build_id(_tree(tmp_path)))

    def test_stable_between_two_calls(self, tmp_path):
        roots = _tree(tmp_path)
        assert compute_build_id(roots) == compute_build_id(roots)

    def test_changes_when_a_file_changes(self, tmp_path):
        static, templates = _tree(tmp_path)
        before = compute_build_id((static, templates))
        (static / "app.js").write_bytes(b"console.log(2);\n")
        assert compute_build_id((static, templates)) != before

    def test_changes_when_a_nested_file_changes(self, tmp_path):
        static, templates = _tree(tmp_path)
        before = compute_build_id((static, templates))
        (static / "vendor" / "lib.js").write_bytes(b"lib2")
        assert compute_build_id((static, templates)) != before

    def test_changes_when_a_file_is_renamed(self, tmp_path):
        static, templates = _tree(tmp_path)
        before = compute_build_id((static, templates))
        (templates / "index.html").rename(templates / "home.html")
        assert compute_build_id((static, templates)) != before

    def test_same_files_somewhere_else_give_the_same_id(self, tmp_path):
        a = _tree(tmp_path / "a")
        b = _tree(tmp_path / "b")
        assert compute_build_id(a) == compute_build_id(b)

    def test_the_build_id_of_the_running_app_is_ten_hex_characters(self):
        assert HEX10.match(BUILD_ID)


class TestVersionEndpoint:
    def test_reports_the_phase_number_and_the_build(self, client):
        r = client.get("/api/version")
        assert r.status_code == 200
        assert r.json() == {"version": "42", "build": BUILD_ID}
        assert HEX10.match(r.json()["build"])
        assert APP_VERSION == "42"

    def test_is_never_cached(self, client):
        assert client.get("/api/version").headers["cache-control"] == "no-store"


class TestIndexPage:
    def test_is_revalidated_every_time(self, client):
        assert client.get("/").headers["cache-control"] == "no-cache"

    def test_carries_the_same_build_as_the_api(self, client):
        build = client.get("/api/version").json()["build"]
        html = client.get("/").text
        assert f'<meta name="kronos-build" content="{build}">' in html
        assert f"/static/app.js?v={build}" in html
        assert f"/static/styles.css?v={build}" in html

    def test_shows_the_version_label_next_to_the_title(self, client):
        html = client.get("/").text
        assert re.search(r"<h1>Kronos</h1>\s*<span class=\"brand-ver\"[^>]*>v42</span>", html)

    def test_has_the_update_pill(self, client):
        assert 'class="update-pill"' in client.get("/").text


class TestServiceWorker:
    def test_the_build_replaces_the_token(self, client):
        r = client.get("/sw.js")
        build = client.get("/api/version").json()["build"]
        assert r.status_code == 200
        assert build in r.text
        assert "__BUILD__" not in r.text
        assert f"kronos-{build}" in r.text

    def test_headers(self, client):
        r = client.get("/sw.js")
        assert r.headers["content-type"].startswith("application/javascript")
        assert r.headers["service-worker-allowed"] == "/"
        assert r.headers["cache-control"] == "no-cache"

    def test_the_shell_is_fetched_network_first_and_the_api_never_cached(self, client):
        js = client.get("/sw.js").text
        assert "networkFirst" in js
        assert "/api/" in js
