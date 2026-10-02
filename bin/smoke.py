"""Read-only HTTP smoke checks for a running Kronos.

What it checks
--------------
Each check is a plain GET with a 10 s timeout, run in this order:

    /healthz                        200, JSON object with "status" == "ok"
    /                               200, body contains "<title>", "Kronos", "/static/app.js"
    /static/app.js                  200, body longer than 1000 bytes
    /api/config                     200, JSON object
    /api/dashboard                  200, JSON object containing key "cumulative"
    /api/entries                    200, JSON list
    /api/analytics/monthly          200, JSON list
    /api/analytics/yearly           200, JSON list
    /api/analytics/records          200, JSON object
    /api/analytics/yoy              200, JSON object
    /api/__smoke_negative_control__ MUST be 404 (see "The negative control")

Safety
------
Every request is a GET with no body: nothing here mutates state, so it is safe
to point at a production instance. That is the point — deploy.sh runs this after
every deploy and trusts the exit code.

The negative control
--------------------
The last check must come back 404. If a proxy or a catch-all route answers 200
to anything, every other check would pass meaninglessly (any 200 would look
fine). If this one fails, the whole run is untrustworthy and must be treated
as red.

Usage
-----
    python bin/smoke.py http://127.0.0.1:8765

Exit codes: 0 every check passed, 1 at least one check failed, 2 bad usage.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable

TIMEOUT = 10.0  # seconds, per check

Validator = Callable[[int, bytes], str | None]


class Unreachable(Exception):
    """The server did not answer at all (connection refused, timeout, DNS, ...)."""


def get(url: str) -> tuple[int, bytes]:
    """GET url and return (status, body).

    Mirrors wctl.request(): an HTTPError is a real answer (its .code is the
    status), while a URLError / timeout is no answer at all -> Unreachable.
    """
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise Unreachable(str(exc.reason)) from exc
    except OSError as exc:  # socket-level failures (incl. timeout)
        raise Unreachable(str(exc)) from exc


def _expected_200(status: int) -> str | None:
    return None if status == 200 else f"expected 200, got {status}"


def _parse_json(body: bytes) -> tuple[object | None, str | None]:
    """Return (parsed, None) or (None, reason)."""
    try:
        return json.loads(body), None
    except json.JSONDecodeError:
        snippet = body[:120].decode(errors="replace")
        return None, f"body is not valid JSON ({snippet!r})"


def _check_json(status: int, body: bytes, want: type) -> str | None:
    if (err := _expected_200(status)) is not None:
        return err
    data, err = _parse_json(body)
    if err is not None:
        return err
    if not isinstance(data, want):
        return f"expected JSON {want.__name__}, got {type(data).__name__}"
    return None


def check_healthz(status: int, body: bytes) -> str | None:
    if (err := _expected_200(status)) is not None:
        return err
    data, err = _parse_json(body)
    if err is not None:
        return err
    if not isinstance(data, dict) or data.get("status") != "ok":
        return f'expected a JSON object with "status" == "ok", got {repr(data)[:120]}'
    return None


def check_index(status: int, body: bytes) -> str | None:
    if (err := _expected_200(status)) is not None:
        return err
    text = body.decode(errors="replace")
    missing = [token for token in ("<title>", "Kronos", "/static/app.js") if token not in text]
    if missing:
        return "index HTML is missing: " + ", ".join(missing)
    return None


def check_app_js(status: int, body: bytes) -> str | None:
    if (err := _expected_200(status)) is not None:
        return err
    if len(body) <= 1000:
        return f"app.js is only {len(body)} bytes (expected more than 1000)"
    return None


def check_api_config(status: int, body: bytes) -> str | None:
    return _check_json(status, body, dict)


def check_api_dashboard(status: int, body: bytes) -> str | None:
    if (err := _expected_200(status)) is not None:
        return err
    data, err = _parse_json(body)
    if err is not None:
        return err
    if not isinstance(data, dict):
        return f"expected JSON object, got {type(data).__name__}"
    if "cumulative" not in data:
        return 'JSON object has no "cumulative" key'
    return None


def check_api_entries(status: int, body: bytes) -> str | None:
    return _check_json(status, body, list)


def check_api_monthly(status: int, body: bytes) -> str | None:
    return _check_json(status, body, list)


def check_api_yearly(status: int, body: bytes) -> str | None:
    return _check_json(status, body, list)


def check_api_records(status: int, body: bytes) -> str | None:
    return _check_json(status, body, dict)


def check_api_yoy(status: int, body: bytes) -> str | None:
    return _check_json(status, body, dict)


def check_negative_control(status: int, body: bytes) -> str | None:
    if status != 404:
        return (
            f"expected 404, got {status} - a proxy or catch-all may be answering "
            "every request, so this whole run is untrustworthy"
        )
    return None


CHECKS: list[tuple[str, Validator]] = [
    ("/healthz", check_healthz),
    ("/", check_index),
    ("/static/app.js", check_app_js),
    ("/api/config", check_api_config),
    ("/api/dashboard", check_api_dashboard),
    ("/api/entries", check_api_entries),
    ("/api/analytics/monthly", check_api_monthly),
    ("/api/analytics/yearly", check_api_yearly),
    ("/api/analytics/records", check_api_records),
    ("/api/analytics/yoy", check_api_yoy),
    ("/api/__smoke_negative_control__", check_negative_control),
]


def _ascii(line: str) -> str:
    """ASCII-ify a line so a hostile locale codec can never crash the output."""
    return line.encode("ascii", "replace").decode("ascii")


def run_checks(base_url: str) -> int:
    total = len(CHECKS)
    passed = 0
    for path, validate in CHECKS:
        started = time.monotonic()
        status = 0
        reason: str | None
        try:
            status, body = get(f"{base_url}{path}")
            reason = validate(status, body)
        except Unreachable as exc:
            reason = f"no response ({exc})"
        except Exception as exc:  # a smoke script reports, it never tracebacks
            reason = f"unexpected error ({exc})"
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if reason is None:
            passed += 1
            print(_ascii(f"OK    GET {path}  {status}  {elapsed_ms}ms"))
        else:
            print(_ascii(f"FAIL  GET {path}  {reason}"))
    print(_ascii(f"smoke: {passed}/{total} checks passed against {base_url}"))
    return 0 if passed == total else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only HTTP smoke checks for a running Kronos (GET only, safe on prod).",
    )
    parser.add_argument(
        "base_url",
        help='base URL to check, e.g. http://127.0.0.1:8765 (a trailing "/" is stripped)',
    )
    args = parser.parse_args(argv)
    base_url = args.base_url.rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        parser.error(f"base-url must start with http:// or https://, got {args.base_url!r}")
    return run_checks(base_url)


if __name__ == "__main__":
    sys.exit(main())
