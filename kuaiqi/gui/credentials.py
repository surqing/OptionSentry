from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, MutableMapping

from kuaiqi.config import AppConfig, ConfigError, load_config


@dataclass(frozen=True)
class CredentialResolution:
    username: str
    password: str
    username_env: str
    password_env: str
    source: str


def resolve_tqsdk_credentials(
    config: AppConfig,
    username_input: str,
    password_input: str,
    environ: MutableMapping[str, str] | None = None,
) -> CredentialResolution:
    environ = os.environ if environ is None else environ
    username = username_input.strip()
    password = password_input.strip()
    username_env = config.tqsdk.username_env
    password_env = config.tqsdk.password_env

    if not username and not password:
        if config.tqsdk.username and config.tqsdk.password:
            return CredentialResolution(
                username=config.tqsdk.username,
                password=config.tqsdk.password,
                username_env=username_env,
                password_env=password_env,
                source="config",
            )
        env_username = environ.get(username_env, "")
        env_password = environ.get(password_env, "")
        if not env_username or not env_password:
            raise ConfigError(f"TqSdk auth requires {username_env} and {password_env}.")
        return CredentialResolution(
            username=env_username,
            password=env_password,
            username_env=username_env,
            password_env=password_env,
            source="environment",
        )

    if username and password:
        return CredentialResolution(
            username=username,
            password=password,
            username_env=username_env,
            password_env=password_env,
            source="session",
        )

    raise ConfigError("TqSdk username and password must be both filled or both empty.")


def apply_session_credentials(
    credentials: CredentialResolution,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    if credentials.source not in {"session", "config"}:
        return
    environ = os.environ if environ is None else environ
    environ[credentials.username_env] = credentials.username
    environ[credentials.password_env] = credentials.password


def validate_tqsdk_credentials(
    credentials: CredentialResolution,
    api_factory: Callable[[str, str], object] | None = None,
) -> None:
    if api_factory is None:
        from tqsdk import TqApi, TqAuth

        api = TqApi(auth=TqAuth(credentials.username, credentials.password))
    else:
        api = api_factory(credentials.username, credentials.password)
    close = getattr(api, "close", None)
    if close is not None:
        close()


def load_and_validate_login(
    config_path: str | Path,
    username_input: str,
    password_input: str,
    api_factory: Callable[[str, str], object] | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> tuple[AppConfig, CredentialResolution]:
    config = load_config(config_path)
    credentials = resolve_tqsdk_credentials(config, username_input, password_input, environ=environ)
    validate_tqsdk_credentials(credentials, api_factory=api_factory)
    apply_session_credentials(credentials, environ=environ)
    return config, credentials
