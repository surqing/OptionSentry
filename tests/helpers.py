from __future__ import annotations

from optionsentry.models import InstrumentMeta, MarketSnapshot, Universe


def sample_universe() -> Universe:
    instruments = {
        "SHFE.au2608": InstrumentMeta("SHFE.au2608", "FUTURE"),
        "SHFE.au2608C600": InstrumentMeta(
            "SHFE.au2608C600",
            "OPTION",
            underlying_symbol="SHFE.au2608",
            strike_price=600.0,
            option_class="CALL",
            exercise_year=2026,
            exercise_month=8,
        ),
        "SHFE.au2608P600": InstrumentMeta(
            "SHFE.au2608P600",
            "OPTION",
            underlying_symbol="SHFE.au2608",
            strike_price=600.0,
            option_class="PUT",
            exercise_year=2026,
            exercise_month=8,
        ),
        "SHFE.au2608C620": InstrumentMeta(
            "SHFE.au2608C620",
            "OPTION",
            underlying_symbol="SHFE.au2608",
            strike_price=620.0,
            option_class="CALL",
            exercise_year=2026,
            exercise_month=8,
        ),
        "SHFE.au2608P620": InstrumentMeta(
            "SHFE.au2608P620",
            "OPTION",
            underlying_symbol="SHFE.au2608",
            strike_price=620.0,
            option_class="PUT",
            exercise_year=2026,
            exercise_month=8,
        ),
    }
    return Universe(instruments=instruments)


def snapshot(universe: Universe, prices: dict[str, float], timestamp: str = "2026-01-02 09:31:00") -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=timestamp,
        prices=prices,
        changed_symbols=set(prices),
        universe=universe,
    )
