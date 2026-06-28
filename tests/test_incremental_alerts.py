from __future__ import annotations

import logging
import math
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from kuaiqi.alerts import AlertEngine
from kuaiqi.config import ConfigError
from kuaiqi.data_sources.tqsdk_source import TqSdkDataSource
from kuaiqi.models import InstrumentMeta, MarketSnapshot, Universe
from kuaiqi.strategies import AbsSpreadStrategy, CPComboStrategy, Strategy
from tests.helpers import sample_universe


class IncrementalStrategyTests(unittest.TestCase):
    def test_incremental_events_match_full_scan_events(self) -> None:
        universe = _one_strike_universe()
        snapshots = (
            MarketSnapshot(
                timestamp="t1",
                prices={
                    "SHFE.au2608": 600.0,
                    "SHFE.au2608C600": 5.0,
                    "SHFE.au2608P600": 5.0,
                },
                changed_symbols={"SHFE.au2608", "SHFE.au2608C600", "SHFE.au2608P600"},
                universe=universe,
            ),
            MarketSnapshot(
                timestamp="t2",
                prices={
                    "SHFE.au2608": 590.0,
                    "SHFE.au2608C600": 12.0,
                    "SHFE.au2608P600": 1.0,
                },
                changed_symbols={"SHFE.au2608", "SHFE.au2608C600", "SHFE.au2608P600"},
                universe=universe,
            ),
            MarketSnapshot(
                timestamp="t3",
                prices={
                    "SHFE.au2608": 600.0,
                    "SHFE.au2608C600": 5.0,
                    "SHFE.au2608P600": 5.0,
                },
                changed_symbols={"SHFE.au2608", "SHFE.au2608C600", "SHFE.au2608P600"},
                universe=universe,
            ),
            MarketSnapshot(
                timestamp="t4",
                prices={
                    "SHFE.au2608": 590.0,
                    "SHFE.au2608C600": 12.0,
                    "SHFE.au2608P600": 1.0,
                },
                changed_symbols={"SHFE.au2608", "SHFE.au2608C600", "SHFE.au2608P600"},
                universe=universe,
            ),
        )
        strategies: tuple[Strategy, ...] = (CPComboStrategy(threshold=0.01),)

        self.assertEqual(
            _full_scan_events(strategies, snapshots),
            _incremental_events(strategies, universe, snapshots),
        )

    def test_cp_combo_index_limits_changed_option_work(self) -> None:
        universe = sample_universe()
        prices = {
            "SHFE.au2608": 600.0,
            "SHFE.au2608C600": 5.0,
            "SHFE.au2608P600": 5.0,
            "SHFE.au2608C620": 4.0,
            "SHFE.au2608P620": 24.0,
        }
        snap = MarketSnapshot("t1", prices, set(prices), universe)
        compiled = CPComboStrategy(threshold=0.01).compile(universe)

        option_evaluations = compiled.evaluate(snap, {"SHFE.au2608C600"})
        underlying_evaluations = compiled.evaluate(snap, {"SHFE.au2608"})

        self.assertEqual(len(option_evaluations), 1)
        self.assertIn("K=600", option_evaluations[0].key)
        self.assertEqual(len(underlying_evaluations), 2)

    def test_abs_spread_index_limits_changed_option_work(self) -> None:
        universe = sample_universe()
        prices = {
            "SHFE.au2608C600": 11.0,
            "SHFE.au2608C620": 10.0,
            "SHFE.au2608P600": 3.0,
            "SHFE.au2608P620": 2.0,
        }
        snap = MarketSnapshot("t1", prices, set(prices), universe)
        compiled = AbsSpreadStrategy(threshold=0.1).compile(universe)

        option_evaluations = compiled.evaluate(snap, {"SHFE.au2608C600"})
        underlying_evaluations = compiled.evaluate(snap, {"SHFE.au2608"})

        self.assertEqual(len(option_evaluations), 1)
        self.assertEqual(option_evaluations[0].symbols, ("SHFE.au2608C600", "SHFE.au2608C620"))
        self.assertEqual(underlying_evaluations, [])

    def test_incremental_work_scales_with_changed_symbol_not_total_conditions(self) -> None:
        for strikes in (100, 200, 400):
            universe = _large_option_universe(strikes)
            prices = {symbol: 10.0 for symbol in universe.price_symbols()}
            prices["SHFE.au2608"] = 1000.0
            changed_symbol = "SHFE.au2608C800"
            snap = MarketSnapshot("bench", prices, {changed_symbol}, universe)
            compiled_strategies = (
                CPComboStrategy(threshold=0.01).compile(universe),
                AbsSpreadStrategy(threshold=0.1).compile(universe),
            )

            total_conditions = sum(strategy.condition_count for strategy in compiled_strategies)
            evaluated_conditions = sum(
                len(strategy.evaluate(snap, {changed_symbol}))
                for strategy in compiled_strategies
            )

            self.assertLess(evaluated_conditions * 20, total_conditions)


