from __future__ import annotations

from copy import deepcopy

from optionsentry.config import parse_config
from optionsentry.models import InstrumentMeta, MarketSnapshot, Universe


def sample_universe() -> Universe:
    instruments = {
        "SHFE.au2608": InstrumentMeta("SHFE.au2608", "FUTURE"),
        "SHFE.au2608C600": InstrumentMeta(
            "SHFE.au2608C600",
            "OPTION",
            underlying_symbol="SHFE.au2608",
            strike_price=600.0,
            option_class="CALL",
            exercise_year=2026,
            exercise_month=8,
        ),
        "SHFE.au2608P600": InstrumentMeta(
            "SHFE.au2608P600",
            "OPTION",
            underlying_symbol="SHFE.au2608",
            strike_price=600.0,
            option_class="PUT",
            exercise_year=2026,
            exercise_month=8,
        ),
        "SHFE.au2608C620": InstrumentMeta(
            "SHFE.au2608C620",
            "OPTION",
            underlying_symbol="SHFE.au2608",
            strike_price=620.0,
            option_class="CALL",
            exercise_year=2026,
            exercise_month=8,
        ),
        "SHFE.au2608P620": InstrumentMeta(
            "SHFE.au2608P620",
            "OPTION",
            underlying_symbol="SHFE.au2608",
            strike_price=620.0,
            option_class="PUT",
            exercise_year=2026,
            exercise_month=8,
        ),
    }
    return Universe(instruments=instruments)


def snapshot(universe: Universe, prices: dict[str, float], timestamp: str = "2026-01-02 09:31:00") -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=timestamp,
        prices=prices,
        changed_symbols=set(prices),
        universe=universe,
    )


def parse_test_config(data: dict[str, object]):
    """Translate concise legacy-shaped fixtures into the strict schema used by production."""
    modern = deepcopy(data)
    modern["schema_version"] = 1

    runtime = modern.get("runtime")
    if isinstance(runtime, dict):
        runtime.pop("price_basis", None)

    universe = modern.get("universe")
    if isinstance(universe, dict):
        if universe.get("mode") == "指定模式":
            universe["mode"] = "include"
        for old, new in (("only_do", "include"), ("not_do", "exclude"), ("exchange_ids", "exchanges")):
            if old in universe:
                universe[new] = universe.pop(old)
        for old in ("onlyDo", "notDo", "exclude_do", "excludeDo"):
            universe.pop(old, None)

    datasource = modern.pop("datasource", None)
    if isinstance(datasource, dict):
        tqsdk = dict(datasource.get("tqsdk", {}))
        tqsdk.pop("username", None)
        tqsdk.pop("password", None)
        modern["data_source"] = {"provider": "tqsdk", "tqsdk": tqsdk}

    strategies = modern.get("strategies")
    if isinstance(strategies, list):
        for index, strategy in enumerate(strategies, start=1):
            if not isinstance(strategy, dict):
                continue
            strategy_type = str(strategy.get("type", "strategy"))
            strategy.setdefault("id", f"{strategy_type}_{index}")
            strategy["enabled"] = strategy.pop("selected", True)
            parameters = strategy.get("parameters")
            if not isinstance(parameters, dict):
                parameters = {}
                for key in ("min_value", "max_value"):
                    if key in strategy:
                        parameters[key] = strategy.pop(key)
                strategy["parameters"] = parameters
            script = strategy.pop("filter_script", None)
            entrypoint = strategy.pop("filter_function", "accept")
            strategy.pop("filter_scope", None)
            if script:
                strategy["filter"] = {"script": script, "entrypoint": entrypoint}

    notifier = modern.pop("notifier", None)
    if isinstance(notifier, dict):
        kind = notifier.pop("kind", None)
        channels = notifier.setdefault("channels", {})
        if kind == "console" and not channels:
            channels.update({"file": True, "email": False})
        elif kind == "email" and not channels:
            channels.update({"file": True, "email": True})
        path = notifier.pop("alert_log_path", None)
        if path:
            notifier["file"] = {"path": path}
        email = notifier.get("email")
        if isinstance(email, dict):
            renames = {
                "alert_interval_seconds": "aggregation_seconds",
                "from_addr": "from_address",
                "to_addrs": "to_addresses",
            }
            for old, new in renames.items():
                if old in email:
                    email[new] = email.pop(old)
            email.pop("username", None)
            email.pop("password", None)
        modern["notifications"] = notifier

    logging_data = modern.get("logging")
    if isinstance(logging_data, dict):
        for old, new in (
            ("log_dir", "directory"),
            ("log_file", "filename"),
            ("cycle_summary_interval_seconds", "summary_interval_seconds"),
        ):
            if old in logging_data:
                logging_data[new] = logging_data.pop(old)

    backtest = modern.get("backtest")
    if isinstance(backtest, dict):
        for old, new in (
            ("start_dt", "start_date"),
            ("end_dt", "end_date"),
            ("duration_seconds", "kline_duration_seconds"),
            ("initial_price_timeout_seconds", "initialization_timeout_seconds"),
        ):
            if old in backtest:
                backtest[new] = backtest.pop(old)

    return parse_config(modern)
