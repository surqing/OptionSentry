from __future__ import annotations

import logging
import unittest
from dataclasses import dataclass
from typing import Iterator

from optionsentry.alerts import AlertEngine
from optionsentry.models import AlertEvent, MarketSnapshot, Universe
from optionsentry.runner import AlertRunner
from optionsentry.strategies import CPComboStrategy
from tests.helpers import sample_universe, snapshot


@dataclass
class FakeDataSource:
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
class CapturingNotifier:
    events: list[AlertEvent]

    def notify(self, event: AlertEvent) -> None:
        self.events.append(event)


@dataclass
class FlushTrackingNotifier:
    events: list[AlertEvent]
    flush_calls: int = 0
    force_flush_calls: int = 0

    def notify(self, event: AlertEvent) -> None:
        self.events.append(event)

    def flush(self, force: bool = False) -> None:
        self.flush_calls += 1
        if force:
            self.force_flush_calls += 1


class FailingNotifier:
    def notify(self, event: AlertEvent) -> None:
        raise RuntimeError("notification backend down")


class CapturingLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class RunnerTests(unittest.TestCase):
    def test_runner_closes_data_source_when_universe_is_empty(self) -> None:
        data_source = FakeDataSource(Universe(instruments={}), ())
        logger = logging.getLogger("tests.runner.empty")
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        runner = AlertRunner(
            data_source=data_source,
            strategies=(CPComboStrategy(threshold=0.01),),
            alert_engine=AlertEngine(),
            notifier=CapturingNotifier([]),
            logger=logger,
        )

        alert_count = runner.run()

        self.assertEqual(alert_count, 0)
        self.assertTrue(data_source.closed)

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

    def test_runner_flushes_notifications_each_cycle_and_on_stop(self) -> None:
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
        notifier = FlushTrackingNotifier([])
        logger = logging.getLogger("tests.runner.flush")
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
        self.assertEqual(notifier.flush_calls, 3)
        self.assertEqual(notifier.force_flush_calls, 1)

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

    def test_runner_throttles_info_cycle_summaries(self) -> None:
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
                "SHFE.au2608": 600.0,
                "SHFE.au2608C600": 5.0,
                "SHFE.au2608P600": 5.0,
            },
            timestamp="t2",
        )
        handler = CapturingLogHandler()
        logger = logging.getLogger("tests.runner.log_throttle")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False
        runner = AlertRunner(
            data_source=FakeDataSource(universe, (first, second)),
            strategies=(CPComboStrategy(threshold=1000.0),),
            alert_engine=AlertEngine(),
            notifier=CapturingNotifier([]),
            logger=logger,
            cycle_summary_interval_seconds=3600,
        )

        runner.run()

        summaries = [message for message in handler.messages if message.startswith("cycle_summary")]
        per_cycle_infos = [message for message in handler.messages if message.startswith("cycle=")]
        self.assertEqual(len(summaries), 1)
        self.assertEqual(per_cycle_infos, [])


if __name__ == "__main__":
    unittest.main()
