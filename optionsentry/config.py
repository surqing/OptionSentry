from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from optionsentry.symbols import normalize_symbols


SCHEMA_VERSION = 1
ACTIVE_ALERT_REFRESH_INTERVALS = frozenset({10, 30, 60, 180, 300, 600})
STRATEGY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str = "live"
    alert_on_first_match: bool = False


@dataclass(frozen=True)
class UniverseConfig:
    mode: str = "all"
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    exchanges: tuple[str, ...] = ()
    min_volume: int = 0
    min_open_interest: int = 0


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
    username_env: str = "TQSDK_USERNAME"
    password_env: str = "TQSDK_PASSWORD"
    symbol_info_batch_size: int = 500
    quote_subscription_batch_size: int = 500


@dataclass(frozen=True)
class StrategyFilterConfig:
    script: str
    entrypoint: str = "accept"


@dataclass(frozen=True)
class StrategyConfig:
    id: str
    type: str
    name: str
    enabled: bool
    parameters: Mapping[str, Any]
    filter: StrategyFilterConfig | None = None

    @property
    def filter_script(self) -> str | None:
        return self.filter.script if self.filter is not None else None

    @property
    def filter_function(self) -> str:
        return self.filter.entrypoint if self.filter is not None else "accept"

    @property
    def filter_scope(self) -> str:
        return "options"


def strategy_type_display_name(strategy_type: str) -> str:
    from optionsentry.strategy_registry import get_strategy_class

    try:
        return get_strategy_class(strategy_type).display_name
    except ValueError:
        return strategy_type


def strategy_display_name(strategy: StrategyConfig) -> str:
    return strategy.name


@dataclass(frozen=True)
class EmailConfig:
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_timeout_seconds: int = 10
    alert_interval_seconds: int = 60
    username: str | None = None
    username_env: str = "SMTP_USERNAME"
    password: str | None = None
    password_env: str = "SMTP_PASSWORD"
    from_addr: str | None = None
    to_addrs: tuple[str, ...] = ()
    use_tls: bool = True
    failure_backoff_seconds: int = 300


@dataclass(frozen=True)
class NotifierChannelsConfig:
    popup: bool = False
    sound: bool = False
    file: bool = True
    email: bool = False


@dataclass(frozen=True)
class PopupConfig:
    duration_seconds: int = 2


@dataclass(frozen=True)
class SoundConfig:
    duration_seconds: int = 2


