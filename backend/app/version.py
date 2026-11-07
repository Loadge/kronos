"""Which Kronos this is: the label people read and the fingerprint the browser compares.

``APP_VERSION`` is the phase number shown as "v50" next to the title. Miguel bumps it by
hand when a phase lands; nothing computes it.

``compute_build_id`` is the opposite: nobody types it. It is a short hash of the files the
browser loads, so it changes exactly when a deploy changes what the user sees. The page
carries it (``<meta name="kronos-build">``, the ``?v=`` of app.js and styles.css), the
service worker names its cache after it, and ``GET /api/version`` reports it, which is how
an open page learns that the server has moved on.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

APP_VERSION = "52"


def compute_build_id(root_dirs: Iterable[Path]) -> str:
    """A 10-character sha1 over every file under ``root_dirs``: paths and bytes.

    Files are visited in sorted order and their path relative to their root goes into the
    hash, so renaming a file changes the id as much as editing it does. Nothing else does:
    no timestamps and no absolute paths, so the same files give the same id on any host.
    """
    digest = hashlib.sha1()
    for root in root_dirs:
        root = Path(root)
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if "__pycache__" in path.parts:
                continue
            digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()[:10]
