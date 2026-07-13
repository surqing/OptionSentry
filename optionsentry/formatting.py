from __future__ import annotations

import math


def format_key_number(value: float) -> str:
    return f"{value:g}"


def format_key_bound(value: float) -> str:
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return format_key_number(value)


def format_key_range(min_value: float, max_value: float) -> str:
    return f"({format_key_bound(min_value)}, {format_key_bound(max_value)})"


def format_display_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def format_display_range(min_value: float, max_value: float) -> str:
    return f"({_format_display_bound(min_value)}, {_format_display_bound(max_value)})"


def _format_display_bound(value: float) -> str:
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return format_display_number(value)
