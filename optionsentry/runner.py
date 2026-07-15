from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from optionsentry.alerts import AlertEngine
from optionsentry.config import ConfigError
from optionsentry.data_sources.base import MarketDataSource
from optionsentry.models import AlertEvent, ConditionEvaluation, Universe
from optionsentry.monitor_state import MonitorState
from optionsentry.notifiers import Notifier
from optionsentry.strategies import CompiledStrategy, Strategy, StrategyCompilation
from optionsentry.strategy_filters import apply_strategy_filter, validate_strategy_filters


@dataclass(frozen=True)
class RunnerCycle:
    cycle_count: int
    timestamp: str
    evaluations: tuple[ConditionEvaluation, ...]
    total_conditions: int
    active_count: int
    alerts: tuple[AlertEvent, ...]
    total_alerts: int
    changed_count: int
    compute_ms: float


@dataclass
class RunnerCallbacks:
    on_status: Callable[[str], None] | None = None
    on_universe: Callable[[Universe], None] | None = None
    on_compiled: Callable[[int, int], None] | None = None
    on_cycle: Callable[[RunnerCycle], None] | None = None
    on_alert: Callable[[AlertEvent], None] | None = None


@dataclass
class AlertRunner:
    data_source: MarketDataSource
    strategies: tuple[Strategy, ...]
    alert_engine: AlertEngine
    notifier: Notifier
    logger: logging.Logger
    config_dir: str | Path = "."
    cycle_summary_interval_seconds: int = 60
    stop_requested: Callable[[], bool] | None = None
    callbacks: RunnerCallbacks = field(default_factory=RunnerCallbacks)

    def run(self) -> int:
        cycle_count = 0
        alert_count = 0
        terminal_state = MonitorState.STOPPED
        summary_cycle_count = 0
        summary_alert_count = 0
        summary_evaluation_count = 0
        summary_changed_count = 0
        summary_compute_ms = 0.0
        last_summary_at = 0.0
        try:
            validate_strategy_filters(self.strategies, self.config_dir)
            if self._should_stop():
                return 0
            self._emit_status(MonitorState.DISCOVERING)
            universe = self.data_source.discover_universe()
            if self._should_stop():
                return 0
            if not universe.options:
                self.logger.warning("Universe has no futures options to evaluate.")
                self._emit_universe(universe)
                terminal_state = MonitorState.EMPTY_UNIVERSE
                return 0

            self._emit_status(MonitorState.COMPILING)
            compiled_strategies, stream_universe = self._compile_strategies(universe)
            total_conditions = sum(strategy.condition_count for strategy in compiled_strategies)
            compiled_strategy_count = len(
                {(strategy.strategy_id, strategy.name) for strategy in compiled_strategies}
            )
            self._emit_universe(stream_universe)
            self._emit_compiled(compiled_strategy_count, total_conditions)
            if not compiled_strategies or total_conditions == 0:
                self.logger.warning("No alert conditions after strategy filters and compilation.")
                terminal_state = MonitorState.EMPTY_CONDITIONS
                return 0
            self.logger.info(
                "Compiled alert strategies: strategies=%s units=%s total_conditions=%s",
                compiled_strategy_count,
                len(compiled_strategies),
                total_conditions,
            )

            for snapshot, active_strategies, first_snapshot in self._stream_execution_batches(
                compiled_strategies,
                stream_universe,
            ):
                if self._should_stop():
                    self._emit_status(MonitorState.STOPPING)
                    break
                if first_snapshot:
                    self._emit_status(MonitorState.RUNNING)
                changed_symbols = None if first_snapshot else snapshot.changed_symbols
                started_at = time.perf_counter()
                evaluations = []
                for strategy in active_strategies:
                    evaluations.extend(strategy.evaluate(snapshot, changed_symbols))
                compute_ms = (time.perf_counter() - started_at) * 1000
                events = self.alert_engine.process(evaluations, snapshot.timestamp)
                for event in events:
                    self._notify(event)
                    self._emit_alert(event)
                    alert_count += 1
                self._flush_notifications()
                cycle_count += 1
                summary_cycle_count += 1
                summary_alert_count += len(events)
                summary_evaluation_count += len(evaluations)
                summary_changed_count += len(snapshot.changed_symbols)
                summary_compute_ms += compute_ms
                self.logger.debug(
                    (
                        "cycle=%s timestamp=%s evaluations=%s total_conditions=%s "
                        "active=%s alerts=%s changed=%s compute_ms=%.3f"
                    ),
                    cycle_count,
                    snapshot.timestamp,
                    len(evaluations),
                    total_conditions,
                    self.alert_engine.active_count(),
                    len(events),
                    len(snapshot.changed_symbols),
                    compute_ms,
                )
                now = time.monotonic()
                should_log_summary = (
                    self.cycle_summary_interval_seconds == 0
                    or last_summary_at == 0.0
                    or now - last_summary_at >= self.cycle_summary_interval_seconds
                    or bool(events)
                )
                if should_log_summary:
                    avg_evaluations = summary_evaluation_count / summary_cycle_count
                    avg_changed = summary_changed_count / summary_cycle_count
                    avg_compute_ms = summary_compute_ms / summary_cycle_count
                    self.logger.info(
                        (
                            "cycle_summary total_cycles=%s interval_cycles=%s timestamp=%s "
                            "total_conditions=%s active=%s total_alerts=%s interval_alerts=%s "
                            "avg_evaluations=%.1f avg_changed=%.1f avg_compute_ms=%.3f"
                        ),
                        cycle_count,
                        summary_cycle_count,
                        snapshot.timestamp,
                        total_conditions,
                        self.alert_engine.active_count(),
                        alert_count,
                        summary_alert_count,
                        avg_evaluations,
                        avg_changed,
                        avg_compute_ms,
                    )
                    summary_cycle_count = 0
                    summary_alert_count = 0
                    summary_evaluation_count = 0
                    summary_changed_count = 0
                    summary_compute_ms = 0.0
                    last_summary_at = now
                self._emit_cycle(
                    RunnerCycle(
                        cycle_count=cycle_count,
                        timestamp=snapshot.timestamp,
                        evaluations=tuple(evaluations),
                        total_conditions=total_conditions,
                        active_count=self.alert_engine.active_count(),
                        alerts=tuple(events),
                        total_alerts=alert_count,
                        changed_count=len(snapshot.changed_symbols),
                        compute_ms=compute_ms,
                    )
                )
                if self._should_stop():
                    self._emit_status(MonitorState.STOPPING)
                    break
        except Exception:
            terminal_state = (
                MonitorState.STOPPED
                if self._should_stop()
                else MonitorState.FAILED
            )
            raise
        finally:
            try:
                self._flush_notifications(force=True)
                self.data_source.close()
            except Exception:
                terminal_state = MonitorState.FAILED
                raise
            finally:
                self._emit_status(terminal_state)
        self.logger.info("Runner stopped: cycles=%s alerts=%s", cycle_count, alert_count)
        return alert_count

    def _compile_strategies(self, universe: Universe) -> tuple[tuple[CompiledStrategy, ...], Universe]:
        compiled_strategies: list[CompiledStrategy] = []
        active_universes: list[Universe] = []
        for strategy in self.strategies:
            filtered_universe = apply_strategy_filter(strategy, universe, self.config_dir, self.logger)
            if not filtered_universe.options:
                self.logger.warning(
                    "Skipping strategy with no options after filter: strategy=%s script=%s",
                    strategy.name,
                    getattr(strategy, "filter_script", None) or "<none>",
                )
                continue
            compilation = strategy.compile(filtered_universe)
            self._validate_compilation(strategy, compilation, filtered_universe)
            if compilation.condition_count == 0:
                self.logger.warning(
                    (
                        "Skipping strategy with no compiled conditions: strategy=%s script=%s "
                        "options=%s futures=%s price_symbols=%s"
                    ),
                    strategy.name,
                    getattr(strategy, "filter_script", None) or "<none>",
                    len(filtered_universe.options),
                    len(filtered_universe.futures),
                    len(filtered_universe.price_symbols()),
                )
                continue
            self.logger.info(
                (
                    "Strategy compiled after filter: strategy=%s script=%s conditions=%s "
                    "options=%s futures=%s price_symbols=%s"
                ),
                strategy.name,
                getattr(strategy, "filter_script", None) or "<none>",
                compilation.condition_count,
                len(filtered_universe.options),
                len(filtered_universe.futures),
                len(filtered_universe.price_symbols()),
            )
            for unit in compilation.units:
                unsupported = unit.data_requirements.unsupported_reasons()
                if unsupported:
                    raise ConfigError(
                        f"Strategy {strategy.id} requires unsupported market data: "
                        f"{'; '.join(unsupported)}"
                    )
                compiled_strategies.append(unit)
            active_universes.append(filtered_universe)
        required_symbols = {
            symbol
            for compiled in compiled_strategies
            for symbol in compiled.required_symbols
        }
        stream_universe = _merge_universes(active_universes).subset(required_symbols)
        self.logger.info(
            (
                "Monitoring universe after strategy filters: strategies=%s options=%s "
                "futures=%s price_symbols=%s"
            ),
            len(compiled_strategies),
            len(stream_universe.options),
            len(stream_universe.futures),
            len(stream_universe.price_symbols()),
        )
        return tuple(compiled_strategies), stream_universe

    def _validate_compilation(
        self,
        strategy: Strategy,
        compilation: StrategyCompilation,
        universe: Universe,
    ) -> None:
        expected = (strategy.id, strategy.type_name, strategy.name)
        actual = (
            compilation.strategy_id,
            compilation.strategy_type,
            compilation.name,
        )
        if actual != expected:
            raise ConfigError(
                "Strategy compilation metadata mismatch: "
                f"expected={expected!r} actual={actual!r}"
            )
        universe_symbols = set(universe.instruments)
        for index, unit in enumerate(compilation.units):
            unit_identity = (unit.strategy_id, unit.strategy_type, unit.name)
            if unit_identity != expected:
                raise ConfigError(
                    f"Strategy {strategy.id} execution unit {index} metadata mismatch: "
                    f"expected={expected!r} actual={unit_identity!r}"
                )
            if unit.condition_count <= 0:
                raise ConfigError(
                    f"Strategy {strategy.id} execution unit {index} must contain conditions."
                )
            if not str(unit.backtest_group).strip():
                raise ConfigError(
                    f"Strategy {strategy.id} execution unit {index} requires backtest_group."
                )
            if not unit.required_symbols:
                raise ConfigError(
                    f"Strategy {strategy.id} execution unit {index} requires symbols."
                )
            unknown_symbols = sorted(unit.required_symbols - universe_symbols)
            if unknown_symbols:
                raise ConfigError(
                    f"Strategy {strategy.id} execution unit {index} requires symbols "
                    f"outside its universe: {', '.join(unknown_symbols)}"
                )

    def _stream_execution_batches(
        self,
        compiled_strategies: tuple[CompiledStrategy, ...],
        stream_universe: Universe,
    ):
        if getattr(self.data_source, "mode", "live") != "backtest":
            first_snapshot = True
            for snapshot in self.data_source.stream(stream_universe):
                yield snapshot, compiled_strategies, first_snapshot
                first_snapshot = False
            return

        groups: dict[str, list[CompiledStrategy]] = {}
        for strategy in compiled_strategies:
            groups.setdefault(strategy.backtest_group, []).append(strategy)
        for index, group_name in enumerate(sorted(groups), start=1):
            if self._should_stop():
                return
            group_strategies = tuple(groups[group_name])
            symbols = {
                symbol
                for strategy in group_strategies
                for symbol in strategy.required_symbols
            }
            group_universe = stream_universe.subset(symbols)
            self.logger.info(
                "Starting backtest execution group %s/%s: group=%s units=%s symbols=%s",
                index,
                len(groups),
                group_name,
                len(group_strategies),
                len(symbols),
            )
            first_snapshot = True
            for snapshot in self.data_source.stream(group_universe):
                yield snapshot, group_strategies, first_snapshot
                first_snapshot = False

    def _notify(self, event: AlertEvent) -> None:
        self.logger.warning("alert key=%s message=%s", event.evaluation.key, event.evaluation.message)
        try:
            self.notifier.notify(event)
        except Exception as exc:
            self.logger.error(
                "notification failed key=%s error=%s: %s; continuing",
                event.evaluation.key,
                type(exc).__name__,
                exc,
            )

    def _flush_notifications(self, force: bool = False) -> None:
        flush = getattr(self.notifier, "flush", None)
        if flush is None:
            return
        try:
            flush(force=force)
        except Exception as exc:
            self.logger.error(
                "notification flush failed error=%s: %s; continuing",
                type(exc).__name__,
                exc,
            )

    def _should_stop(self) -> bool:
        return bool(self.stop_requested and self.stop_requested())

    def _emit_status(self, status: MonitorState | str) -> None:
        if self.callbacks.on_status is not None:
            self.callbacks.on_status(MonitorState(status).value)

    def _emit_universe(self, universe: Universe) -> None:
        if self.callbacks.on_universe is not None:
            self.callbacks.on_universe(universe)

    def _emit_compiled(self, strategy_count: int, total_conditions: int) -> None:
        if self.callbacks.on_compiled is not None:
            self.callbacks.on_compiled(strategy_count, total_conditions)

    def _emit_cycle(self, cycle: RunnerCycle) -> None:
        if self.callbacks.on_cycle is not None:
            self.callbacks.on_cycle(cycle)

    def _emit_alert(self, event: AlertEvent) -> None:
        if self.callbacks.on_alert is not None:
            self.callbacks.on_alert(event)


def _merge_universes(universes: list[Universe]) -> Universe:
    instruments = {}
    requested_symbols: set[str] = set()
    for universe in universes:
        instruments.update(universe.instruments)
        requested_symbols.update(universe.requested_symbols)
    return Universe(instruments=instruments, requested_symbols=tuple(sorted(requested_symbols)))
