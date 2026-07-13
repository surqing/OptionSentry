from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Iterable, TypeVar

from optionsentry.models import ConditionEvaluation, MarketSnapshot, Universe
from optionsentry.symbols import normalize_symbols

if TYPE_CHECKING:
    from optionsentry.config import StrategyConfig


@dataclass(frozen=True)
class MetricColumn:
    name: str
    width: int = 105


@dataclass(frozen=True)
class EmailPresentation:
    monitor: str = "-"
    structure: str = "-"
    strike: str = "-"
    metric_label: str = "当前指标值"


class CompiledStrategy:
    name: str

    @property
    def condition_count(self) -> int:
        raise NotImplementedError

    def evaluate(
        self,
        snapshot: MarketSnapshot,
        changed_symbols: set[str] | None = None,
    ) -> list[ConditionEvaluation]:
        raise NotImplementedError


class Strategy:
    type_name: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    display_order: ClassVar[int] = 100
    metric_columns: ClassVar[tuple[MetricColumn, ...]] = ()

    name: str
    filter_script: str | None = None
    filter_function: str = "accept"
    filter_scope: str = "options"

    @classmethod
    def default_range(cls) -> tuple[float, float]:
        return 0.01, math.inf

    @classmethod
    def expand_ranges(
        cls,
        *,
        explicit_range: tuple[float, float] | None,
        threshold: float | None,
    ) -> tuple[tuple[float, float], ...]:
        if explicit_range is not None:
            return (explicit_range,)
        if threshold is None:
            raise ValueError(f"Strategy {cls.type_name} requires min_value and max_value.")
        return ((-math.inf, threshold),)

    @classmethod
    def from_config(cls, config: StrategyConfig) -> Strategy:
        return cls(
            min_value=config.min_value,
            max_value=config.max_value,
            name=config.name or cls.display_name,
            filter_script=config.filter_script,
            filter_function=config.filter_function,
            filter_scope=config.filter_scope,
        )

    @classmethod
    def parse_key(cls, key: str) -> dict[str, str] | None:
        return None

    @classmethod
    def email_presentation(cls, fields: dict[str, str]) -> EmailPresentation:
        return EmailPresentation()

    @classmethod
    def row_background_color(cls, evaluation: ConditionEvaluation) -> str | None:
        return None

    def evaluate(self, snapshot: MarketSnapshot, universe: Universe) -> list[ConditionEvaluation]:
        raise NotImplementedError

    def compile(self, universe: Universe) -> CompiledStrategy:
        return FullScanCompiledStrategy(strategy=self)


@dataclass
class FullScanCompiledStrategy(CompiledStrategy):
    strategy: Strategy

    @property
    def name(self) -> str:
        return self.strategy.name

    @property
    def condition_count(self) -> int:
        return 0

    def evaluate(
        self,
        snapshot: MarketSnapshot,
        changed_symbols: set[str] | None = None,
    ) -> list[ConditionEvaluation]:
        return self.strategy.evaluate(snapshot, snapshot.universe)


_Condition = TypeVar("_Condition")


def add_condition(
    conditions: list[_Condition],
    condition_ids_by_symbol: dict[str, set[int]],
    condition: _Condition,
    symbols: Iterable[str],
) -> None:
    condition_id = len(conditions)
    conditions.append(condition)
    for symbol in symbols:
        condition_ids_by_symbol.setdefault(symbol, set()).add(condition_id)


def affected_condition_ids(
    condition_ids_by_symbol: dict[str, set[int]],
    changed_symbols: set[str] | None,
    condition_count: int,
) -> Iterable[int]:
    if changed_symbols is None:
        return range(condition_count)
    condition_ids: set[int] = set()
    for symbol in normalize_symbols(changed_symbols):
        condition_ids.update(condition_ids_by_symbol.get(symbol, ()))
    return sorted(condition_ids)


def valid_price(value: float | None) -> bool:
    if value is None:
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric)


def in_alert_range(value: float, min_value: float, max_value: float) -> bool:
    return min_value < value < max_value
