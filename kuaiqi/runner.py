from __future__ import annotations

import logging
from dataclasses import dataclass

from kuaiqi.alerts import AlertEngine
from kuaiqi.data_sources.base import MarketDataSource
from kuaiqi.models import AlertEvent
from kuaiqi.notifiers import Notifier
from kuaiqi.strategies import Strategy


@dataclass
class AlertRunner:
    data_source: MarketDataSource
    strategies: tuple[Strategy, ...]
    alert_engine: AlertEngine
    notifier: Notifier
    logger: logging.Logger

    def run(self) -> int:
        universe = self.data_source.discover_universe()
        if not universe.options:
            self.logger.warning("Universe has no futures options to evaluate.")
            return 0

        cycle_count = 0
        alert_count = 0
        try:
            for snapshot in self.data_source.stream(universe):
                evaluations = []
                for strategy in self.strategies:
                    evaluations.extend(strategy.evaluate(snapshot, snapshot.universe))
                events = self.alert_engine.process(evaluations, snapshot.timestamp)
                for event in events:
                    self._notify(event)
                    alert_count += 1
                cycle_count += 1
                active_count = sum(1 for evaluation in evaluations if evaluation.active)
                self.logger.info(
                    "cycle=%s timestamp=%s evaluations=%s active=%s alerts=%s changed=%s",
                    cycle_count,
                    snapshot.timestamp,
                    len(evaluations),
                    active_count,
                    len(events),
                    len(snapshot.changed_symbols),
                )
        finally:
            self.data_source.close()
        self.logger.info("Runner stopped: cycles=%s alerts=%s", cycle_count, alert_count)
        return alert_count

    def _notify(self, event: AlertEvent) -> None:
        self.logger.warning("alert key=%s message=%s", event.evaluation.key, event.evaluation.message)
        try:
            self.notifier.notify(event)
        except Exception:
            self.logger.exception("notification failed key=%s; continuing", event.evaluation.key)