@dataclass(frozen=True)
class NotifierConfig:
    channels: NotifierChannelsConfig = field(default_factory=NotifierChannelsConfig)
    popup: PopupConfig = field(default_factory=PopupConfig)
    sound: SoundConfig = field(default_factory=SoundConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    alert_log_path: str = "logs/alerts.jsonl"


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    log_dir: str = "logs"
    log_file: str = "optionsentry.log"
    max_bytes: int = 5_000_000
    backup_count: int = 5
    cycle_summary_interval_seconds: int = 60


@dataclass(frozen=True)
class ActiveAlertsViewConfig:
    auto_refresh: bool = True
    refresh_interval_seconds: int = 10


@dataclass(frozen=True)
class GuiConfig:
    active_alerts: ActiveAlertsViewConfig = field(default_factory=ActiveAlertsViewConfig)


@dataclass(frozen=True)
class AppConfig:
    schema_version: int
    runtime: RuntimeConfig
    universe: UniverseConfig
    backtest: BacktestConfig
    tqsdk: TqSdkConfig
    strategies: tuple[StrategyConfig, ...]
    notifier: NotifierConfig
    logging: LoggingConfig
    gui: GuiConfig = field(default_factory=GuiConfig)

    @property
    def enabled_strategies(self) -> tuple[StrategyConfig, ...]:
        return tuple(strategy for strategy in self.strategies if strategy.enabled)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    with config_path.open("rb") as fp:
        return parse_config(tomllib.load(fp))


def parse_config(data: dict[str, Any]) -> AppConfig:
    _reject_unknown(
        data,
        {
            "schema_version",
            "runtime",
            "universe",
            "data_source",
            "strategies",
            "backtest",
            "notifications",
            "logging",
            "gui",
        },
        "root",
    )
    version = _integer_value(data.get("schema_version"), "schema_version")
    if version != SCHEMA_VERSION:
        raise ConfigError(
            f"Unsupported schema_version: {version}. Expected {SCHEMA_VERSION}; "
            "recreate the configuration from config.example.toml."
        )

    runtime = _parse_runtime(_table(data.get("runtime"), "runtime"))
    universe = _parse_universe(_table(data.get("universe"), "universe"))
    backtest = _parse_backtest(_table(data.get("backtest"), "backtest"))
    tqsdk = _parse_data_source(_table(data.get("data_source"), "data_source"))
    strategies = _parse_strategies(data.get("strategies"))
    notifier = _parse_notifications(_table(data.get("notifications"), "notifications"))
    logging_config = _parse_logging(_table(data.get("logging"), "logging"))
    gui = _parse_gui(_table(data.get("gui"), "gui"))
    _validate_config(
        runtime,
        universe,
        backtest,
        tqsdk,
        strategies,
        notifier,
        logging_config,
        gui,
    )
    return AppConfig(
        schema_version=version,
        runtime=runtime,
        universe=universe,
        backtest=backtest,
        tqsdk=tqsdk,
        strategies=strategies,
        notifier=notifier,
        logging=logging_config,
        gui=gui,
    )


def _parse_runtime(data: dict[str, Any]) -> RuntimeConfig:
    _reject_unknown(data, {"mode", "alert_on_first_match"}, "runtime")
    return RuntimeConfig(
        mode=str(data.get("mode", "live")),
        alert_on_first_match=_boolean_value(data.get("alert_on_first_match", False), "runtime.alert_on_first_match"),
    )


def _parse_universe(data: dict[str, Any]) -> UniverseConfig:
    _reject_unknown(
        data,
        {"mode", "include", "exclude", "exchanges", "min_volume", "min_open_interest"},
        "universe",
    )
    return UniverseConfig(
        mode=str(data.get("mode", "all")),
        include=normalize_symbols(_tuple_of_str(data.get("include", []), "universe.include")),
        exclude=normalize_symbols(_tuple_of_str(data.get("exclude", []), "universe.exclude")),
        exchanges=normalize_symbols(_tuple_of_str(data.get("exchanges", []), "universe.exchanges")),
        min_volume=_integer_value(data.get("min_volume", 0), "universe.min_volume"),
        min_open_interest=_integer_value(data.get("min_open_interest", 0), "universe.min_open_interest"),
    )


def _parse_backtest(data: dict[str, Any]) -> BacktestConfig:
    _reject_unknown(
        data,
        {
            "start_date",
            "end_date",
            "kline_duration_seconds",
            "data_length",
            "initialization_timeout_seconds",
            "subscription_batch_size",
        },
        "backtest",
    )
    return BacktestConfig(
        start_dt=_optional_date(data.get("start_date"), "backtest.start_date"),
        end_dt=_optional_date(data.get("end_date"), "backtest.end_date"),
        duration_seconds=_integer_value(
            data.get("kline_duration_seconds", 60), "backtest.kline_duration_seconds"
        ),
        data_length=_integer_value(data.get("data_length", 2), "backtest.data_length"),
        initial_price_timeout_seconds=_integer_value(
            data.get("initialization_timeout_seconds", 120),
            "backtest.initialization_timeout_seconds",
        ),
        subscription_batch_size=_integer_value(
            data.get("subscription_batch_size", 50), "backtest.subscription_batch_size"
        ),
    )


def _parse_data_source(data: dict[str, Any]) -> TqSdkConfig:
    _reject_unknown(data, {"provider", "tqsdk"}, "data_source")
    provider = str(data.get("provider", "tqsdk"))
    if provider != "tqsdk":
        raise ConfigError("data_source.provider must be 'tqsdk'.")
    tqsdk = _table(data.get("tqsdk"), "data_source.tqsdk")
    _reject_unknown(
        tqsdk,
        {"username_env", "password_env", "symbol_info_batch_size", "quote_subscription_batch_size"},
        "data_source.tqsdk",
    )
    return TqSdkConfig(
        username_env=_non_empty_string(tqsdk.get("username_env", "TQSDK_USERNAME"), "data_source.tqsdk.username_env"),
        password_env=_non_empty_string(tqsdk.get("password_env", "TQSDK_PASSWORD"), "data_source.tqsdk.password_env"),
        symbol_info_batch_size=_integer_value(
            tqsdk.get("symbol_info_batch_size", 500), "data_source.tqsdk.symbol_info_batch_size"
        ),
        quote_subscription_batch_size=_integer_value(
            tqsdk.get("quote_subscription_batch_size", 500),
            "data_source.tqsdk.quote_subscription_batch_size",
        ),
    )


def _parse_strategies(data: Any) -> tuple[StrategyConfig, ...]:
    from optionsentry.strategy_registry import get_strategy_class

    if not isinstance(data, list):
        raise ConfigError("[[strategies]] must be a list of tables.")
    strategies: list[StrategyConfig] = []
    ids: set[str] = set()
    for index, raw_item in enumerate(data):
        item = _table(raw_item, f"strategies[{index}]")
        _reject_unknown(item, {"id", "type", "name", "enabled", "parameters", "filter"}, f"strategies[{index}]")
        strategy_id = _non_empty_string(item.get("id"), f"strategies[{index}].id")
        if not STRATEGY_ID_PATTERN.fullmatch(strategy_id):
            raise ConfigError(
                f"strategies[{index}].id must match {STRATEGY_ID_PATTERN.pattern}: {strategy_id}"
            )
        if strategy_id in ids:
            raise ConfigError(f"Duplicate strategy id: {strategy_id}")
        ids.add(strategy_id)
        strategy_type = _non_empty_string(item.get("type"), f"strategies[{index}].type")
        try:
            strategy_class = get_strategy_class(strategy_type)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        parameters = _table(item.get("parameters"), f"strategies[{index}].parameters")
        try:
            normalized_parameters = strategy_class.validate_parameters(parameters)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        filter_config = _parse_strategy_filter(item.get("filter"), index)
        name = str(item.get("name", strategy_class.display_name)).strip()
        if not name:
            raise ConfigError(f"strategies[{index}].name cannot be empty.")
        strategies.append(
            StrategyConfig(
                id=strategy_id,
                type=strategy_type,
                name=name,
                enabled=_boolean_value(item.get("enabled", True), f"strategies[{index}].enabled"),
                parameters=normalized_parameters,
                filter=filter_config,
            )
        )
    return tuple(strategies)


def _parse_strategy_filter(value: Any, index: int) -> StrategyFilterConfig | None:
    if value is None:
        return None
    data = _table(value, f"strategies[{index}].filter")
    _reject_unknown(data, {"script", "entrypoint"}, f"strategies[{index}].filter")
    return StrategyFilterConfig(
        script=_non_empty_string(data.get("script"), f"strategies[{index}].filter.script"),
        entrypoint=_non_empty_string(
            data.get("entrypoint", "accept"), f"strategies[{index}].filter.entrypoint"
        ),
    )


def _parse_notifications(data: dict[str, Any]) -> NotifierConfig:
    _reject_unknown(data, {"channels", "file", "popup", "sound", "email"}, "notifications")
    channels_data = _table(data.get("channels"), "notifications.channels")
    _reject_unknown(channels_data, {"popup", "sound", "file", "email"}, "notifications.channels")
    channels = NotifierChannelsConfig(
        popup=_boolean_value(channels_data.get("popup", False), "notifications.channels.popup"),
        sound=_boolean_value(channels_data.get("sound", False), "notifications.channels.sound"),
        file=_boolean_value(channels_data.get("file", True), "notifications.channels.file"),
        email=_boolean_value(channels_data.get("email", False), "notifications.channels.email"),
    )
    file_data = _table(data.get("file"), "notifications.file")
    popup_data = _table(data.get("popup"), "notifications.popup")
    sound_data = _table(data.get("sound"), "notifications.sound")
    email_data = _table(data.get("email"), "notifications.email")
    _reject_unknown(file_data, {"path"}, "notifications.file")
    _reject_unknown(popup_data, {"duration_seconds"}, "notifications.popup")
    _reject_unknown(sound_data, {"duration_seconds"}, "notifications.sound")
    _reject_unknown(
        email_data,
        {
            "smtp_host",
            "smtp_port",
            "smtp_timeout_seconds",
            "aggregation_seconds",
            "username_env",
            "password_env",
            "from_address",
            "to_addresses",
            "use_tls",
            "failure_backoff_seconds",
        },
        "notifications.email",
    )
    username_env = _non_empty_string(
        email_data.get("username_env", "SMTP_USERNAME"),
        "notifications.email.username_env",
    )
    email = EmailConfig(
        smtp_host=_optional_string(email_data.get("smtp_host")) or os.environ.get("SMTP_HOST"),
        smtp_port=_integer_value(email_data.get("smtp_port", 587), "notifications.email.smtp_port"),
        smtp_timeout_seconds=_integer_value(
            email_data.get("smtp_timeout_seconds", 10), "notifications.email.smtp_timeout_seconds"
        ),
        alert_interval_seconds=_integer_value(
            email_data.get("aggregation_seconds", 60), "notifications.email.aggregation_seconds"
        ),
        username=os.environ.get(username_env),
        username_env=username_env,
        password_env=_non_empty_string(
            email_data.get("password_env", "SMTP_PASSWORD"),
            "notifications.email.password_env",
        ),
        from_addr=_optional_string(email_data.get("from_address")) or os.environ.get("ALERT_EMAIL_FROM"),
        to_addrs=_parse_recipients(email_data.get("to_addresses")),
        use_tls=_boolean_value(email_data.get("use_tls", True), "notifications.email.use_tls"),
        failure_backoff_seconds=_integer_value(
            email_data.get("failure_backoff_seconds", 300),
            "notifications.email.failure_backoff_seconds",
        ),
    )
    return NotifierConfig(
        channels=channels,
        popup=PopupConfig(
            duration_seconds=_integer_value(
                popup_data.get("duration_seconds", 2), "notifications.popup.duration_seconds"
            )
        ),
        sound=SoundConfig(
            duration_seconds=_integer_value(
                sound_data.get("duration_seconds", 2), "notifications.sound.duration_seconds"
            )
        ),
        email=email,
        alert_log_path=_non_empty_string(
            file_data.get("path", "logs/alerts.jsonl"),
            "notifications.file.path",
        ),
    )


def _parse_logging(data: dict[str, Any]) -> LoggingConfig:
    _reject_unknown(
        data,
        {"level", "directory", "filename", "max_bytes", "backup_count", "summary_interval_seconds"},
        "logging",
    )
    return LoggingConfig(
        level=_non_empty_string(data.get("level", "INFO"), "logging.level").upper(),
        log_dir=_non_empty_string(data.get("directory", "logs"), "logging.directory"),
        log_file=_non_empty_string(data.get("filename", "optionsentry.log"), "logging.filename"),
        max_bytes=_integer_value(data.get("max_bytes", 5_000_000), "logging.max_bytes"),
        backup_count=_integer_value(data.get("backup_count", 5), "logging.backup_count"),
        cycle_summary_interval_seconds=_integer_value(
            data.get("summary_interval_seconds", 60), "logging.summary_interval_seconds"
        ),
    )


def _parse_gui(data: dict[str, Any]) -> GuiConfig:
    _reject_unknown(data, {"active_alerts"}, "gui")
    active = _table(data.get("active_alerts"), "gui.active_alerts")
    _reject_unknown(active, {"auto_refresh", "refresh_interval_seconds"}, "gui.active_alerts")
    return GuiConfig(
        active_alerts=ActiveAlertsViewConfig(
            auto_refresh=_boolean_value(active.get("auto_refresh", True), "gui.active_alerts.auto_refresh"),
            refresh_interval_seconds=_integer_value(
                active.get("refresh_interval_seconds", 10), "gui.active_alerts.refresh_interval_seconds"
            ),
        )
    )


def _validate_config(
    runtime: RuntimeConfig,
    universe: UniverseConfig,
    backtest: BacktestConfig,
    tqsdk: TqSdkConfig,
    strategies: tuple[StrategyConfig, ...],
    notifier: NotifierConfig,
    logging_config: LoggingConfig,
    gui: GuiConfig,
) -> None:
    if runtime.mode not in {"live", "backtest"}:
        raise ConfigError("runtime.mode must be 'live' or 'backtest'.")
    if universe.mode not in {"all", "include"}:
        raise ConfigError("universe.mode must be 'all' or 'include'.")
    if universe.mode == "include" and not universe.include:
        raise ConfigError("universe.include is required when universe.mode='include'.")
    if universe.min_volume < 0 or universe.min_open_interest < 0:
        raise ConfigError("Universe liquidity thresholds must be non-negative.")
    if runtime.mode == "backtest" and (backtest.start_dt is None or backtest.end_dt is None):
        raise ConfigError("backtest.start_date and backtest.end_date are required in backtest mode.")
    if backtest.start_dt is not None and backtest.end_dt is not None and backtest.start_dt > backtest.end_dt:
        raise ConfigError("backtest.start_date must be on or before backtest.end_date.")
    if backtest.duration_seconds <= 0:
        raise ConfigError("backtest.kline_duration_seconds must be positive.")
    if runtime.mode == "backtest" and backtest.duration_seconds != 60:
        raise ConfigError("Backtest mode currently supports only 60-second K-lines.")
    if backtest.data_length <= 0 or backtest.initial_price_timeout_seconds <= 0:
        raise ConfigError("Backtest data_length and initialization_timeout_seconds must be positive.")
    if backtest.subscription_batch_size <= 0:
        raise ConfigError("backtest.subscription_batch_size must be positive.")
    if tqsdk.symbol_info_batch_size <= 0 or tqsdk.quote_subscription_batch_size <= 0:
        raise ConfigError("TqSdk batch sizes must be positive.")
    if logging_config.level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError("logging.level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")
    if logging_config.max_bytes <= 0 or logging_config.backup_count < 0:
        raise ConfigError("Logging size must be positive and backup_count non-negative.")
    if logging_config.cycle_summary_interval_seconds < 0:
        raise ConfigError("logging.summary_interval_seconds must be non-negative.")
    if not 1 <= notifier.popup.duration_seconds <= 3600:
        raise ConfigError("notifications.popup.duration_seconds must be between 1 and 3600.")
    if not 1 <= notifier.sound.duration_seconds <= 3600:
        raise ConfigError("notifications.sound.duration_seconds must be between 1 and 3600.")
    if notifier.email.alert_interval_seconds < 0:
        raise ConfigError("notifications.email.aggregation_seconds must be non-negative.")
    if not 1 <= notifier.email.smtp_port <= 65535:
        raise ConfigError("notifications.email.smtp_port must be between 1 and 65535.")
    if notifier.email.smtp_timeout_seconds <= 0:
        raise ConfigError("notifications.email.smtp_timeout_seconds must be positive.")
    if notifier.email.failure_backoff_seconds < 0:
        raise ConfigError("notifications.email.failure_backoff_seconds must be non-negative.")
    if gui.active_alerts.refresh_interval_seconds not in ACTIVE_ALERT_REFRESH_INTERVALS:
        raise ConfigError(
            "gui.active_alerts.refresh_interval_seconds must be one of 10, 30, 60, 180, 300, or 600."
        )
    if not strategies:
        raise ConfigError("At least one [[strategies]] entry is required.")


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"Unknown {path} field(s): {', '.join(unknown)}")


def _table(value: Any, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be a table.")
    return value


def _integer_value(value: Any, path: str) -> int:
    if value is None or isinstance(value, bool):
        raise ConfigError(f"{path} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ConfigError(f"{path} must be an integer.")


def _boolean_value(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{path} must be a boolean.")
    return value


def _non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path} must be a non-empty string.")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError("Optional string configuration values must be strings.")
    return value.strip() or None


def _tuple_of_str(value: Any, path: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConfigError(f"{path} must be an array of strings.")
    return tuple(item for item in value if item)


def _optional_date(value: Any, path: str) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ConfigError(f"{path} must be an ISO date.") from exc
    raise ConfigError(f"{path} must be a date.")


def _parse_recipients(value: Any) -> tuple[str, ...]:
    if value is None:
        value = [item.strip() for item in os.environ.get("ALERT_EMAIL_TO", "").split(",") if item.strip()]
    return _tuple_of_str(value, "notifications.email.to_addresses")
