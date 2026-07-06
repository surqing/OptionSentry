from __future__ import annotations

import logging
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from optionsentry.config import ConfigError, load_config, parse_config
from optionsentry.models import InstrumentMeta, Universe
from optionsentry.data_sources.tqsdk_source import TqSdkDataSource, _row_to_meta
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

        self.assertIn("SHFE.AU2608", symbols)
        self.assertIn("SHFE.AU2608C600", symbols)

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

        self.assertEqual(meta.symbol, "SHFE.AU2608C600")
        self.assertEqual(meta.underlying_symbol, "SHFE.AU2608")
        self.assertEqual(meta.api_symbol, "SHFE.au2608C600")
        self.assertEqual(meta.api_underlying_symbol, "SHFE.au2608")

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

    def test_tqsdk_row_to_meta_reads_expiry_and_exercise_dates(self) -> None:
        meta = _row_to_meta(
            {
                "instrument_id": "au2608C600",
                "exchange_id": "SHFE",
                "ins_class": "OPTION",
                "expire_datetime": 1787641200,
                "expire_rest_days": 53,
                "delivery_year": 2026,
                "delivery_month": 8,
                "last_exercise_datetime": 1787641200,
                "exercise_year": 2026,
                "exercise_month": 7,
            },
            "SHFE.au2608C600",
        )

        self.assertEqual(meta.expire_datetime, 1787641200.0)
        self.assertEqual(meta.expire_rest_days, 53)
        self.assertEqual(meta.delivery_year, 2026)
        self.assertEqual(meta.delivery_month, 8)
        self.assertEqual(meta.last_exercise_datetime, 1787641200.0)
        self.assertEqual(meta.expire_date, date(2026, 8, 25))
        self.assertEqual(meta.last_exercise_date, date(2026, 8, 25))

    def test_tqsdk_row_to_meta_reads_static_contract_fields(self) -> None:
        meta = _row_to_meta(
            {
                "instrument_id": "au2608C600",
                "exchange_id": "SHFE",
                "ins_class": "OPTION",
                "price_tick": 0.5,
                "volume_multiple": 15,
                "open_limit": 0,
                "max_limit_order_volume": 100,
                "max_market_order_volume": 0,
                "min_limit_order_volume": 1,
                "min_market_order_volume": 0,
                "open_max_market_order_volume": 0,
                "open_max_limit_order_volume": 100,
                "open_min_market_order_volume": 0,
                "open_min_limit_order_volume": 1,
                "expired": False,
                "upper_limit": 20,
                "lower_limit": 1,
                "pre_settlement": 10,
                "pre_open_interest": 123,
                "pre_close": 9,
                "trading_time_day": [["09:00:00", "10:15:00"], ["13:30:00", "15:00:00"]],
                "trading_time_night": [["21:00:00", "26:30:00"]],
            },
            "SHFE.au2608C600",
        )

        self.assertEqual(meta.instrument_id, "au2608C600")
        self.assertEqual(meta.exchange_id, "SHFE")
        self.assertEqual(meta.price_tick, 0.5)
        self.assertEqual(meta.volume_multiple, 15.0)
        self.assertEqual(meta.open_limit, 0.0)
        self.assertEqual(meta.max_limit_order_volume, 100.0)
        self.assertEqual(meta.max_market_order_volume, 0.0)
        self.assertEqual(meta.min_limit_order_volume, 1.0)
        self.assertEqual(meta.min_market_order_volume, 0.0)
        self.assertEqual(meta.open_max_market_order_volume, 0.0)
        self.assertEqual(meta.open_max_limit_order_volume, 100.0)
        self.assertEqual(meta.open_min_market_order_volume, 0.0)
        self.assertEqual(meta.open_min_limit_order_volume, 1.0)
        self.assertFalse(meta.expired)
        self.assertEqual(meta.upper_limit, 20.0)
        self.assertEqual(meta.lower_limit, 1.0)
        self.assertEqual(meta.pre_settlement, 10.0)
        self.assertEqual(meta.pre_open_interest, 123.0)
        self.assertEqual(meta.pre_close, 9.0)
        self.assertEqual(meta.trading_time_day, (("09:00:00", "10:15:00"), ("13:30:00", "15:00:00")))
        self.assertEqual(meta.trading_time_night, (("21:00:00", "26:30:00"),))

    def test_tqsdk_query_metas_uses_batches(self) -> None:
        api = _FakeSymbolInfoApi()
        source = TqSdkDataSource(
            config=SimpleNamespace(tqsdk=SimpleNamespace(symbol_info_batch_size=2)),
            logger=logging.getLogger("tests.universe.batch_metas"),
        )

        metas = source._query_metas(
            api,
            (
                "SHFE.AU2608",
                "SHFE.AU2609",
                "SHFE.AU2610",
                "SHFE.AU2611",
                "SHFE.AU2612",
            ),
        )

        self.assertEqual(
            set(metas),
            {"SHFE.AU2608", "SHFE.AU2609", "SHFE.AU2610", "SHFE.AU2611", "SHFE.AU2612"},
        )
        self.assertEqual(
            api.calls,
            (
                ("SHFE.au2608", "SHFE.au2609"),
                ("SHFE.au2610", "SHFE.au2611"),
                ("SHFE.au2612",),
            ),
        )

    def test_config_parses_universe_liquidity_filters(self) -> None:
        config = parse_config(
            {
                "runtime": {},
                "universe": {"min_volume": 1, "min_open_interest": 2},
                "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
            }
        )

        self.assertEqual(config.universe.min_volume, 1)
        self.assertEqual(config.universe.min_open_interest, 2)
        self.assertEqual(config.logging.cycle_summary_interval_seconds, 60)
        self.assertTrue(config.gui.active_alerts.auto_refresh)
        self.assertEqual(config.gui.active_alerts.refresh_interval_seconds, 10)

        legacy_config = parse_config(
            {
                "runtime": {},
                "universe": {"min_volume": 100.0, "min_open_interest": 200.0},
                "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
            }
        )
        self.assertEqual(legacy_config.universe.min_volume, 100)
        self.assertEqual(legacy_config.universe.min_open_interest, 200)

        with self.assertRaises(ConfigError):
            parse_config(
                {
                    "runtime": {},
                    "universe": {"min_volume": -1},
                    "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
                }
            )
        with self.assertRaises(ConfigError):
            parse_config(
                {
                    "runtime": {},
                    "universe": {"min_volume": 1.5},
                    "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
                }
            )
        with self.assertRaises(ConfigError):
            parse_config(
                {
                    "runtime": {},
                    "logging": {"cycle_summary_interval_seconds": -1},
                    "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
                }
            )
        with self.assertRaises(ConfigError):
            parse_config(
                {
                    "runtime": {},
                    "gui": {"active_alerts": {"refresh_interval_seconds": 11}},
                    "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
                }
            )

    def test_config_normalizes_universe_match_terms(self) -> None:
        config = parse_config(
            {
                "runtime": {},
                "universe": {
                    "mode": "指定模式",
                    "only_do": ["shfe.au2608", "ag"],
                    "notDo": ["shfe.au2608c600"],
                    "exchange_ids": ["shfe"],
                },
                "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
            }
        )

        self.assertEqual(config.universe.only_do, ("SHFE.AU2608", "AG"))
        self.assertEqual(config.universe.not_do, ("SHFE.AU2608C600",))
        self.assertEqual(config.universe.exchange_ids, ("SHFE",))

        with self.assertRaisesRegex(ConfigError, "universe.only_do"):
            parse_config(
                {
                    "universe": {"mode": "指定模式"},
                    "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
                }
            )
        for removed_mode in ("onlyDo", "excludeDo"):
            with self.assertRaisesRegex(ConfigError, "universe.mode"):
                parse_config(
                    {
                        "universe": {"mode": removed_mode, "only_do": ["AG"]},
                        "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
                    }
                )

    def test_config_parses_active_alert_refresh_settings(self) -> None:
        config = parse_config(
            {
                "gui": {
                    "active_alerts": {
                        "auto_refresh": False,
                        "refresh_interval_seconds": 180,
                    }
                },
                "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
            }
        )

        self.assertFalse(config.gui.active_alerts.auto_refresh)
        self.assertEqual(config.gui.active_alerts.refresh_interval_seconds, 180)

    def test_config_parses_notifier_channels_and_legacy_defaults(self) -> None:
        strategies = [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}]

        live_config = parse_config({"strategies": strategies})

        self.assertFalse(live_config.notifier.channels.popup)
        self.assertFalse(live_config.notifier.channels.sound)
        self.assertTrue(live_config.notifier.channels.file)
        self.assertTrue(live_config.notifier.channels.email)
        self.assertEqual(live_config.notifier.popup.duration_seconds, 2)
        self.assertEqual(live_config.notifier.sound.duration_seconds, 2)

        backtest_config = parse_config(
            {
                "runtime": {"mode": "backtest"},
                "backtest": {"start_dt": "2026-01-02", "end_dt": "2026-01-05"},
                "strategies": strategies,
            }
        )
        self.assertTrue(backtest_config.notifier.channels.file)
        self.assertFalse(backtest_config.notifier.channels.email)

        legacy_console_config = parse_config(
            {
                "notifier": {"kind": "console"},
                "strategies": strategies,
            }
        )
        self.assertTrue(legacy_console_config.notifier.channels.file)
        self.assertFalse(legacy_console_config.notifier.channels.email)

        explicit_config = parse_config(
            {
                "notifier": {
                    "kind": "email",
                    "channels": {
                        "popup": True,
                        "sound": True,
                        "file": False,
                        "email": False,
                    },
                    "popup": {"duration_seconds": 5},
                    "sound": {"duration_seconds": 7},
                },
                "strategies": strategies,
            }
        )
        self.assertTrue(explicit_config.notifier.channels.popup)
        self.assertTrue(explicit_config.notifier.channels.sound)
        self.assertFalse(explicit_config.notifier.channels.file)
        self.assertFalse(explicit_config.notifier.channels.email)
        self.assertEqual(explicit_config.notifier.popup.duration_seconds, 5)
        self.assertEqual(explicit_config.notifier.sound.duration_seconds, 7)

        with self.assertRaises(ConfigError):
            parse_config(
                {
                    "notifier": {"popup": {"duration_seconds": 0}},
                    "strategies": strategies,
                }
            )
        with self.assertRaises(ConfigError):
            parse_config(
                {
                    "notifier": {"sound": {"duration_seconds": 3601}},
                    "strategies": strategies,
                }
            )

    def test_example_config_parses_with_gui_defaults(self) -> None:
        config = load_config(Path(__file__).resolve().parents[1] / "config.example.toml")

        self.assertTrue(config.gui.active_alerts.auto_refresh)
        self.assertEqual(config.gui.active_alerts.refresh_interval_seconds, 10)
        self.assertFalse(config.notifier.channels.popup)
        self.assertFalse(config.notifier.channels.sound)
        self.assertTrue(config.notifier.channels.file)
        self.assertTrue(config.notifier.channels.email)
        self.assertEqual(config.notifier.popup.duration_seconds, 2)
        self.assertEqual(config.notifier.sound.duration_seconds, 2)

    def test_live_universe_filters_liquidity_from_metadata(self) -> None:
        api = _FakeDiscoveryApi(_liquidity_rows(include_metrics=True))
        source = _FakeDiscoveryDataSource(api, min_volume=1, min_open_interest=1)

        universe = source.discover_universe()

        self.assertEqual(
            {option.symbol for option in universe.options},
            {"SHFE.AU2608C600", "SHFE.AU2608P620"},
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
            {"SHFE.AU2608C600", "SHFE.AU2608P620"},
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

    def test_specified_mode_discovers_matching_futures_and_options(self) -> None:
        api = _FakeDiscoveryApi(_multi_product_rows())
        source = _FakeDiscoveryDataSource(
            api,
            min_volume=0,
            min_open_interest=0,
            mode="指定模式",
            only_do=("Ag", "Au"),
        )

        universe = source.discover_universe()

        self.assertEqual(
            {option.symbol for option in universe.options},
            {
                "SHFE.AG2608C5000",
                "SHFE.AG2608P5000",
                "SHFE.AU2608C600",
                "SHFE.AU2608P600",
            },
        )
        self.assertEqual({future.symbol for future in universe.futures}, {"SHFE.AG2608", "SHFE.AU2608"})

    def test_not_do_removes_matching_futures_and_options_from_specified_mode(self) -> None:
        api = _FakeDiscoveryApi(_multi_product_rows())
        source = _FakeDiscoveryDataSource(
            api,
            min_volume=0,
            min_open_interest=0,
            mode="指定模式",
            only_do=("Ag", "Au"),
            not_do=("Ag2608",),
        )

        universe = source.discover_universe()

        self.assertEqual(
            {option.symbol for option in universe.options},
            {"SHFE.AU2608C600", "SHFE.AU2608P600"},
        )
        self.assertEqual({future.symbol for future in universe.futures}, {"SHFE.AU2608"})


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
        mode: str = "all",
        only_do: tuple[str, ...] = (),
        not_do: tuple[str, ...] = (),
    ) -> None:
        self.api = api
        self.probe_apis = list(probe_apis)
        self.config = SimpleNamespace(
            runtime=SimpleNamespace(mode="live"),
            universe=SimpleNamespace(
                mode=mode,
                only_do=only_do,
                not_do=not_do,
                exchange_ids=("SHFE",) if mode == "all" else (),
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
        ins_class = kwargs.get("ins_class")
        return [
            symbol
            for symbol, row in self.rows.items()
            if row.get("ins_class") == ins_class
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


def _multi_product_rows() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    rows.update(
        _product_rows(
            product="au",
            future="au2608",
            strike=600.0,
            instrument_name="Gold",
        )
    )
    rows.update(
        _product_rows(
            product="ag",
            future="ag2608",
            strike=5000.0,
            instrument_name="Silver",
        )
    )
    rows.update(
        _product_rows(
            product="cu",
            future="cu2608",
            strike=70000.0,
            instrument_name="Copper",
        )
    )
    return rows


def _product_rows(
    *,
    product: str,
    future: str,
    strike: float,
    instrument_name: str,
) -> dict[str, dict[str, Any]]:
    exchange = "SHFE"
    call = f"{future}C{int(strike)}"
    put = f"{future}P{int(strike)}"
    return {
        f"{exchange}.{future}": {
            "instrument_id": future,
            "exchange_id": exchange,
            "ins_class": "FUTURE",
            "product_id": product,
            "instrument_name": instrument_name,
        },
        f"{exchange}.{call}": {
            "instrument_id": call,
            "exchange_id": exchange,
            "ins_class": "OPTION",
            "underlying_symbol": future,
            "strike_price": strike,
            "option_class": "CALL",
            "exercise_year": 2026,
            "exercise_month": 8,
            "product_id": product,
            "instrument_name": f"{instrument_name} call",
        },
        f"{exchange}.{put}": {
            "instrument_id": put,
            "exchange_id": exchange,
            "ins_class": "OPTION",
            "underlying_symbol": future,
            "strike_price": strike,
            "option_class": "PUT",
            "exercise_year": 2026,
            "exercise_month": 8,
            "product_id": product,
            "instrument_name": f"{instrument_name} put",
        },
    }


if __name__ == "__main__":
    unittest.main()
