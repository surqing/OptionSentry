from __future__ import annotations

import contextlib
import io
import logging
import math
import sys
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from optionsentry.alerts import AlertEngine
from optionsentry.config import ConfigError
from optionsentry.data_sources.tqsdk_source import TqSdkDataSource
from optionsentry.models import InstrumentMeta, MarketSnapshot, Universe
from optionsentry.strategies import AbsSpreadStrategy, CPComboStrategy, Strategy
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
        strategies: tuple[Strategy, ...] = (CPComboStrategy(min_value=0.01, max_value=float("inf")),)

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
        compiled = CPComboStrategy(min_value=0.01, max_value=float("inf")).compile(universe)

        option_evaluations = compiled.evaluate(snap, {"SHFE.au2608C600"})
        underlying_evaluations = compiled.evaluate(snap, {"SHFE.au2608"})

        self.assertEqual(len(option_evaluations), 1)
        self.assertIn("K=600", option_evaluations[0].key)
        self.assertEqual(len(underlying_evaluations), 2)

    def test_abs_spread_index_limits_changed_option_work(self) -> None:
        universe = sample_universe()
        prices = {
            "SHFE.au2608": 610.0,
            "SHFE.au2608C600": 11.0,
            "SHFE.au2608C620": 10.0,
            "SHFE.au2608P600": 3.0,
            "SHFE.au2608P620": 2.0,
        }
        snap = MarketSnapshot("t1", prices, set(prices), universe)
        compiled = AbsSpreadStrategy(min_value=float("-inf"), max_value=0.1).compile(universe)

        option_evaluations = compiled.evaluate(snap, {"SHFE.au2608C600"})
        underlying_evaluations = compiled.evaluate(snap, {"SHFE.au2608"})

        self.assertEqual(len(option_evaluations), 1)
        self.assertEqual(option_evaluations[0].symbols, ("SHFE.AU2608C600", "SHFE.AU2608C620"))
        self.assertEqual(len(underlying_evaluations), 2)
        self.assertTrue(all(item.metrics for item in underlying_evaluations))

    def test_incremental_work_scales_with_changed_symbol_not_total_conditions(self) -> None:
        for strikes in (100, 200, 400):
            universe = _large_option_universe(strikes)
            prices = {symbol: 10.0 for symbol in universe.price_symbols()}
            prices["SHFE.au2608"] = 1000.0
            changed_symbol = "SHFE.au2608C800"
            snap = MarketSnapshot("bench", prices, {changed_symbol}, universe)
            compiled_strategies = (
                CPComboStrategy(min_value=0.01, max_value=float("inf")).compile(universe),
                AbsSpreadStrategy(min_value=float("-inf"), max_value=0.1).compile(universe),
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
                mode="include",
                include=("SHFE.au2608",),
                exclude=(),
                exchanges=(),
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
            (
                ("SHFE.au2608",),
                ("SHFE.au2608", "SHFE.au2608C600", "SHFE.au2608P600"),
            ),
        )
        self.assertEqual(first.prices["SHFE.AU2608"], 600.0)

    def test_live_stream_debug_logs_final_subscription_symbols(self) -> None:
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
            )
        )
        data_source = _FakeLiveDataSource(api)

        with self.assertLogs("tests.live_price_cache", level="DEBUG") as logs:
            stream = data_source._stream_live(universe)
            try:
                next(stream)
            finally:
                stream.close()

        text = "\n".join(logs.output)
        self.assertIn("Final live quote subscription symbols (3)", text)
        self.assertIn("SHFE.AU2608", text)
        self.assertIn("SHFE.AU2608C600", text)
        self.assertIn("SHFE.AU2608P600", text)

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
        self.assertEqual(second.changed_symbols, {"SHFE.AU2608C600"})
        self.assertEqual(second.prices["SHFE.AU2608"], 600.0)
        self.assertEqual(second.prices["SHFE.AU2608P600"], 5.0)
        self.assertEqual(second.prices["SHFE.AU2608C600"], 6.0)
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
        symbols = [f"S{index}" for index in range(13000)]

        quotes = data_source._subscribe_live_quotes(api, symbols)

        self.assertEqual(set(quotes), set(symbols))

    def test_live_quote_subscription_rejects_count_above_threshold(self) -> None:
        api = _FakeApi(events=())
        data_source = _FakeLiveDataSource(api, quote_subscription_batch_size=500)
        symbols = [f"S{index}" for index in range(13001)]

        with self.assertRaisesRegex(ConfigError, "预处理后需要订阅的合约数量过多"):
            data_source._subscribe_live_quotes(api, symbols)

        self.assertEqual(api.quote_list_calls, ())

    def test_live_stream_rejects_preprocessed_universe_above_threshold(self) -> None:
        api = _FakeApi(events=())
        data_source = _FakeLiveDataSource(api, quote_subscription_batch_size=500)

        with self.assertRaisesRegex(ConfigError, "预处理后需要订阅的合约数量过多"):
            next(data_source._stream_live(_large_option_universe(6500)))

        self.assertEqual(data_source.create_api_calls, 0)
        self.assertEqual(api.quote_list_calls, ())


