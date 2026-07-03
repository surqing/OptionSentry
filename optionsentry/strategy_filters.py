from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable

from optionsentry.config import ConfigError
from optionsentry.models import InstrumentMeta, Universe
from optionsentry.strategies import Strategy


@dataclass(frozen=True)
class FilterContext:
    universe: Universe

    def underlying(self, option: InstrumentMeta) -> InstrumentMeta | None:
        if not option.underlying_symbol:
            return None
        meta = self.universe.instruments.get(option.underlying_symbol)
        if meta is not None and meta.is_future:
            return meta
        return None


def apply_strategy_filter(
    strategy: Strategy,
    universe: Universe,
    config_dir: str | Path,
    logger: logging.Logger,
) -> Universe:
    script = getattr(strategy, "filter_script", None)
    if not script:
        return universe
    scope = getattr(strategy, "filter_scope", "options")
    if scope != "options":
        raise ConfigError(f"Strategy filter_scope must be 'options': {strategy.name}")
    script_path = _resolve_script_path(script, config_dir)
    function_name = getattr(strategy, "filter_function", "accept") or "accept"
    accept = _load_filter_function(script_path, function_name, strategy.name)
    ctx = FilterContext(universe=universe)
    kept_options: list[InstrumentMeta] = []
    missing_underlyings: set[str] = set()
    for option in universe.options:
        try:
            result = accept(option, ctx)
        except Exception as exc:
            raise ConfigError(
                f"Strategy filter failed for {strategy.name} option {option.symbol}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(result, bool):
            raise ConfigError(
                f"Strategy filter {strategy.name} returned {type(result).__name__} "
                f"for {option.symbol}; expected bool."
            )
        if not result:
            continue
        underlying = ctx.underlying(option)
        if underlying is None:
            missing_underlyings.add(option.underlying_symbol or option.symbol)
            continue
        kept_options.append(option)

    if missing_underlyings:
        logger.warning(
            "Strategy %s filter kept options with missing futures underlyings; "
            "dropped=%s first=%s",
            strategy.name,
            len(missing_underlyings),
            sorted(missing_underlyings)[:20],
        )

    instruments: dict[str, InstrumentMeta] = {}
    for option in kept_options:
        underlying = ctx.underlying(option)
        if underlying is None:
            continue
        instruments[underlying.symbol] = underlying
        instruments[option.symbol] = option
    filtered = Universe(instruments=instruments, requested_symbols=tuple(sorted(instruments)))
    logger.info(
        "Applied strategy filter: strategy=%s script=%s options %s -> %s futures=%s",
        strategy.name,
        script_path,
        len(universe.options),
        len(filtered.options),
        len(filtered.futures),
    )
    return filtered


def _resolve_script_path(script: str, config_dir: str | Path) -> Path:
    script_path = Path(script).expanduser()
    if not script_path.is_absolute():
        script_path = Path(config_dir) / script_path
    script_path = script_path.resolve()
    if not script_path.exists():
        raise ConfigError(f"Strategy filter script not found: {script_path}")
    if not script_path.is_file():
        raise ConfigError(f"Strategy filter script is not a file: {script_path}")
    return script_path


def _load_filter_function(script_path: Path, function_name: str, strategy_name: str) -> Callable[[InstrumentMeta, FilterContext], bool]:
    module = _load_module(script_path, strategy_name)
    accept = getattr(module, function_name, None)
    if accept is None:
        raise ConfigError(f"Strategy filter function not found: {function_name} in {script_path}")
    if not callable(accept):
        raise ConfigError(f"Strategy filter function is not callable: {function_name} in {script_path}")
    return accept


def _load_module(script_path: Path, strategy_name: str) -> ModuleType:
    module_name = f"_optionsentry_filter_{abs(hash((str(script_path), strategy_name)))}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"Unable to load strategy filter script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ConfigError(
            f"Strategy filter script import failed: {script_path}: {type(exc).__name__}: {exc}"
        ) from exc
    return module
