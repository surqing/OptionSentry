from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from optionsentry.config import parse_config
from optionsentry.gui.config_store import config_to_data, save_config


def _strategy(
    strategy_id: str = "cp_combo_default",
    strategy_type: str = "cp_combo",
    *,
    enabled: bool = True,
    parameters: dict[str, object] | None = None,
) -> dict[str, object]:
    if parameters is None:
        parameters = {"min_value": 0.01, "max_value": float("inf")}
    return {
        "id": strategy_id,
        "type": strategy_type,
        "name": strategy_id,
        "enabled": enabled,
        "parameters": parameters,
    }


def _config(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {"schema_version": 1, "strategies": [_strategy()]}
    data.update(overrides)
    return data


class GuiConfigStoreTests(unittest.TestCase):
    def test_save_config_rewrites_canonical_document_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text("# obsolete configuration\n", encoding="utf-8")
            config = parse_config(
                _config(
                    runtime={"mode": "backtest"},
                    backtest={"start_date": "2026-01-02", "end_date": "2026-01-05"},
                    universe={"mode": "include", "include": ["SHFE.au2608C600"]},
                    strategies=[
                        _strategy(parameters={"min_value": 0.02, "max_value": float("inf")}),
                        _strategy(
                            "spread",
                            "abs_spread",
                            enabled=False,
                            parameters={"min_value": float("-inf"), "max_value": 0.1},
                        ),
                    ],
                )
            )

            save_config(path, config)
            text = path.read_text(encoding="utf-8")
            saved = parse_config(config_to_data(config))

            self.assertNotIn("obsolete configuration", text)
            self.assertIn("schema_version = 1", text)
            self.assertIn("[strategies.parameters]", text)
            self.assertIn("enabled = false", text)
            self.assertEqual(saved, config)
            self.assertEqual([strategy.type for strategy in saved.enabled_strategies], ["cp_combo"])

    def test_save_config_does_not_write_environment_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            os.environ["TQSDK_PASSWORD"] = "super-secret"
            config = parse_config(_config())

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            self.assertIn('password_env = "TQSDK_PASSWORD"', text)
            self.assertNotIn("super-secret", text)

    def test_save_config_never_serializes_tqsdk_or_email_passwords(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            config = parse_config(
                _config(
                    data_source={
                        "provider": "tqsdk",
                        "tqsdk": {"username_env": "TQ_USER", "password_env": "TQ_PASSWORD"},
                    },
                    notifications={
                        "email": {
                            "username_env": "MAIL_USER",
                            "password_env": "MAIL_PASSWORD",
                        }
                    },
                )
            )

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            self.assertIn('username_env = "TQ_USER"', text)
            self.assertIn('password_env = "TQ_PASSWORD"', text)
            self.assertIn('username_env = "MAIL_USER"', text)
            self.assertIn('password_env = "MAIL_PASSWORD"', text)
            self.assertNotIn("password =", text)

    def test_save_config_writes_active_alert_refresh_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            config = parse_config(
                _config(gui={"active_alerts": {"auto_refresh": False, "refresh_interval_seconds": 180}})
            )

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            self.assertIn("[gui.active_alerts]", text)
            self.assertIn("auto_refresh = false", text)
            self.assertEqual(parse_config(config_to_data(config)), config)

    def test_save_config_writes_nested_strategy_filter_only_when_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            filtered = _strategy()
            filtered["filter"] = {"script": "filters/gold.py", "entrypoint": "accept"}
            config = parse_config(
                _config(
                    strategies=[
                        filtered,
                        _strategy(
                            "spread",
                            "abs_spread",
                            parameters={"min_value": float("-inf"), "max_value": 0.1},
                        ),
                    ]
                )
            )

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            self.assertIn("[strategies.filter]", text)
            self.assertIn('script = "filters/gold.py"', text)
            self.assertEqual(text.count("entrypoint"), 1)
            self.assertEqual(parse_config(config_to_data(config)), config)

    def test_save_config_writes_notification_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            config = parse_config(
                _config(
                    notifications={
                        "channels": {"popup": True, "sound": True, "file": False, "email": False},
                        "popup": {"duration_seconds": 5},
                        "sound": {"duration_seconds": 7},
                    }
                )
            )

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            self.assertIn("[notifications.channels]", text)
            self.assertIn("[notifications.popup]", text)
            self.assertIn("[notifications.sound]", text)
            self.assertTrue(config.notifier.channels.popup)
            self.assertFalse(config.notifier.channels.email)


if __name__ == "__main__":
    unittest.main()
