from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import tomlkit

from optionsentry.config import AppConfig, ConfigError, StrategyConfig, parse_config


def config_to_data(config: AppConfig) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "runtime": {
            "mode": config.runtime.mode,
            "alert_on_first_match": config.runtime.alert_on_first_match,
        },
        "universe": {
            "mode": config.universe.mode,
            "include": list(config.universe.include),
            "exclude": list(config.universe.exclude),
            "exchanges": list(config.universe.exchanges),
            "min_volume": config.universe.min_volume,
            "min_open_interest": config.universe.min_open_interest,
        },
        "data_source": {
            "provider": "tqsdk",
            "tqsdk": {
                "username_env": config.tqsdk.username_env,
                "password_env": config.tqsdk.password_env,
                "symbol_info_batch_size": config.tqsdk.symbol_info_batch_size,
                "quote_subscription_batch_size": config.tqsdk.quote_subscription_batch_size,
            },
        },
        "strategies": [_strategy_data(strategy) for strategy in config.strategies],
        "backtest": {
            "start_date": config.backtest.start_dt,
            "end_date": config.backtest.end_dt,
            "kline_duration_seconds": config.backtest.duration_seconds,
            "data_length": config.backtest.data_length,
            "initialization_timeout_seconds": config.backtest.initial_price_timeout_seconds,
            "subscription_batch_size": config.backtest.subscription_batch_size,
        },
        "notifications": {
            "channels": {
                "popup": config.notifier.channels.popup,
                "sound": config.notifier.channels.sound,
                "file": config.notifier.channels.file,
                "email": config.notifier.channels.email,
            },
            "file": {"path": config.notifier.alert_log_path},
            "popup": {"duration_seconds": config.notifier.popup.duration_seconds},
            "sound": {"duration_seconds": config.notifier.sound.duration_seconds},
            "email": {
                "smtp_host": config.notifier.email.smtp_host or "",
                "smtp_port": config.notifier.email.smtp_port,
                "smtp_timeout_seconds": config.notifier.email.smtp_timeout_seconds,
                "aggregation_seconds": config.notifier.email.alert_interval_seconds,
                "username_env": config.notifier.email.username_env,
                "password_env": config.notifier.email.password_env,
                "from_address": config.notifier.email.from_addr or "",
                "to_addresses": list(config.notifier.email.to_addrs),
                "use_tls": config.notifier.email.use_tls,
                "failure_backoff_seconds": config.notifier.email.failure_backoff_seconds,
            },
        },
        "logging": {
            "level": config.logging.level,
            "directory": config.logging.log_dir,
            "filename": config.logging.log_file,
            "max_bytes": config.logging.max_bytes,
            "backup_count": config.logging.backup_count,
            "summary_interval_seconds": config.logging.cycle_summary_interval_seconds,
        },
        "gui": {
            "active_alerts": {
                "auto_refresh": config.gui.active_alerts.auto_refresh,
                "refresh_interval_seconds": config.gui.active_alerts.refresh_interval_seconds,
            }
        },
    }


def save_config(path: str | Path, config: AppConfig) -> None:
    data = config_to_data(config)
    parse_config(data)
    document = tomlkit.document()
    _merge_document(document, data)
    config_path = Path(path)
    config_path.write_text(tomlkit.dumps(document), encoding="utf-8")


def data_to_config(data: dict[str, Any]) -> AppConfig:
    try:
        return parse_config(data)
    except (TypeError, ValueError) as exc:
        raise ConfigError(str(exc)) from exc


def _strategy_data(strategy: StrategyConfig) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": strategy.id,
        "type": strategy.type,
        "name": strategy.name,
        "enabled": strategy.enabled,
        "parameters": dict(strategy.parameters),
    }
    if strategy.filter is not None:
        item["filter"] = {
            "script": strategy.filter.script,
            "entrypoint": strategy.filter.entrypoint,
        }
    return item


def _merge_document(parent: Any, data: dict[str, Any]) -> None:
    for key, value in data.items():
        if value is None:
            continue
        if key == "strategies":
            parent[key] = _strategy_array(value)
        elif isinstance(value, dict):
            table = tomlkit.table()
            parent[key] = table
            _merge_document(table, value)
        else:
            parent[key] = _toml_value(value)


def _strategy_array(items: list[dict[str, Any]]) -> Any:
    array = tomlkit.aot()
    for item in items:
        table = tomlkit.table()
        for key in ("id", "type", "name", "enabled"):
            table[key] = _toml_value(item[key])
        parameters = tomlkit.table()
        for key, value in item["parameters"].items():
            parameters[key] = _toml_value(value)
        table["parameters"] = parameters
        if "filter" in item:
            filter_table = tomlkit.table()
            for key, value in item["filter"].items():
                filter_table[key] = _toml_value(value)
            table["filter"] = filter_table
        array.append(table)
    return array


def _toml_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
