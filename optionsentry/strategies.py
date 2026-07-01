from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from optionsentry.config import StrategyConfig, strategy_display_name
from optionsentry.models import ConditionEvaluation, InstrumentMeta, MarketSnapshot, Universe
from optionsentry.symbols import normalize_symbols


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
    name: str

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


@dataclass
class CPComboStrategy(Strategy):
    threshold: float
    name: str = "cp_combo"

    def evaluate(self, snapshot: MarketSnapshot, universe: Universe) -> list[ConditionEvaluation]:
        return self.compile(universe).evaluate(snapshot)

    def compile(self, universe: Universe) -> CompiledStrategy:
        return _compile_cp_combo(self, universe)


@dataclass
class AbsSpreadStrategy(Strategy):
    threshold: float
    name: str = "abs_spread"

    def evaluate(self, snapshot: MarketSnapshot, universe: Universe) -> list[ConditionEvaluation]:
        return self.compile(universe).evaluate(snapshot)

    def compile(self, universe: Universe) -> CompiledStrategy:
        return _compile_abs_spread(self, universe)


@dataclass(frozen=True)
class _CPComboCondition:
    key: str
    group_text: str
    strike: float
    call_symbol: str
    put_symbol: str
    underlying_symbol: str


@dataclass
class _CompiledCPComboStrategy(CompiledStrategy):
    name: str
    threshold: float
    conditions: tuple[_CPComboCondition, ...]
    condition_ids_by_symbol: dict[str, set[int]]

    @property
    def condition_count(self) -> int:
        return len(self.conditions)

    def evaluate(
        self,
        snapshot: MarketSnapshot,
        changed_symbols: set[str] | None = None,
    ) -> list[ConditionEvaluation]:
        evaluations: list[ConditionEvaluation] = []
        for condition_id in _affected_condition_ids(
            self.condition_ids_by_symbol,
            changed_symbols,
            self.condition_count,
        ):
            condition = self.conditions[condition_id]
            future_price = snapshot.prices.get(condition.underlying_symbol)
            if not _valid_price(future_price) or future_price <= 0:
                continue
            call_price = snapshot.prices.get(condition.call_symbol)
            put_price = snapshot.prices.get(condition.put_symbol)
            if not (_valid_price(call_price) and _valid_price(put_price)):
                continue
            deviation = call_price - put_price + condition.strike - future_price
            value = deviation / future_price
            active = abs(deviation) > self.threshold * future_price
            symbols = (condition.call_symbol, condition.put_symbol, condition.underlying_symbol)
            evaluations.append(
                ConditionEvaluation(
                    key=condition.key,
                    strategy_name=self.name,
                    active=active,
                    value=value,
                    threshold=self.threshold,
                    symbols=symbols,
                    message=(
                        f"{self.name} {condition.group_text} K={_format_float(condition.strike)} "
                        f"value={value:.8f} threshold={self.threshold:.8f} "
                        f"symbols={','.join(symbols)}"
                    ),
                )
            )
        return evaluations


@dataclass(frozen=True)
class _AbsSpreadCondition:
    key: str
    group_text: str
    option_class: str
    first_symbol: str
    second_symbol: str
    first_strike: float
    second_strike: float


@dataclass
class _CompiledAbsSpreadStrategy(CompiledStrategy):
    name: str
    threshold: float
    conditions: tuple[_AbsSpreadCondition, ...]
    condition_ids_by_symbol: dict[str, set[int]]

    @property
    def condition_count(self) -> int:
        return len(self.conditions)

    def evaluate(
        self,
        snapshot: MarketSnapshot,
        changed_symbols: set[str] | None = None,
    ) -> list[ConditionEvaluation]:
        evaluations: list[ConditionEvaluation] = []
        for condition_id in _affected_condition_ids(
            self.condition_ids_by_symbol,
            changed_symbols,
            self.condition_count,
        ):
            condition = self.conditions[condition_id]
            first_price = snapshot.prices.get(condition.first_symbol)
            second_price = snapshot.prices.get(condition.second_symbol)
            if not (_valid_price(first_price) and _valid_price(second_price)):
                continue
            value = abs(first_price - second_price) / abs(condition.first_strike - condition.second_strike)
            active = value < self.threshold
            symbols = (condition.first_symbol, condition.second_symbol)
            evaluations.append(
                ConditionEvaluation(
                    key=condition.key,
                    strategy_name=self.name,
                    active=active,
                    value=value,
                    threshold=self.threshold,
                    symbols=symbols,
                    message=(
                        f"{self.name} {condition.group_text} {condition.option_class} "
                        f"{_format_float(condition.first_strike)}-{_format_float(condition.second_strike)} "
                        f"value={value:.8f} threshold={self.threshold:.8f} "
                        f"symbols={','.join(symbols)}"
                    ),
                )
            )
        return evaluations


