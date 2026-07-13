from __future__ import annotations

import math
import unittest

from optionsentry.config import StrategyConfig, parse_config, strategy_display_name
from optionsentry.models import InstrumentMeta, Universe
from optionsentry.strategies import (
    CALL_MONEYNESS_METRIC,
    PUT_MONEYNESS_METRIC,
    SPREAD_A_MONEYNESS_METRIC,
    SPREAD_AVG_MONEYNESS_METRIC,
    SPREAD_B_MONEYNESS_METRIC,
    AbsSpreadStrategy,
    CPComboStrategy,
)
from optionsentry.strategies import build_strategy
from tests.helpers import sample_universe, snapshot


class StrategyTests(unittest.TestCase):
    def test_abs_spread_structured_strikes_match_symbol_tail_used_by_legacy_email(self) -> None:
        universe = Universe(
            instruments={
                "SHFE.au2608": InstrumentMeta("SHFE.au2608", "FUTURE"),
                "SHFE.au2608C600.0": InstrumentMeta(
                    "SHFE.au2608C600.0",
                    "OPTION",
                    underlying_symbol="SHFE.au2608",
                    strike_price=600.0,
                    option_class="CALL",
                    exercise_year=2026,
                    exercise_month=8,
                ),
                "SHFE.au2608C620.0": InstrumentMeta(
                    "SHFE.au2608C620.0",
                    "OPTION",
                    underlying_symbol="SHFE.au2608",
                    strike_price=620.0,
                    option_class="CALL",
                    exercise_year=2026,
                    exercise_month=8,
                ),
            }
        )
        snap = snapshot(
            universe,
            {
                "SHFE.au2608": 610.0,
                "SHFE.au2608C600.0": 11.0,
                "SHFE.au2608C620.0": 10.0,
            },
        )

        evaluation = AbsSpreadStrategy(min_value=float("-inf"), max_value=0.1).evaluate(
            snap,
            universe,
        )[0]

        self.assertEqual(evaluation.fields["first_strike"], "600.0")
        self.assertEqual(evaluation.fields["second_strike"], "620.0")

    def test_strategy_display_name_defaults_to_chinese_label(self) -> None:
        cp_config = StrategyConfig(type="cp_combo", min_value=0.01, max_value=float("inf"))
        spread_config = StrategyConfig(type="abs_spread", min_value=float("-inf"), max_value=0.1)

        self.assertEqual(strategy_display_name(cp_config), "CP组合预警")
        self.assertEqual(strategy_display_name(spread_config), "价差预警")
        self.assertEqual(build_strategy(cp_config).name, "CP组合预警")
        self.assertEqual(build_strategy(spread_config).name, "价差预警")

    def test_strategy_display_name_preserves_explicit_name(self) -> None:
        config = StrategyConfig(type="cp_combo", min_value=0.01, max_value=float("inf"), name="custom")

        self.assertEqual(strategy_display_name(config), "custom")
        self.assertEqual(build_strategy(config).name, "custom")

    def test_strategy_filter_config_defaults_and_builds_strategy(self) -> None:
        parsed = parse_config(
            {
                "strategies": [
                    {
                        "type": "cp_combo",
                        "min_value": 0.01,
                        "max_value": float("inf"),
                        "filter_script": "filters/gold.py",
                    }
                ]
            }
        )

        strategy_config = parsed.strategies[0]
        strategy = build_strategy(strategy_config)

        self.assertEqual(strategy_config.filter_script, "filters/gold.py")
        self.assertEqual(strategy_config.filter_function, "accept")
        self.assertEqual(strategy_config.filter_scope, "options")
        self.assertEqual(strategy.filter_script, "filters/gold.py")
        self.assertEqual(strategy.filter_function, "accept")
        self.assertEqual(strategy.filter_scope, "options")

    def test_strategy_filter_scope_only_supports_options(self) -> None:
        with self.assertRaisesRegex(ValueError, "filter_scope"):
            parse_config(
                {
                    "strategies": [
                        {
                            "type": "cp_combo",
                            "min_value": 0.01,
                            "max_value": float("inf"),
                            "filter_script": "filters/gold.py",
                            "filter_scope": "all",
                        }
                    ]
                }
            )

    def test_cp_combo_uses_positive_warning_range(self) -> None:
        universe = sample_universe()
        snap = snapshot(
            universe,
            {
                "SHFE.au2608": 590.0,
                "SHFE.au2608C600": 12.0,
                "SHFE.au2608P600": 1.0,
            },
        )

        evaluations = CPComboStrategy(min_value=0.01, max_value=float("inf")).evaluate(snap, universe)

        active = [item for item in evaluations if item.active]
        self.assertEqual(len(active), 1)
        self.assertEqual(
            active[0].key,
            "cp_combo:SHFE.AU2608:2026-8:K=600:SHFE.AU2608C600:"
            "SHFE.AU2608P600:R=0.01..inf",
        )
        self.assertEqual(active[0].strategy_type, "cp_combo")
        self.assertEqual(
            active[0].fields,
            {
                "underlying": "SHFE.AU2608",
                "expiry": "2026-8",
                "strike": "600",
                "call_symbol": "SHFE.AU2608C600",
                "put_symbol": "SHFE.AU2608P600",
            },
        )
        self.assertEqual(
            active[0].message,
            "cp_combo SHFE.AU2608:2026-8 K=600 value=0.03559322 range=(0.01, inf) "
            "symbols=SHFE.AU2608C600,SHFE.AU2608P600,SHFE.AU2608",
        )
        self.assertAlmostEqual(active[0].value, (12.0 - 1.0 + 600.0 - 590.0) / 590.0)
        self.assertAlmostEqual(active[0].metrics[CALL_MONEYNESS_METRIC], (590.0 - 600.0) / 590.0)
        self.assertAlmostEqual(active[0].metrics[PUT_MONEYNESS_METRIC], (600.0 - 590.0) / 590.0)

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

        evaluations = CPComboStrategy(min_value=float("-inf"), max_value=-0.01).evaluate(snap, universe)

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

        evaluations = CPComboStrategy(min_value=0.01, max_value=float("inf")).evaluate(snap, universe)

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

        evaluations = CPComboStrategy(min_value=0.01, max_value=float("inf")).evaluate(snap, universe)

        self.assertEqual(evaluations, [])

    def test_abs_spread_uses_ab_leg_order_and_signed_strike_distance(self) -> None:
        universe = sample_universe()
        snap = snapshot(
            universe,
            {
                "SHFE.au2608": 610.0,
                "SHFE.au2608C600": 11.0,
                "SHFE.au2608C620": 10.0,
                "SHFE.au2608P600": 3.0,
                "SHFE.au2608P620": 2.0,
            },
        )

        evaluations = AbsSpreadStrategy(min_value=float("-inf"), max_value=0.1).evaluate(snap, universe)

        self.assertEqual(len(evaluations), 2)
        self.assertTrue(all(item.active for item in evaluations))
        call_eval = next(item for item in evaluations if ":CALL:" in item.key)
        put_eval = next(item for item in evaluations if ":PUT:" in item.key)
        self.assertEqual(call_eval.strategy_type, "abs_spread")
        self.assertEqual(
            call_eval.fields,
            {
                "underlying": "SHFE.AU2608",
                "expiry": "2026-8",
                "option_class": "CALL",
                "first_symbol": "SHFE.AU2608C600",
                "second_symbol": "SHFE.AU2608C620",
                "first_strike": "600",
                "second_strike": "620",
            },
        )
        self.assertEqual(call_eval.symbols, ("SHFE.AU2608C600", "SHFE.AU2608C620"))
        self.assertEqual(put_eval.symbols, ("SHFE.AU2608P620", "SHFE.AU2608P600"))
        self.assertAlmostEqual(call_eval.value, (11.0 - 10.0) / (600.0 - 620.0))
        self.assertAlmostEqual(put_eval.value, (2.0 - 3.0) / (620.0 - 600.0))
        self.assertAlmostEqual(call_eval.metrics[SPREAD_A_MONEYNESS_METRIC], (610.0 - 600.0) / 610.0)
        self.assertAlmostEqual(call_eval.metrics[SPREAD_B_MONEYNESS_METRIC], (610.0 - 620.0) / 610.0)
        self.assertAlmostEqual(call_eval.metrics[SPREAD_AVG_MONEYNESS_METRIC], 0.0)
        self.assertAlmostEqual(put_eval.metrics[SPREAD_A_MONEYNESS_METRIC], (620.0 - 610.0) / 610.0)
        self.assertAlmostEqual(put_eval.metrics[SPREAD_B_MONEYNESS_METRIC], (600.0 - 610.0) / 610.0)
        self.assertAlmostEqual(put_eval.metrics[SPREAD_AVG_MONEYNESS_METRIC], 0.0)

    def test_warning_range_uses_strict_bounds(self) -> None:
        universe = sample_universe()
        cp_snap = snapshot(
            universe,
            {
                "SHFE.au2608": 600.0,
                "SHFE.au2608C600": 11.0,
                "SHFE.au2608P600": 5.0,
            },
        )
        spread_snap = snapshot(
            universe,
            {
                "SHFE.au2608": 610.0,
                "SHFE.au2608C600": 10.0,
                "SHFE.au2608C620": 12.0,
                "SHFE.au2608P600": 2.0,
                "SHFE.au2608P620": 4.0,
            },
        )

        cp_evaluations = CPComboStrategy(min_value=0.01, max_value=float("inf")).evaluate(cp_snap, universe)
        spread_evaluations = AbsSpreadStrategy(min_value=float("-inf"), max_value=0.1).evaluate(
            spread_snap,
            universe,
        )

        self.assertFalse(any(item.active for item in cp_evaluations))
        self.assertFalse(any(item.active for item in spread_evaluations))

    def test_legacy_threshold_config_expands_to_warning_ranges(self) -> None:
        config = parse_config(
            {
                "strategies": [
                    {"type": "cp_combo", "threshold": 0.01},
                    {"type": "abs_spread", "threshold": 0.1},
                ]
            }
        )

        self.assertEqual(
            [(strategy.type, strategy.min_value, strategy.max_value) for strategy in config.strategies],
            [
                ("cp_combo", 0.01, float("inf")),
                ("cp_combo", float("-inf"), -0.01),
                ("abs_spread", float("-inf"), 0.1),
            ],
        )


if __name__ == "__main__":
    unittest.main()
