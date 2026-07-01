from __future__ import annotations

import math
import unittest

from optionsentry.config import StrategyConfig, strategy_display_name
from optionsentry.strategies import AbsSpreadStrategy, CPComboStrategy
from optionsentry.strategies import build_strategy
from tests.helpers import sample_universe, snapshot


class StrategyTests(unittest.TestCase):
    def test_strategy_display_name_defaults_to_chinese_label(self) -> None:
        cp_config = StrategyConfig(type="cp_combo", threshold=0.01)
        spread_config = StrategyConfig(type="abs_spread", threshold=0.1)

        self.assertEqual(strategy_display_name(cp_config), "CP组合预警")
        self.assertEqual(strategy_display_name(spread_config), "价差预警")
        self.assertEqual(build_strategy(cp_config).name, "CP组合预警")
        self.assertEqual(build_strategy(spread_config).name, "价差预警")

    def test_strategy_display_name_preserves_explicit_name(self) -> None:
        config = StrategyConfig(type="cp_combo", threshold=0.01, name="custom")

        self.assertEqual(strategy_display_name(config), "custom")
        self.assertEqual(build_strategy(config).name, "custom")

    def test_cp_combo_uses_absolute_threshold(self) -> None:
        universe = sample_universe()
        snap = snapshot(
            universe,
            {
                "SHFE.au2608": 590.0,
                "SHFE.au2608C600": 12.0,
                "SHFE.au2608P600": 1.0,
            },
        )

        evaluations = CPComboStrategy(threshold=0.01).evaluate(snap, universe)

        active = [item for item in evaluations if item.active]
        self.assertEqual(len(active), 1)
        self.assertAlmostEqual(active[0].value, (12.0 - 1.0 + 600.0 - 590.0) / 590.0)

    def test_cp_combo_preserves_value_sign_for_negative_deviation(self) -> None:
        universe = sample_universe()
        snap = snapshot(
            universe,
            {
                "SHFE.au2608": 590.0,
                "SHFE.au2608C600": 1.0,
                "SHFE.au2608P600": 20.0,
            },
        )

        evaluations = CPComboStrategy(threshold=0.01).evaluate(snap, universe)

        active = [item for item in evaluations if item.active]
        self.assertEqual(len(active), 1)
        self.assertLess(active[0].value, -0.01)
        self.assertAlmostEqual(active[0].value, (1.0 - 20.0 + 600.0 - 590.0) / 590.0)

    def test_cp_combo_skips_invalid_future_price(self) -> None:
        universe = sample_universe()
        snap = snapshot(
            universe,
            {
                "SHFE.au2608": 0.0,
                "SHFE.au2608C600": 12.0,
                "SHFE.au2608P600": 1.0,
            },
        )

        evaluations = CPComboStrategy(threshold=0.01).evaluate(snap, universe)

        self.assertEqual(evaluations, [])

    def test_cp_combo_skips_nan_option_price(self) -> None:
        universe = sample_universe()
        snap = snapshot(
            universe,
            {
                "SHFE.au2608": 590.0,
                "SHFE.au2608C600": math.nan,
                "SHFE.au2608P600": 1.0,
            },
        )

        evaluations = CPComboStrategy(threshold=0.01).evaluate(snap, universe)

        self.assertEqual(evaluations, [])

    def test_abs_spread_uses_absolute_strike_distance(self) -> None:
        universe = sample_universe()
        snap = snapshot(
            universe,
            {
                "SHFE.au2608C600": 11.0,
                "SHFE.au2608C620": 10.0,
                "SHFE.au2608P600": 3.0,
                "SHFE.au2608P620": 2.0,
            },
        )

        evaluations = AbsSpreadStrategy(threshold=0.1).evaluate(snap, universe)

        self.assertEqual(len(evaluations), 2)
        self.assertTrue(all(item.active for item in evaluations))
        self.assertTrue(all(abs(item.value - 0.05) < 1e-9 for item in evaluations))


if __name__ == "__main__":
    unittest.main()
