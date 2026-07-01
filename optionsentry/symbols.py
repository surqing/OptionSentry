from __future__ import annotations

from typing import Iterable


LOWER_PRODUCT_EXCHANGES = {"SHFE", "DCE", "INE", "GFEX"}


def normalize_symbol(symbol: object) -> str:
    return str(symbol).strip().upper()


def normalize_symbols(symbols: Iterable[object]) -> tuple[str, ...]:
    return tuple(normalize_symbol(symbol) for symbol in symbols if str(symbol).strip())


def tqsdk_api_symbol(symbol: object) -> str:
    normalized = normalize_symbol(symbol)
    if "." not in normalized:
        return normalized
    exchange, instrument = normalized.split(".", 1)
    if exchange not in LOWER_PRODUCT_EXCHANGES:
        return f"{exchange}.{instrument}"
    return f"{exchange}.{_lower_leading_letters(instrument)}"


def _lower_leading_letters(value: str) -> str:
    index = 0
    while index < len(value) and value[index].isalpha():
        index += 1
    return value[:index].lower() + value[index:]
