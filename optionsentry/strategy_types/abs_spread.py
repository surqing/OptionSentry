from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import ClassVar

from optionsentry.formatting import format_key_bound, format_key_number, format_key_range
from optionsentry.models import ConditionEvaluation, MarketSnapshot, Universe
from optionsentry.strategy_base import (
    CompiledStrategy,
    EmailPresentation,
    MetricColumn,
    Strategy,
    add_condition,
    affected_condition_ids,
    in_alert_range,
    valid_price,
)
from optionsentry.strategy_registry import register_strategy


SPREAD_A_MONEYNESS_METRIC = "虚实度A"
SPREAD_B_MONEYNESS_METRIC = "虚实度B"
SPREAD_AVG_MONEYNESS_METRIC = "平均虚实度"


@register_strategy("abs_spread")
@dataclass
class AbsSpreadStrategy(Strategy):
    display_name: ClassVar[str] = "价差预警"
    display_order: ClassVar[int] = 20
    metric_columns: ClassVar[tuple[MetricColumn, ...]] = (
        MetricColumn(SPREAD_A_MONEYNESS_METRIC),
        MetricColumn(SPREAD_B_MONEYNESS_METRIC),
        MetricColumn(SPREAD_AVG_MONEYNESS_METRIC, width=115),
    )

    min_value: float
    max_value: float
    name: str = "abs_spread"
    filter_script: str | None = None
    filter_function: str = "accept"
    filter_scope: str = "options"

    @classmethod
    def default_range(cls) -> tuple[float, float]:
        return -math.inf, 0.1

    @classmethod
    def make_key(
        cls,
        *,
        name: str,
        group_text: str,
        option_class: str,
        first_symbol: str,
        second_symbol: str,
        min_value: float,
        max_value: float,
    ) -> str:
        return (
            f"{name}:{group_text}:{option_class}:{first_symbol}:{second_symbol}:"
            f"R={format_key_bound(min_value)}..{format_key_bound(max_value)}"
        )

    @classmethod
    def parse_key(cls, key: str) -> dict[str, str] | None:
        parts = key.split(":")
        if len(parts) < 6 or not (parts[0] == cls.type_name or parts[3] in {"CALL", "PUT"}):
            return None
        return {
            "underlying": parts[1],
            "expiry": parts[2],
            "option_class": parts[3],
            "first_symbol": parts[4],
            "second_symbol": parts[5],
            "first_strike": _symbol_tail_number(parts[4]),
            "second_strike": _symbol_tail_number(parts[5]),
        }

    @classmethod
    def email_presentation(cls, fields: dict[str, str]) -> EmailPresentation:
        monitor = f"{fields.get('underlying', '')} {fields.get('expiry', '')}".strip()
        first_strike = fields.get("first_strike", "")
        second_strike = fields.get("second_strike", "")
        return EmailPresentation(
            monitor=monitor or "-",
            structure=_option_class_label(fields.get("option_class", "")),
            strike=f"{first_strike} / {second_strike}" if first_strike and second_strike else "-",
            metric_label="价差比例",
        )

    def evaluate(self, snapshot: MarketSnapshot, universe: Universe) -> list[ConditionEvaluation]:
        return self.compile(universe).evaluate(snapshot)

    def compile(self, universe: Universe) -> CompiledStrategy:
        return _compile_abs_spread(self, universe)


@dataclass(frozen=True)
class _AbsSpreadCondition:
    key: str
    group_text: str
    expiry: str
    option_class: str
    first_symbol: str
    second_symbol: str
    first_strike: float
    second_strike: float
    underlying_symbol: str


