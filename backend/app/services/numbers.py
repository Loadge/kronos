"""How a number is written: the four formats Kronos offers, for the server-rendered pages.

The browser has its own copy of these rules (``fmtNum`` and ``parseNum`` in app.js). Both are
tested against the same table, ``tests/fixtures/number_cases.json``, so they cannot drift apart.

The format is a BCP 47 locale tag kept in the settings, one of the four in ``FORMATS``. Only the
separators differ between them: the digits come out of the same Python formatting as before, so
with the default (``en-US``) every text is what it always was.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_FORMAT = "en-US"

# tag -> (what it looks like, group mark, decimal mark)
FORMATS: dict[str, tuple[str, str, str]] = {
    "en-US": ("1,234.56", ",", "."),
    "es-ES": ("1.234,56", ".", ","),
    "fr-FR": ("1 234,56", " ", ","),
    "de-CH": ("1’234.56", "’", "."),
}

_current: ContextVar[str] = ContextVar("number_format", default=DEFAULT_FORMAT)


def valid(tag: str) -> bool:
    return tag in FORMATS


@contextmanager
def use_format(tag: str) -> Iterator[None]:
    """The format the ``fmt_*`` helpers of the printable timesheets use inside the block."""
    token = _current.set(tag if tag in FORMATS else DEFAULT_FORMAT)
    try:
        yield
    finally:
        _current.reset(token)


def activate(tag: str) -> None:
    """Set the format for the rest of this request. A request runs in a context copy of its own, so
    nothing outlives it."""
    _current.set(tag if tag in FORMATS else DEFAULT_FORMAT)


def current() -> str:
    return _current.get()


def localize(text: str, tag: str | None = None) -> str:
    """Rewrite the separators of an en-US number ("1,234.56") for `tag` (the current one)."""
    _, group, decimal = FORMATS[tag or current()]
    if (group, decimal) == (",", "."):
        return text
    return text.replace(",", "\x00").replace(".", decimal).replace("\x00", group)


def format_number(
    value: float, decimals: int = 2, *, grouping: bool = True, tag: str | None = None
) -> str:
    """`value` with `decimals` decimals: 1234.5 is "1,234.50" in en-US and "1.234,50" in es-ES."""
    return localize(f"{value:,.{decimals}f}" if grouping else f"{value:.{decimals}f}", tag)


_SPACES_AND_APOSTROPHES = re.compile(r"[\s'’]")
_PLAIN = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")


def parse_number(text: str, tag: str = DEFAULT_FORMAT) -> float | None:
    """What a person typed, read the way their format writes numbers; None when it is no number.

    Spaces and apostrophes are only ever group marks. With a comma and a dot present the last one
    is the decimal mark. A mark repeated is a group mark. A single mark that is the format's
    decimal mark is the decimal point. A single group mark is a group mark when exactly three
    digits follow ("55.000" is 55000 in es-ES; "1,234" is 1234 in en-US), and a dot in front of
    one or two digits stays a decimal point. A comma that is not the format's mark is read as a
    decimal comma when one or two digits follow ("12,5" is 12.5 in en-US), else as a group mark.
    """
    _, group, decimal = FORMATS.get(tag, FORMATS[DEFAULT_FORMAT])
    t = _SPACES_AND_APOSTROPHES.sub("", str(text)).replace("−", "-")
    if t == "":
        return None
    commas, dots = t.count(","), t.count(".")
    if commas and dots:
        mark = "," if t.rfind(",") > t.rfind(".") else "."
        other = "." if mark == "," else ","
        t = t.replace(other, "").replace(mark, ".")
    elif commas or dots:
        mark, count = (",", commas) if commas else (".", dots)
        before, _, after = t.rpartition(mark)
        if count > 1:
            t = t.replace(mark, "")
        elif mark == decimal:
            t = t.replace(mark, ".")
        elif mark == group:
            if len(after) == 3 and (mark == "," or re.fullmatch(r"[+-]?\d{1,3}", before)):
                t = before + after
            elif mark == "," and len(after) <= 2:
                t = before + "." + after
            elif mark == ",":
                t = before + after
            # a lone group dot that is not in group shape is a decimal point: "1.5", "28960.03"
        elif mark == ",":  # a comma in a format that writes the decimal as a dot
            t = before + ("." + after if len(after) <= 2 else after)
        # a dot in a format whose decimal mark is the comma: read as a decimal point
    if not _PLAIN.match(t):
        return None
    return float(t)
