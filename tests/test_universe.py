from __future__ import annotations

import unittest

from kuaiqi.models import InstrumentMeta, Universe
from kuaiqi.data_sources.tqsdk_source import _row_to_meta
from tests.helpers import sample_universe


class UniverseTests(unittest.TestCase):
    def test_groups_options_by_underlying_and_expiry(self) -> None:
        universe = sample_universe()

        groups = universe.option_groups()

        self.assertEqual(len(groups), 1)
        group_options = next(iter(groups.values()))
        self.assertEqual(len(group_options), 4)

    def test_price_symbols_include_options_and_underlying(self) -> None:
        universe = sample_universe()

        symbols = universe.price_symbols()

        self.assertIn("SHFE.au2608", symbols)
        self.assertIn("SHFE.au2608C600", symbols)

    def test_non_futures_underlying_can_be_filtered_by_builder_logic(self) -> None:
        universe = Universe(
            instruments={
                "SSE.510050": InstrumentMeta("SSE.510050", "FUND"),
                "SSE.510050C3": InstrumentMeta(
                    "SSE.510050C3",
                    "OPTION",
                    underlying_symbol="SSE.510050",
                    strike_price=3.0,
                    option_class="CALL",
                ),
            }
        )

        self.assertEqual([meta.symbol for meta in universe.futures], [])

    def test_tqsdk_row_to_meta_keeps_full_symbol_when_instrument_id_is_short(self) -> None:
        meta = _row_to_meta(
            {
                "instrument_id": "au2608C600",
                "exchange_id": "SHFE",
                "ins_class": "OPTION",
                "underlying_symbol": "au2608",
                "strike_price": 600.0,
                "option_class": "CALL",
            },
            "SHFE.au2608C600",
        )

        self.assertEqual(meta.symbol, "SHFE.au2608C600")
        self.assertEqual(meta.underlying_symbol, "SHFE.au2608")


if __name__ == "__main__":
    unittest.main()
