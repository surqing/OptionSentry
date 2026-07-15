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


def _config(**overrides: object):
    data: dict[str, object] = {
        "schema_version": 1,
        "strategies": [
            {
                "id": "cp",
                "type": "cp_combo",
                "name": "CP",
                "enabled": True,
                "parameters": {"min_value": 0.01, "max_value": float("inf")},
            }
        ],
    }
    data.update(overrides)
    return parse_config(data)


class GuiCredentialTests(unittest.TestCase):
    def test_blank_login_uses_configured_environment_variables(self) -> None:
        config = _config(
            data_source={
                "provider": "tqsdk",
                "tqsdk": {"username_env": "USER_ENV", "password_env": "PASS_ENV"},
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

    def test_filled_login_uses_session_credentials(self) -> None:
        config = _config(
            data_source={
                "provider": "tqsdk",
                "tqsdk": {"username_env": "USER_ENV", "password_env": "PASS_ENV"},
            }
        )
        environ: dict[str, str] = {}

        credentials = resolve_tqsdk_credentials(config, "alice", "secret", environ=environ)
        apply_session_credentials(credentials, environ=environ)

        self.assertEqual(credentials.source, "session")
        self.assertEqual(environ, {"USER_ENV": "alice", "PASS_ENV": "secret"})

    def test_partially_filled_login_fails(self) -> None:
        with self.assertRaises(ConfigError):
            resolve_tqsdk_credentials(_config(), "alice", "")

    def test_config_rejects_persisted_tqsdk_credentials(self) -> None:
        with self.assertRaisesRegex(ConfigError, "Unknown data_source.tqsdk field"):
            _config(data_source={"provider": "tqsdk", "tqsdk": {"username": "alice"}})

    def test_load_and_validate_login_does_not_write_credentials_to_config(self) -> None:
        calls: list[tuple[str, str]] = []

        def factory(username: str, password: str) -> object:
            calls.append((username, password))
            return _FakeApi()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(
                "schema_version = 1\n\n"
                "[data_source]\n"
                'provider = "tqsdk"\n\n'
                "[data_source.tqsdk]\n"
                'username_env = "USER_ENV"\n'
                'password_env = "PASS_ENV"\n\n'
                "[[strategies]]\n"
                'id = "cp"\n'
                'type = "cp_combo"\n'
                'name = "CP"\n'
                "enabled = true\n\n"
                "[strategies.parameters]\n"
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
