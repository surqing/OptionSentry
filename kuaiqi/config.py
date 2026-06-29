from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str = "live"
    price_basis: str = "last"
    alert_on_first_match: bool = False


@dataclass(frozen=True)
class UniverseConfig:
    mode: str = "all"
    underlyings: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    exchange_ids: tuple[str, ...] = ()
    min_volume: float = 0.0
    min_open_interest: float = 0.0


@dataclass(frozen=True)
class BacktestConfig:
    start_dt: date | None = None
    end_dt: date | None = None
    duration_seconds: int = 60
    data_length: int = 2
    initial_price_timeout_seconds: int = 120
    subscription_batch_size: int = 50


@dataclass(frozen=True)
class TqSdkConfig:
    username: str | None = None
    password: str | None = None
    username_env: str = "TQSDK_USERNAME"
    password_env: str = "TQSDK_PASSWORD"
    symbol_info_batch_size: int = 500
    quote_subscription_batch_size: int = 500


@dataclass(frozen=True)
class StrategyConfig:
    type: str
    threshold: float
    name: str | None = None
    selected: bool = True


@dataclass(frozen=True)
class EmailConfig:
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_timeout_seconds: int = 10
    alert_interval_seconds: int = 60
    username: str | None = None
    password: str | None = None
    password_env: str = "SMTP_PASSWORD"
    from_addr: str | None = None
    to_addrs: tuple[str, ...] = ()
    use_tls: bool = True
    failure_backoff_seconds: int = 300


@dataclass(frozen=True)
class NotifierConfig:
    kind: str | None = None
    email: EmailConfig = field(default_factory=EmailConfig)
    alert_log_path: str = "logs/alerts.jsonl"


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    log_dir: str = "logs"
    log_file: str = "kuaiqi.log"
    max_bytes: int = 5_000_000
    backup_count: int = 5
    cycle_summary_interval_seconds: int = 60


@dataclass(frozen=True)
class AppConfig:
    runtime: RuntimeConfig
    universe: UniverseConfig
    backtest: BacktestConfig
    tqsdk: TqSdkConfig
    strategies: tuple[StrategyConfig, ...]
    notifier: NotifierConfig
    logging: LoggingConfig

    @property
    def selected_strategies(self) -> tuple[StrategyConfig, ...]:
        return tuple(strategy for strategy in self.strategies if strategy.selected)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    with config_path.open("rb") as fp:
        data = tomllib.load(fp)
    return parse_config(data)


def parse_config(data: dict[str, Any]) -> AppConfig:
    runtime = _parse_runtime(data.get("runtime", {}))
    universe = _parse_universe(data.get("universe", {}))
    backtest = _parse_backtest(data.get("backtest", {}))
    datasource = data.get("datasource", {})
    tqsdk = _parse_tqsdk(datasource.get("tqsdk", {}))
    strategies = _parse_strategies(data.get("strategies", []))
    notifier = _parse_notifier(data.get("notifier", {}), data.get("notifier.email", {}))
    logging_config = _parse_logging(data.get("logging", {}))
    _validate_config(runtime, universe, backtest, strategies, logging_config)
    return AppConfig(
        runtime=runtime,
        universe=universe,
        backtest=backtest,
        tqsdk=tqsdk,
        strategies=strategies,
        notifier=notifier,
        logging=logging_config,
    )


def _parse_runtime(data: dict[str, Any]) -> RuntimeConfig:
    return RuntimeConfig(
        mode=str(data.get("mode", "live")),
        price_basis=str(data.get("price_basis", "last")),
        alert_on_first_match=bool(data.get("alert_on_first_match", False)),
    )


def _parse_universe(data: dict[str, Any]) -> UniverseConfig:
    return UniverseConfig(
        mode=str(data.get("mode", "all")),
        underlyings=_tuple_of_str(data.get("underlyings", ())),
        symbols=_tuple_of_str(data.get("symbols", ())),
        exchange_ids=_tuple_of_str(data.get("exchange_ids", ())),
        min_volume=float(data.get("min_volume", 0)),
        min_open_interest=float(data.get("min_open_interest", 0)),
    )


def _parse_backtest(data: dict[str, Any]) -> BacktestConfig:
    return BacktestConfig(
        start_dt=_optional_date(data.get("start_dt")),
        end_dt=_optional_date(data.get("end_dt")),
        duration_seconds=int(data.get("duration_seconds", 60)),
        data_length=int(data.get("data_length", 2)),
        initial_price_timeout_seconds=int(data.get("initial_price_timeout_seconds", 120)),
        subscription_batch_size=int(data.get("subscription_batch_size", 50)),
    )


def _parse_tqsdk(data: dict[str, Any]) -> TqSdkConfig:
    symbol_info_batch_size = int(data.get("symbol_info_batch_size", 500))
    quote_subscription_batch_size = int(data.get("quote_subscription_batch_size", 500))
    username = _optional_str(data.get("username"))
    password = _optional_str(data.get("password"))
    if bool(username) != bool(password):
        raise ConfigError("datasource.tqsdk.username and password must be both set or both omitted.")
    if symbol_info_batch_size <= 0:
        raise ConfigError("datasource.tqsdk.symbol_info_batch_size must be positive.")
    if quote_subscription_batch_size <= 0:
        raise ConfigError("datasource.tqsdk.quote_subscription_batch_size must be positive.")
    return TqSdkConfig(
        username=username,
        password=password,
        username_env=str(data.get("username_env", "TQSDK_USERNAME")),
        password_env=str(data.get("password_env", "TQSDK_PASSWORD")),
        symbol_info_batch_size=symbol_info_batch_size,
        quote_subscription_batch_size=quote_subscription_batch_size,
    )


