from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from optionsentry.alerts import AlertEngine
from optionsentry.data_sources.base import MarketDataSource
from optionsentry.models import AlertEvent, ConditionEvaluation, Universe
from optionsentry.notifiers import Notifier
from optionsentry.strategies import CompiledStrategy, Strategy
from optionsentry.strategy_filters import apply_strategy_filter


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
        summary_cycle_count = 0
        summary_alert_count = 0
        summary_evaluation_count = 0
        summary_changed_count = 0
        summary_compute_ms = 0.0
        last_summary_at = 0.0
        try:
            self._emit_status("discovering")
            universe = self.data_source.discover_universe()
            if not universe.options:
                self.logger.warning("Universe has no futures options to evaluate.")
                self._emit_universe(universe)
                self._emit_status("empty_universe")
                return 0

            self._emit_status("compiling")
            compiled_strategies, stream_universe = self._compile_strategies(universe)
            total_conditions = sum(strategy.condition_count for strategy in compiled_strategies)
            self._emit_universe(stream_universe)
            self._emit_compiled(len(compiled_strategies), total_conditions)
            if not compiled_strategies or total_conditions == 0:
                self.logger.warning("No alert conditions after strategy filters and compilation.")
                self._emit_status("empty_conditions")
                return 0
            self.logger.info(
                "Compiled alert strategies: strategies=%s total_conditions=%s",
                len(compiled_strategies),
                total_conditions,
            )

            initialized = False
            for snapshot in self.data_source.stream(stream_universe):
                if self._should_stop():
                    self._emit_status("stopping")
                    break
                changed_symbols = None if not initialized else snapshot.changed_symbols
                started_at = time.perf_counter()
                evaluations = []
                for strategy in compiled_strategies:
                    evaluations.extend(strategy.evaluate(snapshot, changed_symbols))
                compute_ms = (time.perf_counter() - started_at) * 1000
                events = self.alert_engine.process(evaluations, snapshot.timestamp)
                for event in events:
                    self._notify(event)
                    self._emit_alert(event)
                    alert_count += 1
                self._flush_notifications()
                cycle_count += 1
                initialized = True

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
                    self._emit_status("stopping")
                    break
        finally:
            self._flush_notifications(force=True)
            self.data_source.close()
            self._emit_status("stopped")
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
            compiled = strategy.compile(filtered_universe)
            if compiled.condition_count == 0:
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
                compiled.condition_count,
                len(filtered_universe.options),
                len(filtered_universe.futures),
                len(filtered_universe.price_symbols()),
            )
            compiled_strategies.append(compiled)
            active_universes.append(filtered_universe)
        stream_universe = _merge_universes(active_universes)
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

    def _emit_status(self, status: str) -> None:
        if self.callbacks.on_status is not None:
            self.callbacks.on_status(status)

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
