from __future__ import annotations

import logging
import unittest
from dataclasses import dataclass
from typing import Iterator

from optionsentry.alerts import AlertEngine
from optionsentry.models import AlertEvent, MarketSnapshot, Universe
from optionsentry.runner import AlertRunner, RunnerCallbacks
from optionsentry.strategies import CPComboStrategy
from tests.helpers import sample_universe, snapshot


@dataclass
class _FakeDataSource:
    universe: Universe
    snapshots: tuple[MarketSnapshot, ...]
    closed: bool = False

    def discover_universe(self) -> Universe:
        return self.universe

    def stream(self, universe: Universe) -> Iterator[MarketSnapshot]:
        yield from self.snapshots

    def close(self) -> None:
        self.closed = True


@dataclass
class _Notifier:
    events: list[AlertEvent]

    def notify(self, event: AlertEvent) -> None:
        self.events.append(event)


class GuiRunnerAdapterTests(unittest.TestCase):
    def test_runner_emits_gui_callbacks(self) -> None:
        universe = sample_universe()
        snap = snapshot(
            universe,
            {
                "SHFE.au2608": 590.0,
                "SHFE.au2608C600": 12.0,
                "SHFE.au2608P600": 1.0,
            },
            timestamp="t1",
        )
        notifier = _Notifier([])
        statuses: list[str] = []
        compiled: list[tuple[int, int]] = []
        cycles = []
        alerts: list[AlertEvent] = []
        runner = AlertRunner(
            data_source=_FakeDataSource(universe, (snap,)),
            strategies=(CPComboStrategy(threshold=0.01),),
            alert_engine=AlertEngine(alert_on_first_match=True),
            notifier=notifier,
            logger=_logger("tests.gui.callbacks"),
            callbacks=RunnerCallbacks(
                on_status=statuses.append,
                on_compiled=lambda count, total: compiled.append((count, total)),
                on_cycle=cycles.append,
                on_alert=alerts.append,
            ),
        )

        alert_count = runner.run()

        self.assertEqual(alert_count, 1)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(len(cycles), 1)
        self.assertEqual(compiled[0][0], 1)
        self.assertIn("discovering", statuses)
        self.assertEqual(statuses[-1], "stopped")

    def test_runner_stop_callback_breaks_after_cycle(self) -> None:
        universe = sample_universe()
        first = snapshot(
            universe,
            {
                "SHFE.au2608": 590.0,
                "SHFE.au2608C600": 12.0,
                "SHFE.au2608P600": 1.0,
            },
            timestamp="t1",
        )
        second = snapshot(
            universe,
            {
                "SHFE.au2608": 580.0,
                "SHFE.au2608C600": 20.0,
                "SHFE.au2608P600": 1.0,
            },
            timestamp="t2",
        )
        stop = False
        cycles = []

        def on_cycle(cycle: object) -> None:
            nonlocal stop
            cycles.append(cycle)
            stop = True

        runner = AlertRunner(
            data_source=_FakeDataSource(universe, (first, second)),
            strategies=(CPComboStrategy(threshold=0.01),),
            alert_engine=AlertEngine(alert_on_first_match=True),
            notifier=_Notifier([]),
            logger=_logger("tests.gui.stop"),
            stop_requested=lambda: stop,
            callbacks=RunnerCallbacks(on_cycle=on_cycle),
        )

        runner.run()

        self.assertEqual(len(cycles), 1)


def _logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return logger


if __name__ == "__main__":
    unittest.main()