def _parse_strategies(data: list[dict[str, Any]]) -> tuple[StrategyConfig, ...]:
    if not isinstance(data, list):
        raise ConfigError("[[strategies]] must be a list of tables.")
    strategies: list[StrategyConfig] = []
    for item in data:
        if "type" not in item:
            raise ConfigError("Each strategy requires a type.")
        if "threshold" not in item:
            raise ConfigError(f"Strategy {item.get('type')} requires threshold.")
        strategies.append(
            StrategyConfig(
                type=str(item["type"]),
                threshold=float(item["threshold"]),
                name=str(item["name"]) if item.get("name") is not None else None,
                selected=bool(item.get("selected", True)),
            )
        )
    return tuple(strategies)


def _parse_notifier(data: dict[str, Any], flat_email_data: dict[str, Any]) -> NotifierConfig:
    email_data = data.get("email", flat_email_data) or {}
    alert_interval_seconds = int(email_data.get("alert_interval_seconds", 60))
    if alert_interval_seconds < 0:
        raise ConfigError("notifier.email.alert_interval_seconds must be non-negative.")
    email = EmailConfig(
        smtp_host=_env_or_value(email_data.get("smtp_host"), "SMTP_HOST"),
        smtp_port=int(_env_or_value(email_data.get("smtp_port"), "SMTP_PORT") or 587),
        smtp_timeout_seconds=int(email_data.get("smtp_timeout_seconds", 10)),
        alert_interval_seconds=alert_interval_seconds,
        username=_env_or_value(email_data.get("username"), "SMTP_USERNAME"),
        password=str(email_data["password"]) if email_data.get("password") is not None else None,
        password_env=str(email_data.get("password_env", "SMTP_PASSWORD")),
        from_addr=_env_or_value(email_data.get("from_addr"), "ALERT_EMAIL_FROM"),
        to_addrs=_parse_recipients(email_data.get("to_addrs")),
        use_tls=bool(email_data.get("use_tls", True)),
        failure_backoff_seconds=int(email_data.get("failure_backoff_seconds", 300)),
    )
    return NotifierConfig(
        kind=str(data["kind"]) if data.get("kind") else None,
        email=email,
        alert_log_path=str(data.get("alert_log_path", "logs/alerts.jsonl")),
    )


def _parse_logging(data: dict[str, Any]) -> LoggingConfig:
    return LoggingConfig(
        level=str(data.get("level", "INFO")),
        log_dir=str(data.get("log_dir", "logs")),
        log_file=str(data.get("log_file", "kuaiqi.log")),
        max_bytes=int(data.get("max_bytes", 5_000_000)),
        backup_count=int(data.get("backup_count", 5)),
        cycle_summary_interval_seconds=int(data.get("cycle_summary_interval_seconds", 60)),
    )


def _validate_config(
    runtime: RuntimeConfig,
    universe: UniverseConfig,
    backtest: BacktestConfig,
    strategies: tuple[StrategyConfig, ...],
    logging_config: LoggingConfig,
) -> None:
    if runtime.mode not in {"live", "backtest"}:
        raise ConfigError("runtime.mode must be 'live' or 'backtest'.")
    if runtime.price_basis != "last":
        raise ConfigError("Only runtime.price_basis='last' is supported in this version.")
    if universe.mode not in {"all", "underlyings", "symbols"}:
        raise ConfigError("universe.mode must be 'all', 'underlyings', or 'symbols'.")
    if universe.mode == "underlyings" and not universe.underlyings:
        raise ConfigError("universe.underlyings is required when universe.mode='underlyings'.")
    if universe.mode == "symbols" and not universe.symbols:
        raise ConfigError("universe.symbols is required when universe.mode='symbols'.")
    if universe.min_volume < 0:
        raise ConfigError("universe.min_volume must be non-negative.")
    if universe.min_open_interest < 0:
        raise ConfigError("universe.min_open_interest must be non-negative.")
    if runtime.mode == "backtest" and (backtest.start_dt is None or backtest.end_dt is None):
        raise ConfigError("backtest.start_dt and backtest.end_dt are required in backtest mode.")
    if runtime.mode == "backtest" and backtest.duration_seconds != 60:
        raise ConfigError("Backtest mode currently supports only 60-second K-lines.")
    if runtime.mode == "backtest" and backtest.subscription_batch_size <= 0:
        raise ConfigError("backtest.subscription_batch_size must be positive.")
    if logging_config.max_bytes <= 0:
        raise ConfigError("logging.max_bytes must be positive.")
    if logging_config.backup_count < 0:
        raise ConfigError("logging.backup_count must be non-negative.")
    if logging_config.cycle_summary_interval_seconds < 0:
        raise ConfigError("logging.cycle_summary_interval_seconds must be non-negative.")
    if not strategies:
        raise ConfigError("At least one [[strategies]] entry is required.")
    for strategy in strategies:
        if strategy.type not in {"cp_combo", "abs_spread"}:
            raise ConfigError(f"Unsupported strategy type: {strategy.type}")
        if strategy.threshold < 0:
            raise ConfigError(f"Strategy threshold must be non-negative: {strategy.type}")


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _env_or_value(value: Any, env_name: str) -> str | None:
    if value is not None:
        return str(value)
    return os.environ.get(env_name)


def _parse_recipients(value: Any) -> tuple[str, ...]:
    if value is None:
        env_value = os.environ.get("ALERT_EMAIL_TO", "")
        value = [item.strip() for item in env_value.split(",") if item.strip()]
    return _tuple_of_str(value)
