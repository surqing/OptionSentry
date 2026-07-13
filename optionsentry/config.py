from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from optionsentry.symbols import normalize_symbols


class ConfigError(ValueError):
    pass


ACTIVE_ALERT_REFRESH_INTERVALS = frozenset({10, 30, 60, 180, 300, 600})


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str = "live"
    price_basis: str = "last"
    alert_on_first_match: bool = False


@dataclass(frozen=True)
class UniverseConfig:
    mode: str = "all"
    only_do: tuple[str, ...] = ()
    not_do: tuple[str, ...] = ()
    exchange_ids: tuple[str, ...] = ()
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
    username: str | None = None
    password: str | None = None
    username_env: str = "TQSDK_USERNAME"
    password_env: str = "TQSDK_PASSWORD"
    symbol_info_batch_size: int = 500
    quote_subscription_batch_size: int = 500


@dataclass(frozen=True)
class StrategyConfig:
    type: str
    min_value: float
    max_value: float
    name: str | None = None
    selected: bool = True
    filter_script: str | None = None
    filter_function: str = "accept"
    filter_scope: str = "options"


def strategy_type_display_name(strategy_type: str) -> str:
    from optionsentry.strategy_registry import get_strategy_class

    try:
        return get_strategy_class(strategy_type).display_name
    except ValueError:
        return strategy_type


def strategy_display_name(strategy: StrategyConfig) -> str:
    if strategy.name:
        return strategy.name
    return strategy_type_display_name(strategy.type)


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
class NotifierChannelsConfig:
    popup: bool = False
    sound: bool = False
    file: bool = True
    email: bool = True


@dataclass(frozen=True)
class PopupConfig:
    duration_seconds: int = 2


@dataclass(frozen=True)
class SoundConfig:
    duration_seconds: int = 2


