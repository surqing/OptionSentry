from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import tomlkit

from kuaiqi.config import AppConfig, ConfigError, parse_config


def config_to_data(config: AppConfig) -> dict[str, Any]:
    email = asdict(config.notifier.email)
    return {
        "runtime": asdict(config.runtime),
        "universe": asdict(config.universe),
        "datasource": {"tqsdk": asdict(config.tqsdk)},
        "strategies": [asdict(strategy) for strategy in config.strategies],
        "backtest": _date_strings(asdict(config.backtest)),
        "notifier": {
            "kind": config.notifier.kind,
            "alert_log_path": config.notifier.alert_log_path,
            "email": email,
        },
        "logging": asdict(config.logging),
    }


def save_config(path: str | Path, config: AppConfig) -> None:
    data = config_to_data(config)
    parse_config(data)
    config_path = Path(path)
    if config_path.exists():
        document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    else:
        document = tomlkit.document()
    _merge_document(document, data)
    parse_config(document.unwrap())
    config_path.write_text(tomlkit.dumps(document), encoding="utf-8")


def data_to_config(data: dict[str, Any]) -> AppConfig:
    try:
        return parse_config(data)
    except (TypeError, ValueError) as exc:
        raise ConfigError(str(exc)) from exc


def _merge_document(parent: Any, data: dict[str, Any]) -> None:
    for key, value in data.items():
        if value is None:
            if key in parent:
                parent.pop(key)
            continue
        if key == "strategies":
            parent[key] = _strategy_array(value)
        elif isinstance(value, dict):
            table = _ensure_table(parent, key)
            _merge_document(table, value)
        else:
            parent[key] = _toml_value(value)


def _ensure_table(parent: Any, key: str) -> Any:
    if key not in parent or not isinstance(parent[key], dict):
        parent[key] = tomlkit.table()
    return parent[key]


def _strategy_array(items: list[dict[str, Any]]) -> Any:
    array = tomlkit.aot()
    for item in items:
        table = tomlkit.table()
        for key, value in item.items():
            if value is not None:
                table[key] = _toml_value(value)
        array.append(table)
    return array


def _toml_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _date_strings(data: dict[str, Any]) -> dict[str, Any]:
    return {key: _toml_value(value) for key, value in data.items()}
