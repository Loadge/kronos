"""The currencies Kronos knows, and the one function that turns any of them into euros.

EUR is the internal pivot: every stored rate is "units of the currency per 1 EUR" (the ECB's
convention), so `amount / rate` is the euros everywhere. The catalogue is static: EUR, every
currency the ECB's daily document publishes (the list was copied from it on 2026-11-07) and a
few coins whose price CoinGecko gives. A base currency other than EUR is not supported.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.services import crypto, fx
from app.services.tax import round_half_up

FIAT_DECIMALS = 2
CRYPTO_DECIMALS = 8


@dataclass(frozen=True)
class CurrencyInfo:
    code: str
    name: str
    kind: str  # "fiat" | "crypto"
    rate_source: str  # "none" (EUR itself) | "ecb" | "coingecko"
    decimals: int
    coingecko_id: str | None = None

    def out(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "kind": self.kind,
            "rate_source": self.rate_source,
            "decimals": self.decimals,
        }


def _fiat(code: str, name: str) -> CurrencyInfo:
    return CurrencyInfo(code, name, "fiat", "ecb", FIAT_DECIMALS)


def _coin(code: str, name: str) -> CurrencyInfo:
    return CurrencyInfo(code, name, "crypto", "coingecko", CRYPTO_DECIMALS, crypto.COIN_IDS[code])


CATALOGUE: tuple[CurrencyInfo, ...] = (
    CurrencyInfo("EUR", "Euro", "fiat", "none", FIAT_DECIMALS),
    _fiat("USD", "US dollar"),
    _fiat("JPY", "Japanese yen"),
    _fiat("CZK", "Czech koruna"),
    _fiat("DKK", "Danish krone"),
    _fiat("GBP", "Pound sterling"),
    _fiat("HUF", "Hungarian forint"),
    _fiat("PLN", "Polish zloty"),
    _fiat("RON", "Romanian leu"),
    _fiat("SEK", "Swedish krona"),
    _fiat("CHF", "Swiss franc"),
    _fiat("ISK", "Icelandic krona"),
    _fiat("NOK", "Norwegian krone"),
    _fiat("TRY", "Turkish lira"),
    _fiat("AUD", "Australian dollar"),
    _fiat("BRL", "Brazilian real"),
    _fiat("CAD", "Canadian dollar"),
    _fiat("CNY", "Chinese yuan renminbi"),
    _fiat("HKD", "Hong Kong dollar"),
    _fiat("IDR", "Indonesian rupiah"),
    _fiat("ILS", "Israeli shekel"),
    _fiat("INR", "Indian rupee"),
    _fiat("KRW", "South Korean won"),
    _fiat("MXN", "Mexican peso"),
    _fiat("MYR", "Malaysian ringgit"),
    _fiat("NZD", "New Zealand dollar"),
    _fiat("PHP", "Philippine peso"),
    _fiat("SGD", "Singapore dollar"),
    _fiat("THB", "Thai baht"),
    _fiat("ZAR", "South African rand"),
    _coin("BTC", "Bitcoin"),
    _coin("ETH", "Ether"),
    _coin("USDC", "USD Coin"),
    _coin("USDT", "Tether"),
    _coin("SOL", "Solana"),
)

BY_CODE: dict[str, CurrencyInfo] = {c.code: c for c in CATALOGUE}
CODES: tuple[str, ...] = tuple(BY_CODE)


def is_known(code: str) -> bool:
    return code in BY_CODE


def decimals(code: str) -> int:
    """Decimals an amount of `code` keeps: 2 for fiat, 8 for a coin (unknown codes: 2)."""
    info = BY_CODE.get(code)
    return info.decimals if info else FIAT_DECIMALS


def quantize(amount: float, code: str) -> float:
    """`amount` rounded (a half going away from zero) to the decimals of its currency."""
    return round_half_up(amount, decimals(code))


def units(amount: float, code: str) -> int:
    """`amount` as a whole number of the currency's smallest unit (cents for euros)."""
    return round(quantize(amount, code) * 10 ** decimals(code))


def _unavailable(error: str) -> dict:
    return {
        "available": False,
        "per_eur": None,
        "source": None,
        "date": None,
        "stale": False,
        "error": error,
    }


def ecb_per_eur(currency: str, on: date) -> float | None:
    """The ECB's rate of a fiat currency on a date (units per EUR), or None when it has none.

    USD goes through `fx.for_date(on)` exactly as it always did.
    """
    if currency == "USD":
        return fx.value_of(fx.for_date(on))
    return fx.value_of(fx.for_date(on, currency=currency))


def rate_for(currency: str, on: date) -> dict:
    """The rate of `currency` on `on`, units per EUR, from whichever source publishes it.

    EUR is 1.0 (no source). A fiat currency is the ECB's, a coin CoinGecko's. Never raises:
    {"available", "per_eur", "source", "date", "stale", "error"}, `available` False with the
    reason when there is no rate.
    """
    info = BY_CODE.get(currency)
    if info is None:
        return _unavailable(f"unknown currency {currency}")
    if info.rate_source == "none":
        return {
            "available": True,
            "per_eur": 1.0,
            "source": None,
            "date": on.isoformat(),
            "stale": False,
            "error": None,
        }
    if info.rate_source == "ecb":
        answer = fx.for_date(on) if currency == "USD" else fx.for_date(on, currency=currency)
        rate = fx.value_of(answer)
        if rate is None:
            return _unavailable(answer.get("error") or "no ECB rate")
        return {
            "available": True,
            "per_eur": rate,
            "source": fx.SOURCE,
            "date": answer.get("date"),
            "stale": bool(answer.get("stale")),
            "error": answer.get("error"),
        }
    answer = crypto.price(currency, on)
    if not answer.get("available"):
        return _unavailable(answer.get("error") or "no CoinGecko price")
    return {
        "available": True,
        "per_eur": answer["per_eur"],
        "source": crypto.SOURCE,
        "date": answer.get("date"),
        "stale": bool(answer.get("stale")),
        "error": answer.get("error"),
    }


def cross_rate(frm: str, to: str, on: date) -> float | None:
    """Units of `to` for one unit of `frm` on `on` (EUR is the pivot), or None when either
    side has no rate. The same currency is exactly 1.0 and asks nobody. Eight significant
    digits, so a coin's tiny rate keeps its precision."""
    if frm == to:
        return 1.0
    a, b = rate_for(frm, on), rate_for(to, on)
    if not a["available"] or not b["available"] or not a["per_eur"]:
        return None
    return float(f"{b['per_eur'] / a['per_eur']:.8g}")
