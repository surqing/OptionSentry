from __future__ import annotations

import unittest

from optionsentry.config import ConfigError, parse_config


def _strategy(
    *,
    strategy_id: str = "cp_default",
    strategy_type: str = "cp_combo",
    parameters: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": strategy_id,
        "type": strategy_type,
        "name": "测试策略",
        "enabled": True,
        "parameters": parameters
        if parameters is not None
        else {"min_value": 0.01, "max_value": float("inf")},
    }


class StrictConfigTests(unittest.TestCase):
    def test_minimal_new_schema_parses(self) -> None:
        config = parse_config({"schema_version": 1, "strategies": [_strategy()]})

        self.assertEqual(config.schema_version, 1)
        self.assertEqual(config.strategies[0].id, "cp_default")
        self.assertEqual(config.strategies[0].parameters["min_value"], 0.01)

    def test_schema_version_is_required(self) -> None:
        with self.assertRaisesRegex(ConfigError, "schema_version"):
            parse_config({"strategies": [_strategy()]})

    def test_legacy_root_and_flat_strategy_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "datasource"):
            parse_config(
                {
                    "schema_version": 1,
                    "datasource": {},
                    "strategies": [_strategy()],
                }
            )

        legacy = _strategy()
        legacy["min_value"] = 0.01
        with self.assertRaisesRegex(ConfigError, "min_value"):
            parse_config({"schema_version": 1, "strategies": [legacy]})

    def test_duplicate_and_invalid_strategy_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "Duplicate strategy id"):
            parse_config(
                {
                    "schema_version": 1,
                    "strategies": [_strategy(), _strategy()],
                }
            )

        with self.assertRaisesRegex(ConfigError, "must match"):
            parse_config(
                {
                    "schema_version": 1,
                    "strategies": [_strategy(strategy_id="CP Default")],
                }
            )

    def test_strategy_parameter_contract_is_strict(self) -> None:
        with self.assertRaisesRegex(ConfigError, "requires parameter: max_value"):
            parse_config(
                {
                    "schema_version": 1,
                    "strategies": [_strategy(parameters={"min_value": 0.01})],
                }
            )

        with self.assertRaisesRegex(ConfigError, "unknown parameters: window"):
            parse_config(
                {
                    "schema_version": 1,
                    "strategies": [
                        _strategy(
                            parameters={
                                "min_value": 0.01,
                                "max_value": 1.0,
                                "window": 20,
                            }
                        )
                    ],
                }
            )

        with self.assertRaisesRegex(ConfigError, "min_value must be less"):
            parse_config(
                {
                    "schema_version": 1,
                    "strategies": [
                        _strategy(parameters={"min_value": 1.0, "max_value": 1.0})
                    ],
                }
            )

    def test_credentials_cannot_be_stored_directly(self) -> None:
        with self.assertRaisesRegex(ConfigError, "username"):
            parse_config(
                {
                    "schema_version": 1,
                    "data_source": {
                        "provider": "tqsdk",
                        "tqsdk": {"username": "alice", "password": "secret"},
                    },
                    "strategies": [_strategy()],
                }
            )

    def test_batch_dates_and_logging_values_are_validated(self) -> None:
        with self.assertRaisesRegex(ConfigError, "batch sizes must be positive"):
            parse_config(
                {
                    "schema_version": 1,
                    "data_source": {
                        "provider": "tqsdk",
                        "tqsdk": {"symbol_info_batch_size": 0},
                    },
                    "strategies": [_strategy()],
                }
            )

        with self.assertRaisesRegex(ConfigError, "start_date must be on or before"):
            parse_config(
                {
                    "schema_version": 1,
                    "backtest": {
                        "start_date": "2026-02-01",
                        "end_date": "2026-01-01",
                    },
                    "strategies": [_strategy()],
                }
            )

        with self.assertRaisesRegex(ConfigError, "logging.level"):
            parse_config(
                {
                    "schema_version": 1,
                    "logging": {"level": "TRACE"},
                    "strategies": [_strategy()],
                }
            )


if __name__ == "__main__":
    unittest.main()
