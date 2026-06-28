from __future__ import annotations

import logging
import unittest
from types import SimpleNamespace
from typing import Any

from kuaiqi.config import ConfigError, parse_config
from kuaiqi.models import InstrumentMeta, Universe
from kuaiqi.data_sources.tqsdk_source import TqSdkDataSource, _row_to_meta
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

    def test_tqsdk_row_to_meta_reads_liquidity_metrics(self) -> None:
        meta = _row_to_meta(
            {
                "instrument_id": "au2608C600",
                "exchange_id": "SHFE",
                "ins_class": "OPTION",
                "volume": 12,
                "open_interest": 34,
            },
            "SHFE.au2608C600",
        )

        self.assertEqual(meta.volume, 12.0)
        self.assertEqual(meta.open_interest, 34.0)

    def test_tqsdk_query_metas_uses_batches(self) -> None:
        api = _FakeSymbolInfoApi()
        source = TqSdkDataSource(
            config=SimpleNamespace(tqsdk=SimpleNamespace(symbol_info_batch_size=2)),
            logger=logging.getLogger("tests.universe.batch_metas"),
        )

        metas = source._query_metas(api, ("A.one", "A.two", "A.three", "A.four", "A.five"))

        self.assertEqual(set(metas), {"A.one", "A.two", "A.three", "A.four", "A.five"})
        self.assertEqual(api.calls, (("A.one", "A.two"), ("A.three", "A.four"), ("A.five",)))

    def test_config_parses_universe_liquidity_filters(self) -> None:
        config = parse_config(
            {
                "runtime": {},
                "universe": {"min_volume": 1, "min_open_interest": 2},
                "strategies": [{"type": "cp_combo", "threshold": 0.01}],
            }
        )

        self.assertEqual(config.universe.min_volume, 1.0)
        self.assertEqual(config.universe.min_open_interest, 2.0)
        self.assertEqual(config.logging.cycle_summary_interval_seconds, 60)

        with self.assertRaises(ConfigError):
            parse_config(
                {
                    "runtime": {},
                    "universe": {"min_volume": -1},
                    "strategies": [{"type": "cp_combo", "threshold": 0.01}],
                }
            )
        with self.assertRaises(ConfigError):
            parse_config(
                {
                    "runtime": {},
                    "logging": {"cycle_summary_interval_seconds": -1},
                    "strategies": [{"type": "cp_combo", "threshold": 0.01}],
                }
            )

    def test_live_universe_filters_liquidity_from_metadata(self) -> None:
        api = _FakeDiscoveryApi(_liquidity_rows(include_metrics=True))
        source = _FakeDiscoveryDataSource(api, min_volume=1, min_open_interest=1)

        universe = source.discover_universe()

        self.assertEqual(
            {option.symbol for option in universe.options},
            {"SHFE.au2608C600", "SHFE.au2608P620"},
        )
        self.assertFalse(api.quote_list_calls)
        self.assertFalse(api.closed)
        self.assertIs(source._live_api, api)
        source.close()

    def test_live_universe_filters_liquidity_with_quote_probe(self) -> None:
        discovery_api = _FakeDiscoveryApi(_liquidity_rows(include_metrics=False))
        probe_api = _FakeDiscoveryApi(
            _liquidity_rows(include_metrics=False),
            events=(
                _FakeQuoteEvent(
                    {
                        "SHFE.au2608": {"datetime": "t1", "volume": 10, "open_interest": 5},
                        "SHFE.au2608C600": {"datetime": "t1", "volume": 1, "open_interest": 3},
                        "SHFE.au2608P600": {"datetime": "t1", "volume": 0, "open_interest": 3},
                        "SHFE.au2608C620": {"datetime": "t1", "volume": 2, "open_interest": 0},
                        "SHFE.au2608P620": {"datetime": "t1", "volume": 2, "open_interest": 3},
                    }
                ),
            ),
        )
        source = _FakeDiscoveryDataSource(
            discovery_api,
            min_volume=1,
            min_open_interest=1,
            probe_apis=(probe_api,),
        )

        universe = source.discover_universe()

        self.assertEqual(
            {option.symbol for option in universe.options},
            {"SHFE.au2608C600", "SHFE.au2608P620"},
        )
        self.assertEqual(discovery_api.quote_list_calls, ())
        self.assertEqual(
            probe_api.quote_list_calls,
            (("SHFE.au2608", "SHFE.au2608C600", "SHFE.au2608C620", "SHFE.au2608P600", "SHFE.au2608P620"),),
        )
        self.assertTrue(discovery_api.closed)
        self.assertTrue(probe_api.closed)
        self.assertIsNone(getattr(source, "_live_api", None))

    def test_liquidity_probe_uses_isolated_apis_per_batch(self) -> None:
        discovery_api = _FakeDiscoveryApi(_liquidity_rows(include_metrics=False))
        probe_apis = tuple(
            _FakeDiscoveryApi(
                _liquidity_rows(include_metrics=False),
                events=(
                    _FakeQuoteEvent(
                        {
                            symbol: {"datetime": "t1", "volume": 10, "open_interest": 10}
                            for symbol in batch
                        }
                    ),
                ),
            )
            for batch in (
                ("SHFE.au2608", "SHFE.au2608C600"),
                ("SHFE.au2608C620", "SHFE.au2608P600"),
                ("SHFE.au2608P620",),
            )
        )
        source = _FakeDiscoveryDataSource(
            discovery_api,
            min_volume=1,
            min_open_interest=1,
            probe_apis=probe_apis,
            quote_subscription_batch_size=2,
        )

        universe = source.discover_universe()

        self.assertEqual(len(universe.options), 4)
        self.assertEqual(discovery_api.quote_list_calls, ())
        self.assertEqual(
            [api.quote_list_calls for api in probe_apis],
            [
                (("SHFE.au2608", "SHFE.au2608C600"),),
                (("SHFE.au2608C620", "SHFE.au2608P600"),),
                (("SHFE.au2608P620",),),
            ],
        )
        self.assertTrue(all(api.closed for api in probe_apis))


