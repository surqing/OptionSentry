from __future__ import annotations

import logging
import unittest
from dataclasses import dataclass
from typing import Iterator

from kuaiqi.alerts import AlertEngine
from kuaiqi.models import AlertEvent, MarketSnapshot, Universe
from kuaiqi.runner import AlertRunner
from kuaiqi.strategies import CPComboStrategy
from tests.helpers import sample_universe, snapshot


@dataclass
class FakeDataSource:
    universe: Universe
    snapshots: tuple[MarketSnapshot, ...]

    def discover_universe(self) -> Universe:
        return self.universe

    def stream(self, universe: Universe) -> Iterator[MarketSnapshot]:
        yield from self.snapshots

    def close(self) -> None:
        return None


@dataclass
class CapturingNotifier:
    events: list[AlertEvent]

    def notify(self, event: AlertEvent) -> None:
        self.events.append(event)


class FailingNotifier:
    def notify(self, event: AlertEvent) -> None:
        raise RuntimeError("notification backend down")


class RunnerTests(unittest.TestCase):
    def test_runner_generates_crossing_alerts_from_fake_source(self) -> None:
        universe = sample_universe()
        first = snapshot(
            universe,
            {
                "SHFE.au2608": 600.0,
                "SHFE.au2608C600": 5.0,
                "SHFE.au2608P600": 5.0,
            },
            timestamp="t1",
        )
        second = snapshot(
            universe,
            {
                "SHFE.au2608": 590.0,
                "SHFE.au2608C600": 12.0,
                "SHFE.au2608P600": 1.0,
            },
            timestamp="t2",
        )
        notifier = CapturingNotifier([])
        logger = logging.getLogger("tests.runner")
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        runner = AlertRunner(
            data_source=FakeDataSource(universe, (first, second)),
            strategies=(CPComboStrategy(threshold=0.01),),
            alert_engine=AlertEngine(),
            notifier=notifier,
            logger=logger,
        )

        alert_count = runner.run()

        self.assertEqual(alert_count, 1)
        self.assertEqual(len(notifier.events), 1)
        self.assertEqual(notifier.events[0].timestamp, "t2")

    def test_runner_continues_when_notification_fails(self) -> None:
        universe = sample_universe()
        first = snapshot(
            universe,
            {
                "SHFE.au2608": 600.0,
                "SHFE.au2608C600": 5.0,
                "SHFE.au2608P600": 5.0,
            },
            timestamp="t1",
        )
        second = snapshot(
            universe,
            {
                "SHFE.au2608": 590.0,
                "SHFE.au2608C600": 12.0,
                "SHFE.au2608P600": 1.0,
            },
            timestamp="t2",
        )
        logger = logging.getLogger("tests.runner.notification_failure")
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        runner = AlertRunner(
            data_source=FakeDataSource(universe, (first, second)),
            strategies=(CPComboStrategy(threshold=0.01),),
            alert_engine=AlertEngine(),
            notifier=FailingNotifier(),
            logger=logger,
        )

        alert_count = runner.run()

        self.assertEqual(alert_count, 1)


if __name__ == "__main__":
    unittest.main()