class BacktestKlineInitializationTests(unittest.TestCase):
    def test_backtest_finished_prunes_symbols_without_ready_prices(self) -> None:
        data_source = _FakeBacktestDataSource()
        serials = {
            "A": _FakeSerial("2026-01-02 09:31:00", 10.0),
            "B": _FakeSerial("", math.nan),
        }
        api = _FakeBacktestApi(raise_finished=True)

        with _quiet_tqsdk_output():
            backtest_finished = data_source._wait_for_batch_prices(api, serials, ["A", "B"], 1, 1)

        self.assertTrue(backtest_finished)
        self.assertEqual(set(serials), {"A"})

    def test_backtest_finished_without_any_ready_prices_still_fails(self) -> None:
        data_source = _FakeBacktestDataSource()
        serials = {
            "A": _FakeSerial("", math.nan),
            "B": _FakeSerial("", math.nan),
        }
        api = _FakeBacktestApi(raise_finished=True)

        with self.assertRaisesRegex(ConfigError, "no usable prices"):
            with _quiet_tqsdk_output():
                data_source._wait_for_batch_prices(api, serials, ["A", "B"], 1, 1)


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


@contextlib.contextmanager
def _quiet_tqsdk_output():
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


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


class _FakeSerial:
    def __init__(self, row_datetime: str, close: float, ready: bool = True) -> None:
        self._row = SimpleNamespace(datetime=row_datetime, close=close)
        self.ready = ready

    @property
    def iloc(self) -> "_FakeSerial":
        return self

    def __getitem__(self, _index: int) -> Any:
        return self._row


class _FakeLoop:
    def is_closed(self) -> bool:
        return True


class _FakeBacktestApi:
    _web_gui = False

    def __init__(self, raise_finished: bool = False) -> None:
        self.raise_finished = raise_finished
        self._loop = _FakeLoop()

    def is_serial_ready(self, serial: _FakeSerial) -> bool:
        return serial.ready

    def wait_update(self, deadline: float | None = None) -> bool:
        if self.raise_finished:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                from tqsdk.exceptions import BacktestFinished

            original_hook = sys.excepthook
            original_backtest_hook = BacktestFinished._orig_excepthook
            exc = BacktestFinished(self)
            sys.excepthook = original_hook
            BacktestFinished._orig_excepthook = original_backtest_hook
            raise exc
        return False


class _FakeApi:
    def __init__(self, events: tuple[_FakeEvent, ...]) -> None:
        self.events = list(events)
        self.quotes: dict[str, _FakeQuote] = {}
        self.changed_symbols: set[str] = set()
        self.closed = False
        self.close_count = 0
        self.quote_list_calls: tuple[tuple[str, ...], ...] = ()

    def query_quotes(self, **kwargs) -> list[str]:
        ins_class = kwargs.get("ins_class")
        if ins_class == "FUTURE":
            return ["SHFE.au2608"]
        if ins_class == "OPTION":
            return ["SHFE.au2608C600", "SHFE.au2608P600"]
        return []

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


class _FakeBacktestDataSource(TqSdkDataSource):
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            backtest=SimpleNamespace(
                initial_price_timeout_seconds=0,
            ),
        )
        self.stop_requested = None
        self.logger = logging.getLogger("tests.backtest_initialization")
        self.logger.handlers = [logging.NullHandler()]
        self.logger.propagate = False


if __name__ == "__main__":
    unittest.main()