class _FakeSymbolInfoApi:
    def __init__(self) -> None:
        self.calls: tuple[tuple[str, ...], ...] = ()

    def query_symbol_info(self, symbols: list[str]) -> "_FakeSymbolInfoFrame":
        self.calls = (*self.calls, tuple(symbols))
        return _FakeSymbolInfoFrame(symbols)


class _FakeSymbolInfoFrame:
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols

    def iterrows(self):
        for symbol in self.symbols:
            yield symbol, {"instrument_id": symbol, "ins_class": "OPTION"}


class _FakeDiscoveryDataSource(TqSdkDataSource):
    def __init__(
        self,
        api: "_FakeDiscoveryApi",
        min_volume: float,
        min_open_interest: float,
        probe_apis: tuple["_FakeDiscoveryApi", ...] = (),
        quote_subscription_batch_size: int = 10,
    ) -> None:
        self.api = api
        self.probe_apis = list(probe_apis)
        self.config = SimpleNamespace(
            runtime=SimpleNamespace(mode="live"),
            universe=SimpleNamespace(
                mode="all",
                underlyings=(),
                symbols=(),
                exchange_ids=("SHFE",),
                min_volume=min_volume,
                min_open_interest=min_open_interest,
            ),
            tqsdk=SimpleNamespace(
                symbol_info_batch_size=10,
                quote_subscription_batch_size=quote_subscription_batch_size,
            ),
        )
        self.logger = logging.getLogger("tests.universe.discovery")
        self.logger.handlers = [logging.NullHandler()]
        self.logger.propagate = False
        self.create_api_calls = 0

    def _create_api(self) -> "_FakeDiscoveryApi":
        self.create_api_calls += 1
        if self.create_api_calls > 1 and self.probe_apis:
            return self.probe_apis.pop(0)
        return self.api


