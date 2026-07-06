from __future__ import annotations

import logging
import math
import os
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterator

from optionsentry.config import AppConfig, ConfigError
from optionsentry.models import InstrumentMeta, MarketSnapshot, Universe
from optionsentry.symbols import normalize_symbol, tqsdk_api_symbol


FUTURE_EXCHANGES = {"CFFEX", "SHFE", "DCE", "CZCE", "INE", "GFEX"}
LIQUIDITY_FILTER_TIMEOUT_SECONDS = 30
MAX_LIVE_SUBSCRIPTION_SYMBOLS = 13000


@dataclass
class TqSdkDataSource:
    config: AppConfig
    logger: logging.Logger
    stop_requested: Callable[[], bool] | None = None
    _live_api: Any | None = field(default=None, init=False, repr=False)

    def discover_universe(self) -> Universe:
        api = self._create_api()
        keep_api_for_live = False
        try:
            option_symbols = self._discover_option_symbols(api)
            if not option_symbols:
                self.logger.warning("No option symbols discovered.")
                return Universe(instruments={})

            option_metas = self._query_metas(api, option_symbols)
            underlying_symbols = sorted(
                {
                    meta.underlying_symbol
                    for meta in option_metas.values()
                    if meta.is_option and meta.underlying_symbol
                }
            )
            underlying_metas = self._query_metas(api, underlying_symbols) if underlying_symbols else {}
            future_underlyings = {
                symbol: meta
                for symbol, meta in underlying_metas.items()
                if meta.is_future or _looks_like_future_symbol(symbol)
            }
            filtered_options = {
                symbol: meta
                for symbol, meta in option_metas.items()
                if meta.is_option and meta.underlying_symbol in future_underlyings
            }
            future_underlyings, filtered_options, used_liquidity_quote_scan = self._apply_liquidity_filters(
                api,
                future_underlyings,
                filtered_options,
            )
            instruments = {**future_underlyings, **filtered_options}
            universe = Universe(instruments=instruments, requested_symbols=tuple(sorted(option_metas)))
            self.logger.info(
                "Discovered universe: options=%s futures=%s price_symbols=%s",
                len(universe.options),
                len(universe.futures),
                len(universe.price_symbols()),
            )
            if self.config.runtime.mode == "live" and not used_liquidity_quote_scan:
                self._replace_live_api(api)
                keep_api_for_live = True
                self.logger.info("Reusing discovery TqApi connection for live quote subscription.")
            elif self.config.runtime.mode == "live" and used_liquidity_quote_scan:
                self.logger.info(
                    "Closing discovery TqApi connection after liquidity probe; "
                    "live stream will subscribe filtered symbols with a fresh connection."
                )
            return universe
        finally:
            if not keep_api_for_live:
                api.close()

    def stream(self, universe: Universe) -> Iterator[MarketSnapshot]:
        if self.config.runtime.mode == "live":
            yield from self._stream_live(universe)
            return
        groups = universe.strategy_groups()
        self.logger.info(
            "Backtest will run %s strategy group(s).",
            len(groups),
        )
        for index, group in enumerate(groups, start=1):
            if self._should_stop():
                return
            self.logger.info(
                "Starting backtest group %s/%s with %s symbols.",
                index,
                len(groups),
                len(group.price_symbols()),
            )
            yield from self._stream_backtest_universe(group)

    def close(self) -> None:
        self._close_live_api()

    def _discover_option_symbols(self, api: Any) -> list[str]:
        universe_config = self.config.universe
        if universe_config.mode == "all":
            return self._discover_active_symbols(api, "OPTION", universe_config.exchange_ids)

        option_symbols = self._discover_active_symbols(api, "OPTION")
        if universe_config.mode == "指定模式":
            included_symbols = set(_filter_symbols_by_terms(option_symbols, universe_config.only_do))
            excluded_symbols = set(_filter_symbols_by_terms(option_symbols, universe_config.not_do))
            symbols = sorted(included_symbols - excluded_symbols)
            self.logger.info(
                "Applied universe specified filter: only_do=%s not_do=%s options %s -> %s.",
                universe_config.only_do,
                universe_config.not_do,
                len(option_symbols),
                len(symbols),
            )
            return symbols
        raise ConfigError(f"Unsupported universe mode: {universe_config.mode}")

    def _discover_active_symbols(
        self,
        api: Any,
        ins_class: str,
        exchange_ids: tuple[str, ...] = (),
    ) -> list[str]:
        exchanges = list(exchange_ids) or [None]
        symbols: list[str] = []
        for exchange_id in exchanges:
            kwargs = {"ins_class": ins_class, "expired": False}
            if exchange_id:
                kwargs["exchange_id"] = exchange_id
            symbols.extend(list(api.query_quotes(**kwargs)))
        return sorted(set(symbols))

    def _query_metas(self, api: Any, symbols: list[str] | tuple[str, ...]) -> dict[str, InstrumentMeta]:
        if not symbols:
            return {}
        result: dict[str, InstrumentMeta] = {}
        symbol_list = [tqsdk_api_symbol(symbol) for symbol in symbols]
        batch_size = self.config.tqsdk.symbol_info_batch_size
        batches = list(_batches(symbol_list, batch_size))
        if len(batches) > 1:
            self.logger.info(
                "Querying symbol metadata in %s batch(es) with batch_size=%s.",
                len(batches),
                batch_size,
            )
        for batch_index, batch in enumerate(batches, start=1):
            if len(batches) > 1:
                self.logger.info(
                    "Querying symbol metadata batch %s/%s with %s symbols.",
                    batch_index,
                    len(batches),
                    len(batch),
                )
            try:
                df = api.query_symbol_info(batch)
            except Exception:
                self.logger.exception(
                    "\n"
                    "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                    "!!! 合约元数据查询失败，监控启动已中断\n"
                    "!!! batch=%s/%s batch_size=%s symbols_in_batch=%s\n"
                    "!!! first_symbols=%s\n"
                    "!!! last_symbols=%s\n"
                    "!!! 提示：请检查 only_do/not_do 是否足够收窄；"
                    "如果必须扫描大量合约，可尝试调小 datasource.tqsdk.symbol_info_batch_size。\n"
                    "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
                    batch_index,
                    len(batches),
                    batch_size,
                    len(batch),
                    batch[:10],
                    batch[-10:],
                )
                raise
            for position, (index, row) in enumerate(df.iterrows()):
                fallback_symbol = batch[position] if position < len(batch) else str(index)
                meta = _row_to_meta(row, fallback_symbol)
                if meta.symbol:
                    result[meta.symbol] = meta
        return result

    def _apply_liquidity_filters(
        self,
        api: Any,
        future_metas: dict[str, InstrumentMeta],
        option_metas: dict[str, InstrumentMeta],
    ) -> tuple[dict[str, InstrumentMeta], dict[str, InstrumentMeta], bool]:
        min_volume = _config_number(getattr(self.config.universe, "min_volume", 0))
        min_open_interest = _config_number(getattr(self.config.universe, "min_open_interest", 0))
        if min_volume <= 0 and min_open_interest <= 0:
            return future_metas, option_metas, False
        if self.config.runtime.mode != "live":
            self.logger.warning("Universe liquidity filters are only applied in live mode.")
            return future_metas, option_metas, False

        metas = {**future_metas, **option_metas}
        metrics = {
            symbol: (meta.volume, meta.open_interest)
            for symbol, meta in metas.items()
            if meta.volume is not None or meta.open_interest is not None
        }
        missing_metric_symbols = [
            symbol
            for symbol, meta in metas.items()
            if (min_volume > 0 and meta.volume is None)
            or (min_open_interest > 0 and meta.open_interest is None)
        ]
        used_quote_scan = False
        if missing_metric_symbols:
            self.logger.info(
                "Probing liquidity metrics for %s/%s symbols with missing metadata.",
                len(missing_metric_symbols),
                len(metas),
            )
            metrics.update(
                self._query_liquidity_metrics(
                    sorted(missing_metric_symbols),
                    _api_symbols_by_internal_symbol(metas),
                )
            )
            used_quote_scan = True

        kept_futures = {
            symbol: meta
            for symbol, meta in future_metas.items()
            if _passes_liquidity_filters(meta, metrics, min_volume, min_open_interest)
        }
        kept_options = {
            symbol: meta
            for symbol, meta in option_metas.items()
            if meta.underlying_symbol in kept_futures
            and _passes_liquidity_filters(meta, metrics, min_volume, min_open_interest)
        }
        self.logger.info(
            "Applied universe liquidity filters: min_volume=%s min_open_interest=%s "
            "options %s -> %s, futures %s -> %s.",
            _format_threshold(min_volume),
            _format_threshold(min_open_interest),
            len(option_metas),
            len(kept_options),
            len(future_metas),
            len(kept_futures),
        )
        return kept_futures, kept_options, used_quote_scan

    def _query_liquidity_metrics(
        self,
        symbols: list[str],
        api_symbols_by_symbol: dict[str, str] | None = None,
    ) -> dict[str, tuple[float | None, float | None]]:
        if not symbols:
            return {}
        metrics: dict[str, tuple[float | None, float | None]] = {}
        missing_symbols: list[str] = []
        api_symbols_by_symbol = api_symbols_by_symbol or {}
        batch_size = self.config.tqsdk.quote_subscription_batch_size
        batches = list(_batches(symbols, batch_size))
        for batch_index, batch in enumerate(batches, start=1):
            if self._should_stop():
                break
            self.logger.info(
                "Probing liquidity quote batch %s/%s with %s symbols using an isolated TqApi.",
                batch_index,
                len(batches),
                len(batch),
            )
            batch_api = self._create_api()
            try:
                api_batch = [api_symbols_by_symbol.get(symbol, tqsdk_api_symbol(symbol)) for symbol in batch]
                quotes = dict(zip(batch, batch_api.get_quote_list(api_batch), strict=True))
                missing_symbols.extend(self._wait_liquidity_quote_batch(batch_api, quotes))
                metrics.update(_quote_liquidity_metrics(quotes))
            finally:
                batch_api.close()

        if missing_symbols:
            self.logger.warning(
                "Liquidity probe received snapshots for %s/%s symbols before timeout; "
                "missing symbols may be treated as zero. First 20 missing: %s",
                len(metrics) - len(missing_symbols),
                len(metrics),
                missing_symbols[:20],
            )
        return metrics

    def _wait_liquidity_quote_batch(self, api: Any, quotes: dict[str, Any]) -> list[str]:
        deadline = time.time() + LIQUIDITY_FILTER_TIMEOUT_SECONDS
        while True:
            missing = _missing_liquidity_snapshot_symbols(quotes)
            if not missing or time.time() >= deadline or self._should_stop():
                return missing
            api.wait_update(deadline=min(deadline, time.time() + 2))

    def _stream_live(self, universe: Universe) -> Iterator[MarketSnapshot]:
        symbols = sorted(universe.price_symbols())
        if not symbols:
            self.logger.warning("No symbols to subscribe.")
            return
        _validate_live_subscription_size(symbols)
        api = self._consume_live_api() or self._create_api()
        try:
            quotes = self._subscribe_live_quotes(api, symbols, _api_symbols_by_internal_symbol(universe))
            self.logger.info("Subscribed live quotes: %s", len(quotes))
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(
                    "Final live quote subscription symbols (%s): %s",
                    len(quotes),
                    sorted(quotes),
                )
            prices: dict[str, float] = {}
            initialized = False
            while not self._should_stop():
                updated = api.wait_update(deadline=time.time() + 1)
                if not updated:
                    continue
                changed_symbols: set[str] = set()
                timestamp = ""
                for symbol, quote in quotes.items():
                    quote_time = getattr(quote, "datetime", "")
                    if quote_time and quote_time > timestamp:
                        timestamp = quote_time
                    price = getattr(quote, "last_price", math.nan)
                    price_changed = api.is_changing(quote, "last_price")
                    if _valid_number(price):
                        if price_changed or symbol not in prices:
                            prices[symbol] = float(price)
                    elif price_changed:
                        prices.pop(symbol, None)
                    if price_changed:
                        changed_symbols.add(symbol)
                if not prices:
                    continue
                if changed_symbols or not initialized:
                    initialized = True
                    yield MarketSnapshot(
                        timestamp=timestamp or datetime.now().isoformat(timespec="seconds"),
                        prices=dict(prices),
                        changed_symbols=changed_symbols or set(prices),
                        universe=universe,
                    )
        except Exception:
            self.logger.exception("TqSdk live stream failed.")
            raise
        finally:
            api.close()

    def _replace_live_api(self, api: Any) -> None:
        current_api = getattr(self, "_live_api", None)
        if current_api is not None and current_api is not api:
            with suppress(Exception):
                current_api.close()
        self._live_api = api

    def _consume_live_api(self) -> Any | None:
        api = getattr(self, "_live_api", None)
        self._live_api = None
        return api

    def _close_live_api(self) -> None:
        api = self._consume_live_api()
        if api is not None:
            with suppress(Exception):
                api.close()

    def _subscribe_live_quotes(
        self,
        api: Any,
        symbols: list[str],
        api_symbols_by_symbol: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        _validate_live_subscription_size(symbols)
        quotes: dict[str, Any] = {}
        api_symbols_by_symbol = api_symbols_by_symbol or {}
        batch_size = self.config.tqsdk.quote_subscription_batch_size
        batches = list(_batches(symbols, batch_size))
        for batch_index, batch in enumerate(batches, start=1):
            self.logger.info(
                "Subscribing live quote batch %s/%s with %s symbols.",
                batch_index,
                len(batches),
                len(batch),
            )
            api_batch = [api_symbols_by_symbol.get(symbol, tqsdk_api_symbol(symbol)) for symbol in batch]
            quotes.update(dict(zip(batch, api.get_quote_list(api_batch), strict=True)))
            if batch_index < len(batches):
                api.wait_update(deadline=time.time() + 5)
        return quotes

    def _stream_backtest_universe(self, universe: Universe) -> Iterator[MarketSnapshot]:
        from tqsdk.exceptions import BacktestFinished

        symbols = sorted(universe.price_symbols())
        if not symbols:
            return
        symbols = _order_backtest_symbols(universe, symbols)
        if len(symbols) > 100:
            self.logger.info(
                "Backtest symbol count %s exceeds TqSdk get_quote_list's 100-symbol limit; "
                "using K-line serial subscriptions instead.",
                len(symbols),
            )

        api = self._create_api()
        try:
            serials = self._create_backtest_serials(api, symbols, _api_symbols_by_internal_symbol(universe))
            symbols = [symbol for symbol in symbols if symbol in serials]
            self.logger.info("Subscribed backtest K-lines: %s", len(serials))
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(
                    "Final backtest K-line subscription symbols (%s): %s",
                    len(symbols),
                    symbols,
                )
            last_datetime: Any = None
            last_ready_count = -1
            last_wait_log = 0.0
            initialized = False
            initial_timeout = max(
                self.config.backtest.initial_price_timeout_seconds,
                30 + 3 * len(symbols),
            )
            initial_deadline = time.time() + initial_timeout

            while not self._should_stop():
                row_dt, prices, synced = self._collect_synced_backtest_prices(serials, symbols)
                ready_count = len(prices)
                now = time.time()
                if ready_count != last_ready_count:
                    last_ready_count = ready_count
                    self.logger.info(
                        "Backtest K-line price cache ready: %s/%s symbols.",
                        ready_count,
                        len(symbols),
                    )
                elif not initialized and now - last_wait_log >= 30:
                    last_wait_log = now
                    self.logger.info(
                        "Waiting for synced initial backtest K-line prices: %s/%s symbols ready.",
                        ready_count,
                        len(symbols),
                    )

                if synced and row_dt != last_datetime:
                    initialized = True
                    last_datetime = row_dt
                    yield MarketSnapshot(
                        timestamp=_format_tq_datetime(row_dt) or datetime.now().isoformat(timespec="seconds"),
                        prices=prices,
                        changed_symbols=set(prices),
                        universe=universe,
                    )
                    continue

                if not initialized and now > initial_deadline:
                    missing = sorted(set(symbols) - set(prices))
                    raise ConfigError(
                        "Backtest did not receive initial K-line prices for all symbols within "
                        f"{int(initial_timeout)} seconds. "
                        f"Missing {len(missing)} symbols, first 20: {missing[:20]}"
                    )
                try:
                    api.wait_update(deadline=time.time() + 5 if not initialized else time.time() + 1)
                except BacktestFinished:
                    break
        except Exception:
            self.logger.exception("TqSdk backtest stream failed.")
            raise
        finally:
            api.close()

    def _create_backtest_serials(
        self,
        api: Any,
        symbols: list[str],
        api_symbols_by_symbol: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        from tqsdk.exceptions import BacktestFinished

        serials: dict[str, Any] = {}
        api_symbols_by_symbol = api_symbols_by_symbol or {}
        batch_size = self.config.backtest.subscription_batch_size
        batches = [symbols[index:index + batch_size] for index in range(0, len(symbols), batch_size)]

        for batch_index, batch in enumerate(batches, start=1):
            async def subscribe_batch(batch_symbols: list[str] = batch) -> None:
                for symbol in batch_symbols:
                    serials[symbol] = api.get_kline_serial(
                        api_symbols_by_symbol.get(symbol, tqsdk_api_symbol(symbol)),
                        self.config.backtest.duration_seconds,
                        data_length=self.config.backtest.data_length,
                    )

            self.logger.info(
                "Subscribing backtest K-line batch %s/%s with %s symbols.",
                batch_index,
                len(batches),
                len(batch),
            )
            task = api.create_task(subscribe_batch())
            while not task.done():
                if self._should_stop():
                    raise ConfigError("Backtest subscription stopped by user.")
                try:
                    api.wait_update(deadline=time.time() + 5)
                except BacktestFinished as exc:
                    raise ConfigError(
                        f"Backtest finished before K-line batch {batch_index}/{len(batches)} "
                        "subscriptions were created."
                    ) from exc
            if task.done():
                error = task.exception()
                if error is not None:
                    raise error
            backtest_finished = self._wait_for_batch_prices(api, serials, batch, batch_index, len(batches))
            if backtest_finished:
                self.logger.info(
                    "Stopping further backtest K-line subscriptions after batch %s/%s because "
                    "the backtest ended during initialization.",
                    batch_index,
                    len(batches),
                )
                break

        if not serials:
            raise ConfigError("Backtest did not receive usable K-line prices for any subscribed symbol.")
        if len(serials) != len(symbols):
            skipped = sorted(set(symbols) - set(serials))
            self.logger.warning(
                "Backtest K-line initialization kept %s/%s symbols; skipped %s symbols with "
                "missing K-line prices. First 20 skipped: %s",
                len(serials),
                len(symbols),
                len(skipped),
                skipped[:20],
            )
        return serials

    def _wait_for_batch_prices(
        self,
        api: Any,
        serials: dict[str, Any],
        batch: list[str],
        batch_index: int,
        batch_count: int,
    ) -> bool:
        from tqsdk.exceptions import BacktestFinished

        timeout = max(
            self.config.backtest.initial_price_timeout_seconds,
            30 + 3 * len(batch),
        )
        deadline = time.time() + timeout
        last_download_count = -1
        last_ready_count = -1
        last_wait_log = 0.0
        while True:
            if self._should_stop():
                raise ConfigError("Backtest initialization stopped by user.")
            _, prices, _ = self._collect_synced_backtest_prices(serials, batch)
            ready_count = len(prices)
            download_count = sum(1 for symbol in batch if api.is_serial_ready(serials[symbol]))
            now = time.time()
            if download_count != last_download_count or ready_count != last_ready_count:
                last_download_count = download_count
                last_ready_count = ready_count
                self.logger.info(
                    "Backtest K-line batch %s/%s progress: %s/%s downloaded, %s/%s ready.",
                    batch_index,
                    batch_count,
                    download_count,
                    len(batch),
                    ready_count,
                    len(batch),
                )
            elif now - last_wait_log >= 30:
                last_wait_log = now
                self.logger.info(
                    "Waiting for backtest K-line batch %s/%s: %s/%s downloaded, %s/%s ready.",
                    batch_index,
                    batch_count,
                    download_count,
                    len(batch),
                    ready_count,
                    len(batch),
                )
            if ready_count == len(batch):
                return False
            if now > deadline:
                self._prune_unready_backtest_symbols(
                    serials,
                    batch,
                    prices,
                    f"did not initialize within {int(timeout)} seconds",
                    batch_index,
                    batch_count,
                )
                return False
            try:
                api.wait_update(deadline=time.time() + 5)
            except BacktestFinished:
                self._prune_unready_backtest_symbols(
                    serials,
                    batch,
                    prices,
                    "finished before all symbols initialized",
                    batch_index,
                    batch_count,
                )
                return True

    def _prune_unready_backtest_symbols(
        self,
        serials: dict[str, Any],
        batch: list[str],
        prices: dict[str, float],
        reason: str,
        batch_index: int,
        batch_count: int,
    ) -> None:
        missing = sorted(set(batch) - set(prices))
        if not prices:
            raise ConfigError(
                f"Backtest K-line batch {batch_index}/{batch_count} {reason}; "
                f"no usable prices were received. Missing {len(missing)} symbols, "
                f"first 20: {missing[:20]}"
            )
        for symbol in missing:
            serials.pop(symbol, None)
        self.logger.warning(
            "Backtest K-line batch %s/%s %s; continuing with %s/%s ready symbols. "
            "Skipped %s symbols, first 20: %s",
            batch_index,
            batch_count,
            reason,
            len(prices),
            len(batch),
            len(missing),
            missing[:20],
        )

    def _collect_synced_backtest_prices(
        self,
        serials: dict[str, Any],
        symbols: list[str],
    ) -> tuple[Any, dict[str, float], bool]:
        prices: dict[str, float] = {}
        datetimes: dict[str, Any] = {}
        for symbol in symbols:
            row = serials[symbol].iloc[-1]
            row_dt = getattr(row, "datetime", "")
            close = getattr(row, "close", math.nan)
            if _valid_datetime(row_dt) and _valid_number(close):
                prices[symbol] = float(close)
                datetimes[symbol] = row_dt
        if len(prices) != len(symbols):
            return "", prices, False
        unique_datetimes = {_datetime_key(value) for value in datetimes.values()}
        if len(unique_datetimes) != 1:
            return "", prices, False
        return next(iter(datetimes.values())), prices, True

    def _create_api(self) -> Any:
        from tqsdk import TqApi, TqAuth, TqBacktest, TqSim

        username = os.environ.get(self.config.tqsdk.username_env)
        password = os.environ.get(self.config.tqsdk.password_env)
        if not username or not password:
            raise ConfigError(
                f"TqSdk auth requires {self.config.tqsdk.username_env} "
                f"and {self.config.tqsdk.password_env}."
            )
        auth = TqAuth(username, password)
        if self.config.runtime.mode == "backtest":
            return TqApi(
                TqSim(),
                backtest=TqBacktest(
                    start_dt=self.config.backtest.start_dt,
                    end_dt=self.config.backtest.end_dt,
                ),
                auth=auth,
            )
        return TqApi(auth=auth)

    def _should_stop(self) -> bool:
        return bool(self.stop_requested and self.stop_requested())


def _row_to_meta(row: Any, fallback_symbol: str) -> InstrumentMeta:
    exchange_id = _clean_str(_row_get(row, "exchange_id"))
    raw_symbol = _clean_str(_row_get(row, "instrument_id")) or fallback_symbol
    api_symbol = _full_symbol(raw_symbol, exchange_id, fallback_symbol)
    api_underlying_symbol = _full_symbol(
        _clean_str(_row_get(row, "underlying_symbol")),
        exchange_id,
        "",
    )
    return InstrumentMeta(
        symbol=normalize_symbol(api_symbol),
        ins_class=_clean_str(_row_get(row, "ins_class")),
        instrument_id=_clean_str(_row_get(row, "instrument_id")),
        exchange_id=exchange_id,
        underlying_symbol=normalize_symbol(api_underlying_symbol) if api_underlying_symbol else "",
        strike_price=_optional_float(_row_get(row, "strike_price")),
        option_class=_clean_str(_row_get(row, "option_class")),
        exercise_year=_optional_int(_row_get(row, "exercise_year")),
        exercise_month=_optional_int(_row_get(row, "exercise_month")),
        instrument_name=_clean_str(_row_get(row, "instrument_name")),
        product_id=_clean_str(_row_get(row, "product_id")),
        price_tick=_optional_float(_row_get(row, "price_tick")),
        volume_multiple=_optional_float(_row_get(row, "volume_multiple")),
        open_limit=_optional_float(_row_get(row, "open_limit")),
        max_limit_order_volume=_optional_float(_row_get(row, "max_limit_order_volume")),
        max_market_order_volume=_optional_float(_row_get(row, "max_market_order_volume")),
        min_limit_order_volume=_optional_float(_row_get(row, "min_limit_order_volume")),
        min_market_order_volume=_optional_float(_row_get(row, "min_market_order_volume")),
        open_max_market_order_volume=_optional_float(_row_get(row, "open_max_market_order_volume")),
        open_max_limit_order_volume=_optional_float(_row_get(row, "open_max_limit_order_volume")),
        open_min_market_order_volume=_optional_float(_row_get(row, "open_min_market_order_volume")),
        open_min_limit_order_volume=_optional_float(_row_get(row, "open_min_limit_order_volume")),
        volume=_optional_float(_row_get(row, "volume")),
        open_interest=_optional_float(_row_get(row, "open_interest")),
        expired=_optional_bool(_row_get(row, "expired")),
        expire_datetime=_optional_float(_row_get(row, "expire_datetime")),
        expire_rest_days=_optional_int(_row_get(row, "expire_rest_days")),
        delivery_year=_optional_int(_row_get(row, "delivery_year")),
        delivery_month=_optional_int(_row_get(row, "delivery_month")),
        last_exercise_datetime=_optional_float(_row_get(row, "last_exercise_datetime")),
        upper_limit=_optional_float(_row_get(row, "upper_limit")),
        lower_limit=_optional_float(_row_get(row, "lower_limit")),
        pre_settlement=_optional_float(_row_get(row, "pre_settlement")),
        pre_open_interest=_optional_float(_row_get(row, "pre_open_interest")),
        pre_close=_optional_float(_row_get(row, "pre_close")),
        trading_time_day=_trading_sessions(_row_get(row, "trading_time_day")),
        trading_time_night=_trading_sessions(_row_get(row, "trading_time_night")),
        api_symbol=api_symbol,
        api_underlying_symbol=api_underlying_symbol,
    )


def _row_get(row: Any, key: str) -> Any:
    with suppress(Exception):
        return row[key]
    return None


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    with suppress(TypeError, ValueError):
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
    return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    with suppress(TypeError, ValueError):
        numeric = float(value)
        if math.isfinite(numeric):
            return int(numeric)
    return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
        return None
    with suppress(TypeError, ValueError):
        return bool(value)
    return None


def _trading_sessions(value: Any) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    sessions: list[tuple[str, str]] = []
    try:
        iterator = iter(value)
    except TypeError:
        return ()
    for item in iterator:
        with suppress(TypeError, IndexError):
            start = str(item[0])
            end = str(item[1])
            if start and end:
                sessions.append((start, end))
    return tuple(sessions)


def _valid_number(value: Any) -> bool:
    with suppress(TypeError, ValueError):
        return math.isfinite(float(value))
    return False


def _config_number(value: Any) -> float:
    with suppress(TypeError, ValueError):
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
    return 0.0


def _passes_liquidity_filters(
    meta: InstrumentMeta,
    metrics: dict[str, tuple[float | None, float | None]],
    min_volume: float,
    min_open_interest: float,
) -> bool:
    volume, open_interest = metrics.get(meta.symbol, (meta.volume, meta.open_interest))
    if min_volume > 0 and not _metric_at_least(volume, min_volume):
        return False
    if min_open_interest > 0 and not _metric_at_least(open_interest, min_open_interest):
        return False
    return True


def _metric_at_least(value: float | None, threshold: float) -> bool:
    return value is not None and _valid_number(value) and float(value) >= threshold


def _quote_has_snapshot(quote: Any) -> bool:
    return bool(getattr(quote, "datetime", ""))


def _missing_liquidity_snapshot_symbols(quotes: dict[str, Any]) -> list[str]:
    return [
        symbol
        for symbol, quote in quotes.items()
        if not _quote_has_snapshot(quote)
    ]


def _quote_liquidity_metrics(quotes: dict[str, Any]) -> dict[str, tuple[float | None, float | None]]:
    return {
        symbol: (
            _optional_float(getattr(quote, "volume", None)),
            _optional_float(getattr(quote, "open_interest", None)),
        )
        for symbol, quote in quotes.items()
    }


def _format_threshold(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)


def _valid_datetime(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value != ""
    with suppress(TypeError, ValueError):
        numeric = float(value)
        return math.isfinite(numeric) and numeric > 0
    return True


def _datetime_key(value: Any) -> str:
    if isinstance(value, str):
        return value
    with suppress(TypeError, ValueError):
        numeric = float(value)
        if math.isfinite(numeric):
            return f"{numeric:.0f}"
    return str(value)


def _format_tq_datetime(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    with suppress(TypeError, ValueError, OSError):
        numeric = float(value)
        if not math.isfinite(numeric):
            return ""
        if numeric > 10_000_000_000:
            numeric = numeric / 1_000_000_000
        return datetime.fromtimestamp(numeric).isoformat(timespec="seconds")
    return str(value)


def _latest_timestamp(datetimes: dict[str, Any]) -> str:
    latest = ""
    for value in datetimes.values():
        text = _format_tq_datetime(value)
        if text and text > latest:
            latest = text
    return latest


def _looks_like_future_symbol(symbol: str) -> bool:
    normalized = normalize_symbol(symbol)
    exchange = normalized.split(".", 1)[0] if "." in normalized else ""
    return exchange in FUTURE_EXCHANGES


def _filter_symbols_by_terms(symbols: list[str], terms: tuple[str, ...]) -> list[str]:
    normalized_terms = tuple(_match_text(term) for term in terms if _match_text(term))
    if not normalized_terms:
        return []
    return sorted(
        symbol
        for symbol in symbols
        if _symbol_matches_terms(symbol, normalized_terms)
    )


def _symbol_matches_terms(symbol: str, normalized_terms: tuple[str, ...]) -> bool:
    normalized_haystacks = (_match_text(symbol), _match_text(tqsdk_api_symbol(symbol)))
    return any(
        term in haystack
        for term in normalized_terms
        for haystack in normalized_haystacks
    )


def _match_text(value: object) -> str:
    return str(value).strip().upper()


def _api_symbols_by_internal_symbol(universe_or_metas: Universe | dict[str, InstrumentMeta]) -> dict[str, str]:
    metas = (
        universe_or_metas.instruments.values()
        if isinstance(universe_or_metas, Universe)
        else universe_or_metas.values()
    )
    result: dict[str, str] = {}
    for meta in metas:
        result[meta.symbol] = meta.api_symbol or tqsdk_api_symbol(meta.symbol)
        if meta.underlying_symbol:
            result.setdefault(
                meta.underlying_symbol,
                meta.api_underlying_symbol or tqsdk_api_symbol(meta.underlying_symbol),
            )
    return result


def _order_backtest_symbols(universe: Universe, symbols: list[str]) -> list[str]:
    underlyings = sorted(universe.underlying_symbols)
    ordered = [symbol for symbol in underlyings if symbol in symbols]
    ordered.extend(symbol for symbol in symbols if symbol not in set(ordered))
    return ordered


def _validate_live_subscription_size(symbols: list[str]) -> None:
    if len(symbols) <= MAX_LIVE_SUBSCRIPTION_SYMBOLS:
        return
    raise ConfigError(
        "预处理后需要订阅的合约数量过多，已停止本次预警系统启动。\n\n"
        f"当前需要订阅 {len(symbols)} 个合约，最大允许 {MAX_LIVE_SUBSCRIPTION_SYMBOLS} 个。\n\n"
        "请通过以下方式降低订阅数：\n"
        "- 将合约范围模式从 all 改为指定模式，只填写需要监控的品种或合约关键字。\n"
        "- 缩小 exchange_ids，只扫描必要交易所。\n"
        "- 提高 min_volume 或 min_open_interest，过滤低流动性期权。\n"
        "- 减少要监控的到期月份或标的范围。"
    )


def _batches(symbols: list[str], batch_size: int) -> Iterator[list[str]]:
    for index in range(0, len(symbols), batch_size):
        yield symbols[index:index + batch_size]


def _full_symbol(raw_symbol: str, exchange_id: str, fallback_symbol: str) -> str:
    if not raw_symbol:
        return fallback_symbol
    if "." in raw_symbol:
        return raw_symbol
    if fallback_symbol and "." in fallback_symbol:
        return fallback_symbol
    if exchange_id:
        return f"{exchange_id}.{raw_symbol}"
    return raw_symbol
