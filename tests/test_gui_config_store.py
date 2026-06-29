from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from kuaiqi.config import parse_config
from kuaiqi.gui.config_store import config_to_data, save_config


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
                    "universe": {"mode": "symbols", "symbols": ["SHFE.au2608C600"]},
                    "datasource": {
                        "tqsdk": {
                            "username_env": "TQSDK_USERNAME",
                            "password_env": "TQSDK_PASSWORD",
                        }
                    },
                    "strategies": [
                        {"type": "cp_combo", "threshold": 0.02},
                        {"type": "abs_spread", "threshold": 0.1, "name": "spread", "selected": False},
                    ],
                }
            )

            save_config(path, config)
            text = path.read_text(encoding="utf-8")
            saved = parse_config(config_to_data(config))

            self.assertIn("# keep this comment", text)
            self.assertIn('mode = "backtest"', text)
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
            config = parse_config({"strategies": [{"type": "cp_combo", "threshold": 0.01}]})

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
                    "strategies": [{"type": "cp_combo", "threshold": 0.01}],
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
                    "strategies": [{"type": "cp_combo", "threshold": 0.01}],
                }
            )

            save_config(path, config)

            text = path.read_text(encoding="utf-8")
            saved = parse_config(config_to_data(config))
            self.assertIn('password = "plain-email-secret"', text)
            self.assertIn('password_env = "MAIL_PASSWORD_ENV"', text)
            self.assertEqual(saved.notifier.email.password, "plain-email-secret")


if __name__ == "__main__":
    unittest.main()
