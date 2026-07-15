from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Iterable, Literal, Mapping, TypeVar

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


ParameterKind = Literal["float", "int", "bool", "string", "enum"]


@dataclass(frozen=True)
class StrategyParameterSpec:
    key: str
    label: str
    kind: ParameterKind
    default: Any = None
    required: bool = True
    minimum: float | int | None = None
    maximum: float | int | None = None
    choices: tuple[str, ...] = ()
    choice_labels: tuple[str, ...] = ()
    help_text: str = ""


@dataclass(frozen=True)
class DataRequirements:
    quote_fields: frozenset[str] = frozenset({"last_price"})
    kline_durations: tuple[int, ...] = ()
    option_greeks: bool = False

    def unsupported_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        unsupported_quote_fields = sorted(self.quote_fields - {"last_price"})
        if unsupported_quote_fields:
            reasons.append(f"quote fields: {', '.join(unsupported_quote_fields)}")
        if self.kline_durations:
            reasons.append(f"K-line durations: {self.kline_durations}")
        if self.option_greeks:
            reasons.append("option Greeks")
        return tuple(reasons)


class CompiledStrategy(ABC):
    strategy_id: str
    name: str
    strategy_type: str
    backtest_group: str
    data_requirements: DataRequirements = DataRequirements()

    @property
    @abstractmethod
    def condition_count(self) -> int:
        ...

    @property
    @abstractmethod
    def required_symbols(self) -> frozenset[str]:
        ...

    @abstractmethod
    def evaluate(
        self,
        snapshot: MarketSnapshot,
        changed_symbols: set[str] | None = None,
    ) -> list[ConditionEvaluation]:
        ...


@dataclass(frozen=True)
class StrategyCompilation:
    strategy_id: str
    strategy_type: str
    name: str
    units: tuple[CompiledStrategy, ...]

    @property
    def condition_count(self) -> int:
        return sum(unit.condition_count for unit in self.units)

    @property
    def required_symbols(self) -> frozenset[str]:
        return frozenset(symbol for unit in self.units for symbol in unit.required_symbols)

    def evaluate(
        self,
        snapshot: MarketSnapshot,
        changed_symbols: set[str] | None = None,
    ) -> list[ConditionEvaluation]:
        evaluations: list[ConditionEvaluation] = []
        for unit in self.units:
            evaluations.extend(unit.evaluate(snapshot, changed_symbols))
        return evaluations


class Strategy(ABC):
    type_name: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    display_order: ClassVar[int] = 100
    metric_columns: ClassVar[tuple[MetricColumn, ...]] = ()
    parameter_specs: ClassVar[tuple[StrategyParameterSpec, ...]] = ()

    id: str
    name: str
    filter_script: str | None = None
    filter_function: str = "accept"
    filter_scope: str = "options"

    @classmethod
    def default_parameters(cls) -> dict[str, Any]:
        return {spec.key: spec.default for spec in cls.parameter_specs}

    @classmethod
    def validate_parameters(cls, parameters: Mapping[str, Any]) -> dict[str, Any]:
        return normalize_strategy_parameters(cls.type_name, cls.parameter_specs, parameters)

    @classmethod
    def from_config(cls, config: StrategyConfig) -> Strategy:
        parameters = cls.validate_parameters(config.parameters)
        return cls(
            id=config.id,
            name=config.name or cls.display_name,
            filter_script=config.filter_script,
            filter_function=config.filter_function,
            filter_scope=config.filter_scope,
            **parameters,
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

    @abstractmethod
    def compile(self, universe: Universe) -> StrategyCompilation:
        ...


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


def validate_alert_range(strategy_type: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(parameters)
    min_value = float(normalized["min_value"])
    max_value = float(normalized["max_value"])
    if min_value >= max_value:
        raise ValueError(f"Strategy {strategy_type} min_value must be less than max_value.")
    return normalized


def normalize_strategy_parameters(
    strategy_type: str,
    specs: tuple[StrategyParameterSpec, ...],
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    spec_by_key = {spec.key: spec for spec in specs}
    unknown = sorted(set(parameters) - set(spec_by_key))
    if unknown:
        raise ValueError(f"Strategy {strategy_type} has unknown parameters: {', '.join(unknown)}")

    normalized: dict[str, Any] = {}
    for spec in specs:
        if spec.key in parameters:
            value = parameters[spec.key]
        elif spec.required:
            raise ValueError(f"Strategy {strategy_type} requires parameter: {spec.key}")
        else:
            value = spec.default
        normalized[spec.key] = _normalize_parameter_value(strategy_type, spec, value)
    return normalized


def _normalize_parameter_value(
    strategy_type: str,
    spec: StrategyParameterSpec,
    value: Any,
) -> Any:
    label = f"Strategy {strategy_type} parameter {spec.key}"
    if spec.kind == "float":
        if isinstance(value, bool):
            raise ValueError(f"{label} must be a number.")
        try:
            normalized: Any = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a number.") from exc
        if math.isnan(normalized):
            raise ValueError(f"{label} cannot be NaN.")
    elif spec.kind == "int":
        if isinstance(value, bool):
            raise ValueError(f"{label} must be an integer.")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be an integer.") from exc
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise ValueError(f"{label} must be an integer.")
        normalized = int(numeric)
    elif spec.kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{label} must be a boolean.")
        normalized = value
    elif spec.kind == "string":
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a string.")
        normalized = value
    elif spec.kind == "enum":
        if not isinstance(value, str) or value not in spec.choices:
            choices = ", ".join(spec.choices)
            raise ValueError(f"{label} must be one of: {choices}.")
        normalized = value
    else:  # pragma: no cover - registration rejects unsupported kinds
        raise ValueError(f"{label} uses unsupported kind: {spec.kind}")

    if spec.minimum is not None and normalized < spec.minimum:
        raise ValueError(f"{label} must be at least {spec.minimum}.")
    if spec.maximum is not None and normalized > spec.maximum:
        raise ValueError(f"{label} must be at most {spec.maximum}.")
    return normalized