@dataclass(frozen=True)
class NotifierConfig:
    kind: str | None = None
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
    runtime: RuntimeConfig
    universe: UniverseConfig
    backtest: BacktestConfig
    tqsdk: TqSdkConfig
    strategies: tuple[StrategyConfig, ...]
    notifier: NotifierConfig
    logging: LoggingConfig
    gui: GuiConfig = field(default_factory=GuiConfig)

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
    notifier = _parse_notifier(data.get("notifier", {}), data.get("notifier.email", {}), runtime.mode)
    logging_config = _parse_logging(data.get("logging", {}))
    gui = _parse_gui(data.get("gui", {}))
    _validate_config(runtime, universe, backtest, strategies, notifier, logging_config, gui)
    return AppConfig(
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
    return RuntimeConfig(
        mode=str(data.get("mode", "live")),
        price_basis=str(data.get("price_basis", "last")),
        alert_on_first_match=bool(data.get("alert_on_first_match", False)),
    )


def _parse_universe(data: dict[str, Any]) -> UniverseConfig:
    return UniverseConfig(
        mode=str(data.get("mode", "all")),
        only_do=normalize_symbols(_tuple_of_str(_first_present(data, "only_do", "onlyDo", default=()))),
        not_do=normalize_symbols(
            _tuple_of_str(_first_present(data, "not_do", "notDo", "exclude_do", "excludeDo", default=()))
        ),
        exchange_ids=normalize_symbols(_tuple_of_str(data.get("exchange_ids", ()))),
        min_volume=_integer_value(data.get("min_volume", 0), "universe.min_volume"),
        min_open_interest=_integer_value(data.get("min_open_interest", 0), "universe.min_open_interest"),
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
        strategy_type = str(item["type"])
        strategies.extend(
            _parse_strategy_item(
                strategy_type,
                item,
                name=str(item["name"]) if item.get("name") is not None else None,
                selected=bool(item.get("selected", True)),
            )
        )
    return tuple(strategies)


def _parse_strategy_item(
    strategy_type: str,
    item: dict[str, Any],
    name: str | None,
    selected: bool,
) -> tuple[StrategyConfig, ...]:
    from optionsentry.strategy_registry import get_strategy_class

    try:
        strategy_class = get_strategy_class(strategy_type)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

    explicit_range: tuple[float, float] | None = None
    threshold: float | None = None
    if "min_value" in item or "max_value" in item:
        if "min_value" not in item or "max_value" not in item:
            raise ConfigError(f"Strategy {strategy_type} requires both min_value and max_value.")
        explicit_range = (
            _float_value(item["min_value"], f"Strategy {strategy_type} min_value"),
            _float_value(item["max_value"], f"Strategy {strategy_type} max_value"),
        )
    else:
        if "threshold" not in item:
            raise ConfigError(f"Strategy {strategy_type} requires min_value and max_value.")
        threshold = _float_value(item["threshold"], f"Strategy {strategy_type} threshold")
        if threshold < 0:
            raise ConfigError(f"Strategy threshold must be non-negative: {strategy_type}")

    ranges = strategy_class.expand_ranges(explicit_range=explicit_range, threshold=threshold)
    filter_script = _optional_str(item.get("filter_script"))
    filter_function = str(item.get("filter_function", "accept") or "accept")
    filter_scope = str(item.get("filter_scope", "options") or "options")
    return tuple(
        StrategyConfig(
            type=strategy_type,
            min_value=min_value,
            max_value=max_value,
            name=name,
            selected=selected,
            filter_script=filter_script,
            filter_function=filter_function,
            filter_scope=filter_scope,
        )
        for min_value, max_value in ranges
    )


def _parse_notifier(
    data: dict[str, Any],
    flat_email_data: dict[str, Any],
    runtime_mode: str,
) -> NotifierConfig:
    legacy_kind = str(data["kind"]) if data.get("kind") else None
    channels = _parse_notifier_channels(data.get("channels"), legacy_kind, runtime_mode)
    popup_data = data.get("popup", {}) or {}
    sound_data = data.get("sound", {}) or {}
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
        kind=legacy_kind,
        channels=channels,
        popup=PopupConfig(duration_seconds=int(popup_data.get("duration_seconds", 2))),
        sound=SoundConfig(duration_seconds=int(sound_data.get("duration_seconds", 2))),
        email=email,
        alert_log_path=str(data.get("alert_log_path", "logs/alerts.jsonl")),
    )


def _parse_notifier_channels(
    data: dict[str, Any] | None,
    legacy_kind: str | None,
    runtime_mode: str,
) -> NotifierChannelsConfig:
    default_email = runtime_mode == "live"
    if data is not None:
        return NotifierChannelsConfig(
            popup=bool(data.get("popup", False)),
            sound=bool(data.get("sound", False)),
            file=bool(data.get("file", True)),
            email=bool(data.get("email", default_email)),
        )
    if legacy_kind is None:
        return NotifierChannelsConfig(file=True, email=default_email)
    if legacy_kind == "email":
        return NotifierChannelsConfig(file=True, email=True)
    if legacy_kind == "console":
        return NotifierChannelsConfig(file=True, email=False)
    raise ConfigError(f"Unsupported notifier kind: {legacy_kind}")


def _parse_logging(data: dict[str, Any]) -> LoggingConfig:
    return LoggingConfig(
        level=str(data.get("level", "INFO")),
        log_dir=str(data.get("log_dir", "logs")),
        log_file=str(data.get("log_file", "optionsentry.log")),
        max_bytes=int(data.get("max_bytes", 5_000_000)),
        backup_count=int(data.get("backup_count", 5)),
        cycle_summary_interval_seconds=int(data.get("cycle_summary_interval_seconds", 60)),
    )


def _parse_gui(data: dict[str, Any]) -> GuiConfig:
    active_alerts_data = data.get("active_alerts", {}) or {}
    return GuiConfig(
        active_alerts=ActiveAlertsViewConfig(
            auto_refresh=bool(active_alerts_data.get("auto_refresh", True)),
            refresh_interval_seconds=int(active_alerts_data.get("refresh_interval_seconds", 10)),
        )
    )


def _validate_config(
    runtime: RuntimeConfig,
    universe: UniverseConfig,
    backtest: BacktestConfig,
    strategies: tuple[StrategyConfig, ...],
    notifier: NotifierConfig,
    logging_config: LoggingConfig,
    gui: GuiConfig,
) -> None:
    from optionsentry.strategy_registry import supported_strategy_types

    if runtime.mode not in {"live", "backtest"}:
        raise ConfigError("runtime.mode must be 'live' or 'backtest'.")
    if runtime.price_basis != "last":
        raise ConfigError("Only runtime.price_basis='last' is supported in this version.")
    if universe.mode not in {"all", "指定模式"}:
        raise ConfigError("universe.mode must be 'all' or '指定模式'.")
    if universe.mode == "指定模式" and not universe.only_do:
        raise ConfigError("universe.only_do is required when universe.mode='指定模式'.")
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
    if not 1 <= notifier.popup.duration_seconds <= 3600:
        raise ConfigError("notifier.popup.duration_seconds must be between 1 and 3600.")
    if not 1 <= notifier.sound.duration_seconds <= 3600:
        raise ConfigError("notifier.sound.duration_seconds must be between 1 and 3600.")
    if gui.active_alerts.refresh_interval_seconds not in ACTIVE_ALERT_REFRESH_INTERVALS:
        raise ConfigError(
            "gui.active_alerts.refresh_interval_seconds must be one of "
            "10, 30, 60, 180, 300, or 600."
        )
    if not strategies:
        raise ConfigError("At least one [[strategies]] entry is required.")
    for strategy in strategies:
        if strategy.type not in supported_strategy_types():
            raise ConfigError(f"Unsupported strategy type: {strategy.type}")
        if strategy.filter_scope != "options":
            raise ConfigError(f"Strategy filter_scope must be 'options': {strategy.type}")
        if not strategy.filter_function.strip():
            raise ConfigError(f"Strategy filter_function cannot be empty: {strategy.type}")
        if math.isnan(strategy.min_value) or math.isnan(strategy.max_value):
            raise ConfigError(f"Strategy range cannot contain NaN: {strategy.type}")
        if strategy.min_value >= strategy.max_value:
            raise ConfigError(f"Strategy min_value must be less than max_value: {strategy.type}")


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _first_present(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return default


def _integer_value(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{name} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer.") from exc
    if not number.is_integer():
        raise ConfigError(f"{name} must be an integer.")
    return int(number)


def _float_value(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number.") from exc


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
