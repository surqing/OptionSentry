from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from optionsentry.config import ConfigError
from optionsentry.strategy_filters import apply_strategy_filter
from optionsentry.strategies import CPComboStrategy
from tests.helpers import sample_universe


class StrategyFilterTests(unittest.TestCase):
    def test_accept_filters_only_options_and_adds_underlying_future(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            filters_dir = config_dir / "filters"
            filters_dir.mkdir()
            (filters_dir / "gold.py").write_text(
                "def accept(option, ctx):\n"
                "    if not option.is_option:\n"
                "        raise AssertionError('expected only options')\n"
                "    future = ctx.underlying(option)\n"
                "    return future is not None and option.strike_price == 600\n",
                encoding="utf-8",
            )
            strategy = CPComboStrategy(
                min_value=0.01,
                max_value=float("inf"),
                name="filtered",
                filter_script="filters/gold.py",
            )

            filtered = apply_strategy_filter(strategy, sample_universe(), config_dir, _logger())

            self.assertEqual({option.symbol for option in filtered.options}, {"SHFE.AU2608C600", "SHFE.AU2608P600"})
            self.assertEqual({future.symbol for future in filtered.futures}, {"SHFE.AU2608"})

    def test_filter_returns_universe_unchanged_when_no_script_is_set(self) -> None:
        universe = sample_universe()
        strategy = CPComboStrategy(min_value=0.01, max_value=float("inf"), name="plain")

        filtered = apply_strategy_filter(strategy, universe, ".", _logger())

        self.assertIs(filtered, universe)

    def test_filter_rejects_missing_function_non_bool_and_runtime_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            script = config_dir / "bad.py"
            strategy = CPComboStrategy(
                min_value=0.01,
                max_value=float("inf"),
                name="bad",
                filter_script="bad.py",
            )

            script.write_text("def other(option, ctx):\n    return True\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "function not found"):
                apply_strategy_filter(strategy, sample_universe(), config_dir, _logger())

            script.write_text("def accept(option, ctx):\n    return 'yes'\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "expected bool"):
                apply_strategy_filter(strategy, sample_universe(), config_dir, _logger())

            script.write_text("def accept(option, ctx):\n    raise RuntimeError('boom')\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "RuntimeError"):
                apply_strategy_filter(strategy, sample_universe(), config_dir, _logger())

    def test_filter_rejects_missing_script_and_import_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            strategy = CPComboStrategy(
                min_value=0.01,
                max_value=float("inf"),
                name="bad",
                filter_script="missing.py",
            )

            with self.assertRaisesRegex(ConfigError, "script not found"):
                apply_strategy_filter(strategy, sample_universe(), config_dir, _logger())

            script = config_dir / "missing.py"
            script.write_text("raise RuntimeError('import boom')\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "import failed"):
                apply_strategy_filter(strategy, sample_universe(), config_dir, _logger())


def _logger() -> logging.Logger:
    logger = logging.getLogger("tests.strategy_filters")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return logger


if __name__ == "__main__":
    unittest.main()
