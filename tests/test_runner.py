from __future__ import annotations

import logging
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from optionsentry.alerts import AlertEngine
from optionsentry.models import AlertEvent, MarketSnapshot, Universe
from optionsentry.runner import AlertRunner, RunnerCallbacks
from optionsentry.strategies import CPComboStrategy
from tests.helpers import sample_universe, snapshot


@dataclass
class FakeDataSource:
    universe: Universe
    snapshots: tuple[MarketSnapshot, ...]
    closed: bool = False
    stream_universe: Universe | None = None
    stream_calls: int = 0

    def discover_universe(self) -> Universe:
        return self.universe

    def stream(self, universe: Universe) -> Iterator[MarketSnapshot]:
        self.stream_universe = universe
        self.stream_calls += 1
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
            strategies=(CPComboStrategy(min_value=0.01, max_value=float("inf")),),
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
            strategies=(CPComboStrategy(min_value=0.01, max_value=float("inf")),),
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
            strategies=(CPComboStrategy(min_value=0.01, max_value=float("inf")),),
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
            strategies=(CPComboStrategy(min_value=0.01, max_value=float("inf")),),
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
            strategies=(CPComboStrategy(min_value=1000.0, max_value=float("inf")),),
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

    def test_runner_uses_union_of_strategy_filtered_universes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            (config_dir / "strike_600.py").write_text(
                "def accept(option, ctx):\n    return option.strike_price == 600\n",
                encoding="utf-8",
            )
            (config_dir / "strike_620.py").write_text(
                "def accept(option, ctx):\n    return option.strike_price == 620\n",
                encoding="utf-8",
            )
            universe = sample_universe()
            data_source = FakeDataSource(universe, ())
            compiled: list[tuple[int, int]] = []
            runner = AlertRunner(
                data_source=data_source,
                strategies=(
                    CPComboStrategy(
                        min_value=0.01,
                        max_value=float("inf"),
                        name="strike_600",
                        filter_script="strike_600.py",
                    ),
                    CPComboStrategy(
                        min_value=0.01,
                        max_value=float("inf"),
                        name="strike_620",
                        filter_script="strike_620.py",
                    ),
                ),
                alert_engine=AlertEngine(),
                notifier=CapturingNotifier([]),
                logger=_logger("tests.runner.filtered_union"),
                config_dir=config_dir,
                callbacks=RunnerCallbacks(on_compiled=lambda count, total: compiled.append((count, total))),
            )

            runner.run()

            self.assertEqual(compiled, [(2, 2)])
            self.assertIsNotNone(data_source.stream_universe)
            self.assertEqual({option.symbol for option in data_source.stream_universe.options}, {
                "SHFE.AU2608C600",
                "SHFE.AU2608P600",
                "SHFE.AU2608C620",
                "SHFE.AU2608P620",
            })
            self.assertEqual({future.symbol for future in data_source.stream_universe.futures}, {"SHFE.AU2608"})

    def test_runner_skips_empty_strategy_and_continues_with_valid_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            (config_dir / "none.py").write_text("def accept(option, ctx):\n    return False\n", encoding="utf-8")
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
            notifier = CapturingNotifier([])
            compiled: list[tuple[int, int]] = []
            runner = AlertRunner(
                data_source=FakeDataSource(universe, (first,)),
                strategies=(
                    CPComboStrategy(
                        min_value=0.01,
                        max_value=float("inf"),
                        name="empty",
                        filter_script="none.py",
                    ),
                    CPComboStrategy(min_value=0.01, max_value=float("inf"), name="valid"),
                ),
                alert_engine=AlertEngine(alert_on_first_match=True),
                notifier=notifier,
                logger=_logger("tests.runner.skip_empty"),
                config_dir=config_dir,
                callbacks=RunnerCallbacks(on_compiled=lambda count, total: compiled.append((count, total))),
            )

            alert_count = runner.run()

            self.assertEqual(alert_count, 1)
            self.assertEqual(compiled, [(1, 2)])
            self.assertEqual(len(notifier.events), 1)

    def test_runner_does_not_stream_when_all_strategies_compile_zero_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            (config_dir / "calls.py").write_text(
                "def accept(option, ctx):\n    return option.option_class == 'CALL'\n",
                encoding="utf-8",
            )
            universe = sample_universe()
            data_source = FakeDataSource(universe, ())
            statuses: list[str] = []
            compiled: list[tuple[int, int]] = []
            runner = AlertRunner(
                data_source=data_source,
                strategies=(
                    CPComboStrategy(
                        min_value=0.01,
                        max_value=float("inf"),
                        name="calls_only",
                        filter_script="calls.py",
                    ),
                ),
                alert_engine=AlertEngine(),
                notifier=CapturingNotifier([]),
                logger=_logger("tests.runner.zero_conditions"),
                config_dir=config_dir,
                callbacks=RunnerCallbacks(
                    on_status=statuses.append,
                    on_compiled=lambda count, total: compiled.append((count, total)),
                ),
            )

            alert_count = runner.run()

            self.assertEqual(alert_count, 0)
            self.assertEqual(data_source.stream_calls, 0)
            self.assertEqual(compiled, [(0, 0)])
            self.assertIn("empty_conditions", statuses)


def _logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return logger


if __name__ == "__main__":
    unittest.main()