def build_strategy(config: StrategyConfig) -> Strategy:
    name = strategy_display_name(config)
    if config.type == "cp_combo":
        return CPComboStrategy(threshold=config.threshold, name=name)
    if config.type == "abs_spread":
        return AbsSpreadStrategy(threshold=config.threshold, name=name)
    raise ValueError(f"Unsupported strategy type: {config.type}")


def _compile_cp_combo(strategy: CPComboStrategy, universe: Universe) -> _CompiledCPComboStrategy:
    conditions: list[_CPComboCondition] = []
    condition_ids_by_symbol: dict[str, set[int]] = {}
    for group_key, options in universe.option_groups().items():
        calls = _options_by_strike(options, "CALL")
        puts = _options_by_strike(options, "PUT")
        for strike in sorted(set(calls) & set(puts)):
            call = calls[strike]
            put = puts[strike]
            condition = _CPComboCondition(
                key=(
                    f"{strategy.name}:{group_key.as_text()}:"
                    f"K={_format_float(strike)}:{call.symbol}:{put.symbol}"
                ),
                group_text=group_key.as_text(),
                strike=strike,
                call_symbol=call.symbol,
                put_symbol=put.symbol,
                underlying_symbol=group_key.underlying_symbol,
            )
            _add_condition(conditions, condition_ids_by_symbol, condition, (
                call.symbol,
                put.symbol,
                group_key.underlying_symbol,
            ))
    return _CompiledCPComboStrategy(
        name=strategy.name,
        threshold=strategy.threshold,
        conditions=tuple(conditions),
        condition_ids_by_symbol=condition_ids_by_symbol,
    )


def _compile_abs_spread(strategy: AbsSpreadStrategy, universe: Universe) -> _CompiledAbsSpreadStrategy:
    conditions: list[_AbsSpreadCondition] = []
    condition_ids_by_symbol: dict[str, set[int]] = {}
    for group_key, options in universe.option_groups().items():
        for option_class in ("CALL", "PUT"):
            class_options = [
                option
                for option in options
                if option.option_class == option_class and option.strike_price is not None
            ]
            class_options.sort(key=lambda option: option.strike_price or 0.0)
            for first, second in combinations(class_options, 2):
                first_strike = first.strike_price
                second_strike = second.strike_price
                if first_strike == second_strike:
                    continue
                condition = _AbsSpreadCondition(
                    key=(
                        f"{strategy.name}:{group_key.as_text()}:{option_class}:"
                        f"{first.symbol}:{second.symbol}"
                    ),
                    group_text=group_key.as_text(),
                    option_class=option_class,
                    first_symbol=first.symbol,
                    second_symbol=second.symbol,
                    first_strike=first_strike,
                    second_strike=second_strike,
                )
                _add_condition(conditions, condition_ids_by_symbol, condition, (first.symbol, second.symbol))
    return _CompiledAbsSpreadStrategy(
        name=strategy.name,
        threshold=strategy.threshold,
        conditions=tuple(conditions),
        condition_ids_by_symbol=condition_ids_by_symbol,
    )


def _add_condition(
    conditions: list[_CPComboCondition] | list[_AbsSpreadCondition],
    condition_ids_by_symbol: dict[str, set[int]],
    condition: _CPComboCondition | _AbsSpreadCondition,
    symbols: Iterable[str],
) -> None:
    condition_id = len(conditions)
    conditions.append(condition)
    for symbol in symbols:
        condition_ids_by_symbol.setdefault(symbol, set()).add(condition_id)


def _affected_condition_ids(
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


def _options_by_strike(options: list[InstrumentMeta], option_class: str) -> dict[float, InstrumentMeta]:
    result: dict[float, InstrumentMeta] = {}
    for option in options:
        if option.option_class == option_class and option.strike_price is not None:
            result[option.strike_price] = option
    return result


def _valid_price(value: float | None) -> bool:
    if value is None:
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric)


def _format_float(value: float) -> str:
    return f"{value:g}"
