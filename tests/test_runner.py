from __future__ import annotations

import logging
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from optionsentry.alerts import AlertEngine
from optionsentry.config import ConfigError
from optionsentry.models import AlertEvent, InstrumentMeta, MarketSnapshot, Universe
from optionsentry.runner import AlertRunner, RunnerCallbacks
from optionsentry.strategy_base import (
    CompiledStrategy,
    DataRequirements,
    Strategy,
    StrategyCompilation,
)
from optionsentry.strategies import CPComboStrategy
from tests.helpers import sample_universe, snapshot


@dataclass
class FakeDataSource:
    universe: Universe
    snapshots: tuple[MarketSnapshot, ...]
    closed: bool = False
    stream_universe: Universe | None = None
    stream_calls: int = 0
    discover_calls: int = 0

    def discover_universe(self) -> Universe:
        self.discover_calls += 1
        return self.universe

    def stream(self, universe: Universe) -> Iterator[MarketSnapshot]:
        self.stream_universe = universe
        self.stream_calls += 1
        yield from self.snapshots

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeBacktestDataSource:
    universe: Universe
    mode: str = "backtest"
    stream_universes: list[Universe] = field(default_factory=list)
    closed: bool = False

    def discover_universe(self) -> Universe:
        return self.universe

    def stream(self, universe: Universe) -> Iterator[MarketSnapshot]:
        self.stream_universes.append(universe)
        return
        yield

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
    def test_backtest_streams_exact_execution_groups(self) -> None:
        base = sample_universe()
        instruments = dict(base.instruments)
        instruments.update(
            {
                "DCE.m2609": InstrumentMeta("DCE.m2609", "FUTURE"),
                "DCE.m2609C3000": InstrumentMeta(
                    "DCE.m2609C3000",
                    "OPTION",
                    underlying_symbol="DCE.m2609",
                    strike_price=3000.0,
                    option_class="CALL",
                    exercise_year=2026,
                    exercise_month=9,
                ),
                "DCE.m2609P3000": InstrumentMeta(
                    "DCE.m2609P3000",
                    "OPTION",
                    underlying_symbol="DCE.m2609",
                    strike_price=3000.0,
                    option_class="PUT",
                    exercise_year=2026,
                    exercise_month=9,
                ),
            }
        )
        data_source = FakeBacktestDataSource(Universe(instruments=instruments))
        runner = AlertRunner(
            data_source=data_source,
            strategies=(CPComboStrategy(min_value=0.01, max_value=float("inf")),),
            alert_engine=AlertEngine(),
            notifier=CapturingNotifier([]),
            logger=_logger("tests.runner.backtest_groups"),
        )

        runner.run()

        self.assertEqual(len(data_source.stream_universes), 2)
        grouped_options = {
            frozenset(option.symbol for option in universe.options)
            for universe in data_source.stream_universes
        }
        self.assertEqual(
            grouped_options,
            {
                frozenset(
                    {
                        "SHFE.AU2608C600",
                        "SHFE.AU2608P600",
                        "SHFE.AU2608C620",
                        "SHFE.AU2608P620",
                    }
                ),
                frozenset({"DCE.M2609C3000", "DCE.M2609P3000"}),
            },
        )
        self.assertTrue(
            all(len(universe.futures) == 1 for universe in data_source.stream_universes)
        )
        self.assertTrue(data_source.closed)

    def test_runner_rejects_unsupported_strategy_data_requirements(self) -> None:
        universe = sample_universe()

        class UnsupportedUnit(CompiledStrategy):
            strategy_id = "unsupported"
            strategy_type = "unsupported"
            name = "不支持的数据"
            backtest_group = "test"
            data_requirements = DataRequirements(
                quote_fields=frozenset({"bid_price1"})
            )

            @property
            def condition_count(self) -> int:
                return 1

            @property
            def required_symbols(self) -> frozenset[str]:
                return frozenset({"SHFE.AU2608"})

            def evaluate(self, snapshot, changed_symbols=None):
                return []

        class UnsupportedStrategy(Strategy):
            type_name = "unsupported"
            id = "unsupported"
            name = "不支持的数据"

            def compile(self, universe: Universe) -> StrategyCompilation:
                return StrategyCompilation(
                    strategy_id=self.id,
                    strategy_type=self.type_name,
                    name=self.name,
                    units=(UnsupportedUnit(),),
                )

        data_source = FakeDataSource(universe, ())
        runner = AlertRunner(
            data_source=data_source,
            strategies=(UnsupportedStrategy(),),
            alert_engine=AlertEngine(),
            notifier=CapturingNotifier([]),
            logger=_logger("tests.runner.data_requirements"),
        )

        with self.assertRaisesRegex(
            ConfigError,
            "requires unsupported market data: quote fields: bid_price1",
        ):
            runner.run()

        self.assertTrue(data_source.closed)

    def test_runner_rejects_invalid_compilation_metadata(self) -> None:
        universe = sample_universe()

        class InvalidCompilationStrategy(Strategy):
            type_name = "invalid_compilation"
            id = "invalid_compilation"
            name = "无效编译"

            def compile(self, universe: Universe) -> StrategyCompilation:
                return StrategyCompilation(
                    strategy_id="wrong_id",
                    strategy_type=self.type_name,
                    name=self.name,
                    units=(),
                )

        data_source = FakeDataSource(universe, ())
        runner = AlertRunner(
            data_source=data_source,
            strategies=(InvalidCompilationStrategy(),),
            alert_engine=AlertEngine(),
            notifier=CapturingNotifier([]),
            logger=_logger("tests.runner.invalid_compilation"),
        )

        with self.assertRaisesRegex(
            ConfigError,
            "Strategy compilation metadata mismatch",
        ):
            runner.run()

        self.assertTrue(data_source.closed)

    def test_runner_validates_filter_scripts_before_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_source = FakeDataSource(sample_universe(), ())
            runner = AlertRunner(
                data_source=data_source,
                strategies=(
                    CPComboStrategy(
                        min_value=0.01,
                        max_value=float("inf"),
                        filter_script="missing.py",
                    ),
                ),
                alert_engine=AlertEngine(),
                notifier=CapturingNotifier([]),
                logger=_logger("tests.runner.filter_validation"),
                config_dir=tmpdir,
            )

            with self.assertRaisesRegex(ConfigError, "script not found"):
                runner.run()

            self.assertEqual(data_source.discover_calls, 0)
            self.assertTrue(data_source.closed)

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
            handler = CapturingLogHandler()
            logger = _logger("tests.runner.filtered_union")
            logger.handlers = [handler]
            logger.setLevel(logging.INFO)
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
                logger=logger,
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
            self.assertTrue(any("Strategy compiled after filter: strategy=strike_600" in message for message in handler.messages))
            self.assertTrue(any("Strategy compiled after filter: strategy=strike_620" in message for message in handler.messages))
            self.assertTrue(any(
                "Monitoring universe after strategy filters: strategies=2 options=4 futures=1 price_symbols=5" in message
                for message in handler.messages
            ))

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
