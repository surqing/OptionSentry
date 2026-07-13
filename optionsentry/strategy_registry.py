from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:
    from optionsentry.config import StrategyConfig
    from optionsentry.strategy_base import Strategy


BUILTIN_STRATEGY_PACKAGE = "optionsentry.strategy_types"
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {}
_discovered_packages: set[str] = set()

_StrategyType = TypeVar("_StrategyType", bound=type)


@dataclass(frozen=True)
class ParsedAlertKey:
    strategy_type: str
    fields: dict[str, str]


def register_strategy(type_name: str) -> Callable[[_StrategyType], _StrategyType]:
    def decorator(cls: _StrategyType) -> _StrategyType:
        existing = STRATEGY_REGISTRY.get(type_name)
        if existing is not None and existing is not cls:
            raise ValueError(f"Duplicate strategy type: {type_name}")
        cls.type_name = type_name
        STRATEGY_REGISTRY[type_name] = cls
        return cls

    return decorator


def supported_strategy_types() -> tuple[str, ...]:
    _discover_strategy_package(BUILTIN_STRATEGY_PACKAGE)
    return tuple(cls.type_name for cls in _sorted_strategy_classes())


def get_strategy_class(type_name: str) -> type[Strategy]:
    _discover_strategy_package(BUILTIN_STRATEGY_PACKAGE)
    try:
        return STRATEGY_REGISTRY[type_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported strategy type: {type_name}") from exc


def create_strategy(config: StrategyConfig) -> Strategy:
    return get_strategy_class(config.type).from_config(config)


def parse_alert_key(key: str) -> ParsedAlertKey | None:
    _discover_strategy_package(BUILTIN_STRATEGY_PACKAGE)
    for cls in _sorted_strategy_classes():
        fields = cls.parse_key(key)
        if fields is not None:
            return ParsedAlertKey(strategy_type=cls.type_name, fields=fields)
    return None


def _sorted_strategy_classes() -> tuple[type[Strategy], ...]:
    return tuple(
        sorted(
            STRATEGY_REGISTRY.values(),
            key=lambda cls: (cls.display_order, cls.type_name),
        )
    )


def _discover_strategy_package(package_name: str) -> None:
    if package_name in _discovered_packages:
        return
    package = importlib.import_module(package_name)
    module_names = sorted(
        module_info.name
        for module_info in pkgutil.iter_modules(package.__path__)
        if not module_info.name.startswith("_")
    )
    for module_name in module_names:
        importlib.import_module(f"{package_name}.{module_name}")
    _discovered_packages.add(package_name)
