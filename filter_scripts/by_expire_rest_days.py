from __future__ import annotations


# Keep options whose remaining days to expiry are in this inclusive range.
# Edit these values to match the range you want to monitor.
MIN_EXPIRE_REST_DAYS = 10
MAX_EXPIRE_REST_DAYS = 60


def accept(option, ctx) -> bool:
    """Return True when this option should be included by the strategy."""
    return (
        option.expire_rest_days is not None
        and MIN_EXPIRE_REST_DAYS <= option.expire_rest_days <= MAX_EXPIRE_REST_DAYS
    )