class LivePriceCacheTests(unittest.TestCase):
    def test_live_discovery_api_is_reused_for_quote_stream(self) -> None:
        api = _FakeApi(
            events=(
                _FakeEvent(
                    updates={
                        "SHFE.au2608": {"datetime": "t1", "last_price": 600.0},
                        "SHFE.au2608C600": {"datetime": "t1", "last_price": 5.0},
                        "SHFE.au2608P600": {"datetime": "t1", "last_price": 5.0},
                    },
                    changed_symbols=set(),
                ),
            )
        )
        data_source = _FakeLiveDataSource(api)
        data_source.config = SimpleNamespace(
            runtime=SimpleNamespace(mode="live"),
            universe=SimpleNamespace(
                mode="underlyings",
                underlyings=("SHFE.au2608",),
                symbols=(),
                exchange_ids=(),
            ),
            tqsdk=SimpleNamespace(
                symbol_info_batch_size=10,
                quote_subscription_batch_size=10,
            ),
        )

        universe = data_source.discover_universe()
        self.assertEqual(len(universe.options), 2)
        self.assertFalse(api.closed)
        self.assertIs(data_source._live_api, api)

        stream = data_source._stream_live(universe)
        try:
            first = next(stream)
        finally:
            stream.close()

        self.assertEqual(data_source.create_api_calls, 1)
        self.assertEqual(api.close_count, 1)
        self.assertTrue(api.closed)
        self.assertEqual(
            api.quote_list_calls,
            (("SHFE.au2608", "SHFE.au2608C600", "SHFE.au2608P600"),),
        )
        self.assertEqual(first.prices["SHFE.au2608"], 600.0)

    def test_live_stream_yields_full_cached_prices_with_only_changed_symbols(self) -> None:
        universe = _one_strike_universe()
        api = _FakeApi(
            events=(
                _FakeEvent(
                    updates={
                        "SHFE.au2608": {"datetime": "t1", "last_price": 600.0},
                        "SHFE.au2608C600": {"datetime": "t1", "last_price": 5.0},
                        "SHFE.au2608P600": {"datetime": "t1", "last_price": 5.0},
                    },
                    changed_symbols=set(),
                ),
                _FakeEvent(updates={}, changed_symbols=set()),
                _FakeEvent(
                    updates={"SHFE.au2608C600": {"datetime": "t2", "last_price": 6.0}},
                    changed_symbols={"SHFE.au2608C600"},
                ),
            )
        )
        data_source = _FakeLiveDataSource(api)
        stream = data_source._stream_live(universe)
        try:
            first = next(stream)
            second = next(stream)
        finally:
            stream.close()

        self.assertEqual(first.changed_symbols, set(first.prices))
        self.assertEqual(second.changed_symbols, {"SHFE.au2608C600"})
        self.assertEqual(second.prices["SHFE.au2608"], 600.0)
        self.assertEqual(second.prices["SHFE.au2608P600"], 5.0)
        self.assertEqual(second.prices["SHFE.au2608C600"], 6.0)
        self.assertTrue(api.closed)

    def test_live_quote_subscription_uses_batches(self) -> None:
        api = _FakeApi(events=())
        data_source = _FakeLiveDataSource(api, quote_subscription_batch_size=2)

        quotes = data_source._subscribe_live_quotes(api, ["A", "B", "C", "D", "E"])

        self.assertEqual(set(quotes), {"A", "B", "C", "D", "E"})
        self.assertEqual(api.quote_list_calls, (("A", "B"), ("C", "D"), ("E",)))

    def test_live_quote_subscription_allows_threshold_symbol_count(self) -> None:
        api = _FakeApi(events=())
        data_source = _FakeLiveDataSource(api, quote_subscription_batch_size=500)
        symbols = [f"S{index}" for index in range(1300)]

        quotes = data_source._subscribe_live_quotes(api, symbols)

        self.assertEqual(set(quotes), set(symbols))

    def test_live_quote_subscription_rejects_count_above_threshold(self) -> None:
        api = _FakeApi(events=())
        data_source = _FakeLiveDataSource(api, quote_subscription_batch_size=500)
        symbols = [f"S{index}" for index in range(1301)]

        with self.assertRaisesRegex(ConfigError, "预处理后需要订阅的合约数量过多"):
            data_source._subscribe_live_quotes(api, symbols)

        self.assertEqual(api.quote_list_calls, ())

    def test_live_stream_rejects_preprocessed_universe_above_threshold(self) -> None:
        api = _FakeApi(events=())
        data_source = _FakeLiveDataSource(api, quote_subscription_batch_size=500)

        with self.assertRaisesRegex(ConfigError, "预处理后需要订阅的合约数量过多"):
            next(data_source._stream_live(_large_option_universe(650)))

        self.assertEqual(data_source.create_api_calls, 0)
        self.assertEqual(api.quote_list_calls, ())


def _full_scan_events(
    strategies: tuple[Strategy, ...],
    snapshots: tuple[MarketSnapshot, ...],
) -> list[tuple[str, str, str]]:
    engine = AlertEngine()
    events: list[tuple[str, str, str]] = []
    for snap in snapshots:
        evaluations = []
        for strategy in strategies:
            evaluations.extend(strategy.evaluate(snap, snap.universe))
        events.extend(
            (event.timestamp, event.evaluation.key, event.evaluation.message)
            for event in engine.process(evaluations, snap.timestamp)
        )
    return events


