from __future__ import annotations

from datetime import date


# Keep options whose expire_date is in this inclusive range.
# Edit these two values to match the expiry dates you want to monitor.
MIN_EXPIRE_DATE = date(2026, 8, 1)
MAX_EXPIRE_DATE = date(2026, 12, 31)


def accept(option, ctx) -> bool:
    """Return True when this option should be included by the strategy."""
    return (
        option.expire_date is not None
        and MIN_EXPIRE_DATE <= option.expire_date <= MAX_EXPIRE_DATE
    )