@dataclass
class _CompiledAbsSpreadStrategy(CompiledStrategy):
    name: str
    min_value: float
    max_value: float
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
        for condition_id in affected_condition_ids(
            self.condition_ids_by_symbol,
            changed_symbols,
            self.condition_count,
        ):
            condition = self.conditions[condition_id]
            future_price = snapshot.prices.get(condition.underlying_symbol)
            if not valid_price(future_price) or future_price <= 0:
                continue
            first_symbol, first_strike, second_symbol, second_strike = _spread_leg_order(condition)
            first_price = snapshot.prices.get(first_symbol)
            second_price = snapshot.prices.get(second_symbol)
            if not (valid_price(first_price) and valid_price(second_price)):
                continue
            strike_distance = first_strike - second_strike
            if strike_distance == 0:
                continue
            value = (first_price - second_price) / strike_distance
            active = in_alert_range(value, self.min_value, self.max_value)
            symbols = (first_symbol, second_symbol)
            first_moneyness = _option_moneyness(condition.option_class, first_strike, future_price)
            second_moneyness = _option_moneyness(condition.option_class, second_strike, future_price)
            metrics = {
                SPREAD_A_MONEYNESS_METRIC: first_moneyness,
                SPREAD_B_MONEYNESS_METRIC: second_moneyness,
                SPREAD_AVG_MONEYNESS_METRIC: (first_moneyness + second_moneyness) / 2,
            }
            evaluations.append(
                ConditionEvaluation(
                    key=condition.key,
                    strategy_name=self.name,
                    active=active,
                    value=value,
                    min_value=self.min_value,
                    max_value=self.max_value,
                    symbols=symbols,
                    message=(
                        f"{self.name} {condition.group_text} {condition.option_class} "
                        f"{format_key_number(first_strike)}-{format_key_number(second_strike)} "
                        f"value={value:.8f} range={format_key_range(self.min_value, self.max_value)} "
                        f"symbols={','.join(symbols)}"
                    ),
                    metrics=metrics,
                    strategy_type=AbsSpreadStrategy.type_name,
                    fields={
                        "underlying": condition.underlying_symbol,
                        "expiry": condition.expiry,
                        "option_class": condition.option_class,
                        "first_symbol": condition.first_symbol,
                        "second_symbol": condition.second_symbol,
                        "first_strike": _symbol_tail_number(condition.first_symbol),
                        "second_strike": _symbol_tail_number(condition.second_symbol),
                    },
                )
            )
        return evaluations


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
                group_text = group_key.as_text()
                condition = _AbsSpreadCondition(
                    key=AbsSpreadStrategy.make_key(
                        name=strategy.name,
                        group_text=group_text,
                        option_class=option_class,
                        first_symbol=first.symbol,
                        second_symbol=second.symbol,
                        min_value=strategy.min_value,
                        max_value=strategy.max_value,
                    ),
                    group_text=group_text,
                    expiry=group_text.split(":", 1)[1],
                    option_class=option_class,
                    first_symbol=first.symbol,
                    second_symbol=second.symbol,
                    first_strike=first_strike,
                    second_strike=second_strike,
                    underlying_symbol=group_key.underlying_symbol,
                )
                add_condition(
                    conditions,
                    condition_ids_by_symbol,
                    condition,
                    (first.symbol, second.symbol, group_key.underlying_symbol),
                )
    return _CompiledAbsSpreadStrategy(
        name=strategy.name,
        min_value=strategy.min_value,
        max_value=strategy.max_value,
        conditions=tuple(conditions),
        condition_ids_by_symbol=condition_ids_by_symbol,
    )


def _spread_leg_order(condition: _AbsSpreadCondition) -> tuple[str, float, str, float]:
    first = (condition.first_symbol, condition.first_strike)
    second = (condition.second_symbol, condition.second_strike)
    if condition.option_class == "PUT":
        return (*second, *first) if second[1] > first[1] else (*first, *second)
    return (*first, *second) if first[1] < second[1] else (*second, *first)


def _option_moneyness(option_class: str, strike: float, future_price: float) -> float:
    if option_class == "PUT":
        return (strike - future_price) / future_price
    return (future_price - strike) / future_price


def _option_class_label(option_class: str) -> str:
    return {"CALL": "认购", "PUT": "认沽"}.get(option_class, option_class or "-")


def _symbol_tail_number(symbol: str) -> str:
    tail = ""
    for character in reversed(symbol):
        if not character.isdigit() and character != ".":
            break
        tail = character + tail
    return tail