class _FakeDiscoveryApi:
    def __init__(
        self,
        rows: dict[str, dict[str, Any]],
        events: tuple["_FakeQuoteEvent", ...] = (),
    ) -> None:
        self.rows = rows
        self.events = list(events)
        self.quotes: dict[str, _FakeQuote] = {}
        self.quote_list_calls: tuple[tuple[str, ...], ...] = ()
        self.closed = False

    def query_quotes(self, **kwargs: Any) -> list[str]:
        exchange_id = kwargs.get("exchange_id")
        return [
            symbol
            for symbol, row in self.rows.items()
            if row.get("ins_class") == "OPTION"
            and (exchange_id is None or row.get("exchange_id") == exchange_id)
        ]

    def query_symbol_info(self, symbols: list[str]) -> "_FakeRowsFrame":
        return _FakeRowsFrame(symbols, self.rows)

    def get_quote_list(self, symbols: list[str]) -> list["_FakeQuote"]:
        self.quote_list_calls = (*self.quote_list_calls, tuple(symbols))
        for symbol in symbols:
            self.quotes.setdefault(symbol, _FakeQuote(symbol))
        return [self.quotes[symbol] for symbol in symbols]

    def wait_update(self, deadline: float | None = None) -> bool:
        if not self.events:
            return False
        event = self.events.pop(0)
        for symbol, fields in event.updates.items():
            quote = self.quotes.setdefault(symbol, _FakeQuote(symbol))
            for key, value in fields.items():
                setattr(quote, key, value)
        return True

    def close(self) -> None:
        self.closed = True


class _FakeRowsFrame:
    def __init__(self, symbols: list[str], rows: dict[str, dict[str, Any]]) -> None:
        self.symbols = symbols
        self.rows = rows

    def iterrows(self):
        for symbol in self.symbols:
            yield symbol, dict(self.rows[symbol])


class _FakeQuote:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.datetime = ""
        self.volume = 0
        self.open_interest = 0


class _FakeQuoteEvent:
    def __init__(self, updates: dict[str, dict[str, Any]]) -> None:
        self.updates = updates


def _liquidity_rows(include_metrics: bool) -> dict[str, dict[str, Any]]:
    rows = {
        "SHFE.au2608": {
            "instrument_id": "au2608",
            "exchange_id": "SHFE",
            "ins_class": "FUTURE",
        },
        "SHFE.au2608C600": {
            "instrument_id": "au2608C600",
            "exchange_id": "SHFE",
            "ins_class": "OPTION",
            "underlying_symbol": "au2608",
            "strike_price": 600.0,
            "option_class": "CALL",
            "exercise_year": 2026,
            "exercise_month": 8,
        },
        "SHFE.au2608P600": {
            "instrument_id": "au2608P600",
            "exchange_id": "SHFE",
            "ins_class": "OPTION",
            "underlying_symbol": "au2608",
            "strike_price": 600.0,
            "option_class": "PUT",
            "exercise_year": 2026,
            "exercise_month": 8,
        },
        "SHFE.au2608C620": {
            "instrument_id": "au2608C620",
            "exchange_id": "SHFE",
            "ins_class": "OPTION",
            "underlying_symbol": "au2608",
            "strike_price": 620.0,
            "option_class": "CALL",
            "exercise_year": 2026,
            "exercise_month": 8,
        },
        "SHFE.au2608P620": {
            "instrument_id": "au2608P620",
            "exchange_id": "SHFE",
            "ins_class": "OPTION",
            "underlying_symbol": "au2608",
            "strike_price": 620.0,
            "option_class": "PUT",
            "exercise_year": 2026,
            "exercise_month": 8,
        },
    }
    if include_metrics:
        rows["SHFE.au2608"].update({"volume": 10, "open_interest": 5})
        rows["SHFE.au2608C600"].update({"volume": 1, "open_interest": 3})
        rows["SHFE.au2608P600"].update({"volume": 0, "open_interest": 3})
        rows["SHFE.au2608C620"].update({"volume": 2, "open_interest": 0})
        rows["SHFE.au2608P620"].update({"volume": 2, "open_interest": 3})
    return rows


if __name__ == "__main__":
    unittest.main()