def _incremental_events(
    strategies: tuple[Strategy, ...],
    universe: Universe,
    snapshots: tuple[MarketSnapshot, ...],
) -> list[tuple[str, str, str]]:
    engine = AlertEngine()
    compiled_strategies = tuple(strategy.compile(universe) for strategy in strategies)
    events: list[tuple[str, str, str]] = []
    initialized = False
    for snap in snapshots:
        changed_symbols = None if not initialized else snap.changed_symbols
        evaluations = []
        for strategy in compiled_strategies:
            evaluations.extend(strategy.evaluate(snap, changed_symbols))
        events.extend(
            (event.timestamp, event.evaluation.key, event.evaluation.message)
            for event in engine.process(evaluations, snap.timestamp)
        )
        initialized = True
    return events


def _one_strike_universe() -> Universe:
    return Universe(
        instruments={
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
        }
    )


def _large_option_universe(strikes: int) -> Universe:
    instruments = {"SHFE.au2608": InstrumentMeta("SHFE.au2608", "FUTURE")}
    for index in range(strikes):
        strike = 800 + index * 8
        instruments[f"SHFE.au2608C{strike}"] = InstrumentMeta(
            f"SHFE.au2608C{strike}",
            "OPTION",
            underlying_symbol="SHFE.au2608",
            strike_price=float(strike),
            option_class="CALL",
            exercise_year=2026,
            exercise_month=8,
        )
        instruments[f"SHFE.au2608P{strike}"] = InstrumentMeta(
            f"SHFE.au2608P{strike}",
            "OPTION",
            underlying_symbol="SHFE.au2608",
            strike_price=float(strike),
            option_class="PUT",
            exercise_year=2026,
            exercise_month=8,
        )
    return Universe(instruments=instruments)


@dataclass
class _FakeEvent:
    updates: dict[str, dict[str, Any]]
    changed_symbols: set[str]


@dataclass
class _FakeQuote:
    symbol: str
    datetime: str = ""
    last_price: float = math.nan


class _FakeApi:
    def __init__(self, events: tuple[_FakeEvent, ...]) -> None:
        self.events = list(events)
        self.quotes: dict[str, _FakeQuote] = {}
        self.changed_symbols: set[str] = set()
        self.closed = False
        self.close_count = 0
        self.quote_list_calls: tuple[tuple[str, ...], ...] = ()

    def query_options(self, underlying: str, expired: bool = False) -> list[str]:
        return [f"{underlying}C600", f"{underlying}P600"]

    def query_symbol_info(self, symbols: list[str]) -> "_FakeSymbolInfoFrame":
        return _FakeSymbolInfoFrame(symbols)

    def get_quote_list(self, symbols: list[str]) -> list[_FakeQuote]:
        self.quote_list_calls = (*self.quote_list_calls, tuple(symbols))
        for symbol in symbols:
            self.quotes.setdefault(symbol, _FakeQuote(symbol=symbol))
        return [self.quotes[symbol] for symbol in symbols]

    def wait_update(self, deadline: float | None = None) -> bool:
        if not self.events:
            return False
        event = self.events.pop(0)
        self.changed_symbols = set(event.changed_symbols)
        for symbol, fields in event.updates.items():
            quote = self.quotes.setdefault(symbol, _FakeQuote(symbol=symbol))
            for key, value in fields.items():
                setattr(quote, key, value)
        return True

    def is_changing(self, quote: _FakeQuote, key: str) -> bool:
        return key == "last_price" and quote.symbol in self.changed_symbols

    def close(self) -> None:
        self.close_count += 1
        self.closed = True


class _FakeSymbolInfoFrame:
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols

    def iterrows(self):
        for symbol in self.symbols:
            if symbol == "SHFE.au2608":
                yield symbol, {
                    "instrument_id": "au2608",
                    "exchange_id": "SHFE",
                    "ins_class": "FUTURE",
                }
                continue
            option_class = "CALL" if symbol.endswith("C600") else "PUT"
            yield symbol, {
                "instrument_id": symbol.rsplit(".", 1)[-1],
                "exchange_id": "SHFE",
                "ins_class": "OPTION",
                "underlying_symbol": "au2608",
                "strike_price": 600.0,
                "option_class": option_class,
                "exercise_year": 2026,
                "exercise_month": 8,
            }


class _FakeLiveDataSource(TqSdkDataSource):
    def __init__(self, api: _FakeApi, quote_subscription_batch_size: int = 500) -> None:
        self.api = api
        self.create_api_calls = 0
        self.config = SimpleNamespace(
            tqsdk=SimpleNamespace(quote_subscription_batch_size=quote_subscription_batch_size)
        )
        self.logger = logging.getLogger("tests.live_price_cache")
        self.logger.handlers = [logging.NullHandler()]
        self.logger.propagate = False

    def _create_api(self) -> _FakeApi:
        self.create_api_calls += 1
        return self.api


if __name__ == "__main__":
    unittest.main()
