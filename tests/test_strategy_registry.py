from __future__ import annotations

import unittest
import subprocess
import sys
import tempfile
from pathlib import Path

from optionsentry.config import StrategyConfig, parse_config, strategy_type_display_name
from optionsentry.strategy_base import Strategy
from optionsentry.strategy_registry import (
    ParsedAlertKey,
    STRATEGY_REGISTRY,
    create_strategy,
    get_strategy_class,
    parse_alert_key,
    register_strategy,
    supported_strategy_types,
)


class StrategyRegistryTests(unittest.TestCase):
    def test_builtin_strategies_are_discovered_in_display_order(self) -> None:
        self.assertEqual(supported_strategy_types(), ("cp_combo", "abs_spread"))
        self.assertEqual(get_strategy_class("cp_combo").display_name, "CP组合预警")
        self.assertEqual(get_strategy_class("abs_spread").display_name, "价差预警")

    def test_create_strategy_uses_registered_class(self) -> None:
        config = StrategyConfig(type="cp_combo", min_value=0.01, max_value=float("inf"))

        strategy = create_strategy(config)

        self.assertEqual(type(strategy).__name__, "CPComboStrategy")
        self.assertEqual(strategy.name, "CP组合预警")

    def test_unknown_strategy_type_raises_compatible_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported strategy type: missing"):
            get_strategy_class("missing")

    def test_config_display_and_range_expansion_are_registry_driven(self) -> None:
        @register_strategy("registry_test")
        class RegistryTestStrategy(Strategy):
            display_name = "注册测试策略"
            display_order = 999

            @classmethod
            def expand_ranges(
                cls,
                *,
                explicit_range: tuple[float, float] | None,
                threshold: float | None,
            ) -> tuple[tuple[float, float], ...]:
                if explicit_range is not None:
                    return (explicit_range,)
                return ((1.0, 2.0), (3.0, 4.0))

        try:
            self.assertEqual(strategy_type_display_name("registry_test"), "注册测试策略")
            parsed = parse_config(
                {"strategies": [{"type": "registry_test", "threshold": 0.5}]}
            )
            self.assertEqual(
                [(item.min_value, item.max_value) for item in parsed.strategies],
                [(1.0, 2.0), (3.0, 4.0)],
            )
        finally:
            STRATEGY_REGISTRY.pop("registry_test", None)

    def test_parse_alert_key_supports_localized_names_and_key_shapes(self) -> None:
        cp_key = (
            "CP组合预警:SHFE.au2608:2026-8:K=600:"
            "SHFE.au2608C600:SHFE.au2608P600:R=0.01..inf"
        )
        spread_key = (
            "价差预警:GFEX.lc2608:2026-7:PUT:"
            "GFEX.lc2608-P-128000:GFEX.lc2608-P-130000:R=-inf..0.1"
        )

        self.assertEqual(
            parse_alert_key(cp_key),
            ParsedAlertKey(
                strategy_type="cp_combo",
                fields={
                    "underlying": "SHFE.au2608",
                    "expiry": "2026-8",
                    "strike": "600",
                    "call_symbol": "SHFE.au2608C600",
                    "put_symbol": "SHFE.au2608P600",
                },
            ),
        )
        self.assertEqual(
            parse_alert_key(spread_key),
            ParsedAlertKey(
                strategy_type="abs_spread",
                fields={
                    "underlying": "GFEX.lc2608",
                    "expiry": "2026-7",
                    "option_class": "PUT",
                    "first_symbol": "GFEX.lc2608-P-128000",
                    "second_symbol": "GFEX.lc2608-P-130000",
                    "first_strike": "128000",
                    "second_strike": "130000",
                },
            ),
        )
        self.assertIsNone(parse_alert_key("not:a:strategy:key"))

    def test_package_scan_discovers_new_module_without_aggregator_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package = Path(tmpdir) / "demo_strategies"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "demo.py").write_text(
                "\n".join(
                    (
                        "from optionsentry.strategy_base import Strategy",
                        "from optionsentry.strategy_registry import register_strategy",
                        "@register_strategy('demo')",
                        "class DemoStrategy(Strategy):",
                        "    display_name = '演示策略'",
                        "    display_order = 1",
                    )
                ),
                encoding="utf-8",
            )
            script = (
                "import sys; "
                f"sys.path.insert(0, {tmpdir!r}); "
                "import optionsentry.strategy_registry as registry; "
                "registry.BUILTIN_STRATEGY_PACKAGE = 'demo_strategies'; "
                "print(registry.supported_strategy_types())"
            )

            result = subprocess.run(
                [sys.executable, "-c", script],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.stdout.strip(), "('demo',)")

    def test_duplicate_registration_fails_loudly(self) -> None:
        script = "\n".join(
            (
                "from optionsentry.strategy_registry import register_strategy",
                "@register_strategy('duplicate')",
                "class First: pass",
                "@register_strategy('duplicate')",
                "class Second: pass",
            )
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate strategy type: duplicate", result.stderr)

    def test_config_and_compatibility_facade_are_import_order_independent(self) -> None:
        scripts = (
            "import optionsentry.config; import optionsentry.strategies",
            "import optionsentry.strategies; import optionsentry.config",
        )
        for script in scripts:
            with self.subTest(script=script):
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
