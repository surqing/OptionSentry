from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from optionsentry.config import ConfigError, parse_config
from optionsentry.gui.credentials import (
    apply_session_credentials,
    load_and_validate_login,
    resolve_tqsdk_credentials,
)


class GuiCredentialTests(unittest.TestCase):
    def test_blank_login_uses_configured_environment_variables(self) -> None:
        config = parse_config(
            {
                "datasource": {
                    "tqsdk": {
                        "username_env": "USER_ENV",
                        "password_env": "PASS_ENV",
                    }
                },
                "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
            }
        )

        credentials = resolve_tqsdk_credentials(
            config,
            "",
            "",
            environ={"USER_ENV": "alice", "PASS_ENV": "secret"},
        )

        self.assertEqual(credentials.username, "alice")
        self.assertEqual(credentials.password, "secret")
        self.assertEqual(credentials.source, "environment")

    def test_blank_login_prefers_remembered_config_credentials(self) -> None:
        config = parse_config(
            {
                "datasource": {
                    "tqsdk": {
                        "username": "remembered-user",
                        "password": "remembered-secret",
                        "username_env": "USER_ENV",
                        "password_env": "PASS_ENV",
                    }
                },
                "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
            }
        )
        environ = {"USER_ENV": "env-user", "PASS_ENV": "env-secret"}

        credentials = resolve_tqsdk_credentials(config, "", "", environ=environ)
        apply_session_credentials(credentials, environ=environ)

        self.assertEqual(credentials.username, "remembered-user")
        self.assertEqual(credentials.password, "remembered-secret")
        self.assertEqual(credentials.source, "config")
        self.assertEqual(environ["USER_ENV"], "remembered-user")
        self.assertEqual(environ["PASS_ENV"], "remembered-secret")

    def test_filled_login_uses_session_credentials_without_persisting_names(self) -> None:
        config = parse_config(
            {
                "datasource": {
                    "tqsdk": {
                        "username_env": "USER_ENV",
                        "password_env": "PASS_ENV",
                    }
                },
                "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
            }
        )
        environ: dict[str, str] = {}

        credentials = resolve_tqsdk_credentials(config, "alice", "secret", environ=environ)
        apply_session_credentials(credentials, environ=environ)

        self.assertEqual(credentials.source, "session")
        self.assertEqual(environ["USER_ENV"], "alice")
        self.assertEqual(environ["PASS_ENV"], "secret")
        self.assertEqual(credentials.username_env, "USER_ENV")
        self.assertEqual(credentials.password_env, "PASS_ENV")

    def test_partially_filled_login_fails(self) -> None:
        config = parse_config({"strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}]})

        with self.assertRaises(ConfigError):
            resolve_tqsdk_credentials(config, "alice", "")

    def test_partially_remembered_config_credentials_fail(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config(
                {
                    "datasource": {"tqsdk": {"username": "alice"}},
                    "strategies": [{"type": "cp_combo", "min_value": 0.01, "max_value": float("inf")}],
                }
            )

    def test_load_and_validate_login_does_not_write_credentials_to_config(self) -> None:
        calls: list[tuple[str, str]] = []

        def factory(username: str, password: str) -> object:
            calls.append((username, password))
            return _FakeApi()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(
                "[datasource.tqsdk]\n"
                'username_env = "USER_ENV"\n'
                'password_env = "PASS_ENV"\n\n'
                "[[strategies]]\n"
                'type = "cp_combo"\n'
                "min_value = 0.01\n"
                "max_value = inf\n",
                encoding="utf-8",
            )
            environ: dict[str, str] = {}

            _, credentials = load_and_validate_login(
                path,
                "alice",
                "super-secret",
                api_factory=factory,
                environ=environ,
            )

            self.assertEqual(credentials.source, "session")
            self.assertEqual(calls, [("alice", "super-secret")])
            self.assertNotIn("super-secret", path.read_text(encoding="utf-8"))


class _FakeApi:
    def close(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
