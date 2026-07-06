from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from optionsentry.config import parse_config
from optionsentry.gui.config_store import config_to_data, save_config


class GuiConfigStoreTests(unittest.TestCase):
    def test_save_config_preserves_existing_comments_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(
                "# keep this comment\n"
                "[runtime]\n"
                'mode = "live"\n'
                'price_basis = "last"\n\n'
                "[[strategies]]\n"
                'type = "cp_combo"\n'
                "threshold = 0.01\n",
                encoding="utf-8",
            )
            config = parse_config(
                {
                    "runtime": {"mode": "backtest"},
                    "backtest": {"start_dt": "2026-01-02", "end_dt": "2026-01-05"},
                    "universe": {
                        "mode": "指定模式",
                        "only_do": ["SHFE.au2608C600"],
                        "not_do": [],
                    },
                    "datasource": {
                        "tqsdk": {
                            "username_env": "TQSDK_USERNAME",
                            "password_env": "TQSDK_PASSWORD",
                        }
                    },
                    "strategies": [
                        {"type": "cp_combo", "min_value": 0.02, "max_value": float("inf")},
                        {
                            "type": "abs_spread",
                            "min_value": float("-inf"),
                            "max_value": 0.1,
                            "name": "spread",
                            "selected": False,
                        },
                    ],
                }
            )

            save_config(path, config)
            text = path.read_text(encoding="utf-8")
            saved = parse_config(config_to_data(config))

            self.assertIn("# keep this comment", text)
            self.assertIn('mode = "backtest"', text)
            self.assertIn("min_value = 0.02", text)
            self.assertIn("max_value = inf", text)
            self.assertIn("selected = false", text)
            self.assertEqual(saved.runtime.mode, "backtest")
            self.assertEqual(len(saved.strategies), 2)
            self.assertTrue(saved.strategies[0].selected)
            self.assertFalse(saved.strategies[1].selected)
            self.assertEqual([strategy.type for strategy in saved.selected_strategies], ["cp_combo"])

    def test_save_config_does_not_write_environment_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            os.environ["TQSDK_PASSWORD"] = "super-secret"
            config = parse_config({"strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}]})

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            self.assertIn('password_env = "TQSDK_PASSWORD"', text)
            self.assertNotIn("super-secret", text)

    def test_save_config_writes_remembered_tqsdk_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            config = parse_config(
                {
                    "datasource": {
                        "tqsdk": {
                            "username": "saved-user",
                            "password": "saved-secret",
                        }
                    },
                    "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
                }
            )

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            saved = parse_config(config_to_data(config))
            self.assertIn('username = "saved-user"', text)
            self.assertIn('password = "saved-secret"', text)
            self.assertEqual(saved.tqsdk.username, "saved-user")
            self.assertEqual(saved.tqsdk.password, "saved-secret")

    def test_save_config_writes_explicit_email_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            config = parse_config(
                {
                    "notifier": {
                        "email": {
                            "password": "plain-email-secret",
                            "password_env": "MAIL_PASSWORD_ENV",
                        }
                    },
                    "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
                }
            )

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            saved = parse_config(config_to_data(config))
            self.assertIn('password = "plain-email-secret"', text)
            self.assertIn('password_env = "MAIL_PASSWORD_ENV"', text)
            self.assertEqual(saved.notifier.email.password, "plain-email-secret")

    def test_save_config_writes_active_alert_refresh_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            config = parse_config(
                {
                    "gui": {
                        "active_alerts": {
                            "auto_refresh": False,
                            "refresh_interval_seconds": 180,
                        }
                    },
                    "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
                }
            )

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            saved = parse_config(config_to_data(config))
            self.assertIn("[gui.active_alerts]", text)
            self.assertIn("auto_refresh = false", text)
            self.assertIn("refresh_interval_seconds = 180", text)
            self.assertFalse(saved.gui.active_alerts.auto_refresh)
            self.assertEqual(saved.gui.active_alerts.refresh_interval_seconds, 180)

    def test_save_config_writes_strategy_filter_only_when_script_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            config = parse_config(
                {
                    "strategies": [
                        {
                            "type": "cp_combo",
                            "min_value": 0.01,
                            "max_value": float("inf"),
                            "filter_script": "filters/gold.py",
                            "filter_function": "accept",
                            "filter_scope": "options",
                        },
                        {"type": "abs_spread", "min_value": float("-inf"), "max_value": 0.1},
                    ],
                }
            )

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            saved = parse_config(config_to_data(config))
            self.assertIn('filter_script = "filters/gold.py"', text)
            self.assertIn('filter_function = "accept"', text)
            self.assertIn('filter_scope = "options"', text)
            self.assertEqual(text.count("filter_function"), 1)
            self.assertEqual(saved.strategies[0].filter_script, "filters/gold.py")
            self.assertIsNone(saved.strategies[1].filter_script)

    def test_save_config_writes_notifier_channels_and_removes_legacy_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(
                "[notifier]\n"
                'kind = "console"\n\n'
                "[[strategies]]\n"
                'type = "cp_combo"\n'
                "threshold = 0.01\n",
                encoding="utf-8",
            )
            config = parse_config(
                {
                    "notifier": {
                        "kind": "console",
                        "channels": {
                            "popup": True,
                            "sound": True,
                            "file": False,
                            "email": False,
                        },
                        "popup": {"duration_seconds": 5},
                        "sound": {"duration_seconds": 7},
                    },
                    "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
                }
            )

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            saved = parse_config(config_to_data(config))
            self.assertNotIn("kind =", text)
            self.assertIn("[notifier.channels]", text)
            self.assertIn("popup = true", text)
            self.assertIn("sound = true", text)
            self.assertIn("file = false", text)
            self.assertIn("email = false", text)
            self.assertIn("[notifier.popup]", text)
            self.assertIn("duration_seconds = 5", text)
            self.assertIn("[notifier.sound]", text)
            self.assertIn("duration_seconds = 7", text)
            self.assertTrue(saved.notifier.channels.popup)
            self.assertTrue(saved.notifier.channels.sound)
            self.assertFalse(saved.notifier.channels.file)
            self.assertFalse(saved.notifier.channels.email)


if __name__ == "__main__":
    unittest.main()
