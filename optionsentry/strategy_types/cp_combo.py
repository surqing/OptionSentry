from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar

from optionsentry.formatting import format_key_bound, format_key_number, format_key_range
from optionsentry.models import ConditionEvaluation, InstrumentMeta, MarketSnapshot, Universe
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


CALL_MONEYNESS_METRIC = "C虚实度"
PUT_MONEYNESS_METRIC = "P虚实度"
CP_NEGATIVE_VALUE_COLOR = "#d8ecdf"
CP_POSITIVE_VALUE_COLOR = "#f1d7d2"


@register_strategy("cp_combo")
@dataclass
class CPComboStrategy(Strategy):
    display_name: ClassVar[str] = "CP组合预警"
    display_order: ClassVar[int] = 10
    negative_value_color: ClassVar[str] = CP_NEGATIVE_VALUE_COLOR
    positive_value_color: ClassVar[str] = CP_POSITIVE_VALUE_COLOR
    metric_columns: ClassVar[tuple[MetricColumn, ...]] = (
        MetricColumn(CALL_MONEYNESS_METRIC),
        MetricColumn(PUT_MONEYNESS_METRIC),
    )

    min_value: float
    max_value: float
    name: str = "cp_combo"
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
        return ((threshold, math.inf), (-math.inf, -threshold))

    @classmethod
    def make_key(
        cls,
        *,
        name: str,
        group_text: str,
        strike: float,
        call_symbol: str,
        put_symbol: str,
        min_value: float,
        max_value: float,
    ) -> str:
        return (
            f"{name}:{group_text}:K={format_key_number(strike)}:{call_symbol}:{put_symbol}:"
            f"R={format_key_bound(min_value)}..{format_key_bound(max_value)}"
        )

    @classmethod
    def parse_key(cls, key: str) -> dict[str, str] | None:
        parts = key.split(":")
        if len(parts) < 6 or not (parts[0] == cls.type_name or parts[3].startswith("K=")):
            return None
        return {
            "underlying": parts[1],
            "expiry": parts[2],
            "strike": parts[3].removeprefix("K="),
            "call_symbol": parts[4],
            "put_symbol": parts[5],
        }

    @classmethod
    def email_presentation(cls, fields: dict[str, str]) -> EmailPresentation:
        monitor = f"{fields.get('underlying', '')} {fields.get('expiry', '')}".strip()
        strike = fields.get("strike", "")
        return EmailPresentation(
            monitor=monitor or "-",
            structure="认购 + 认沽 + 标的",
            strike=f"K={strike}" if strike else "-",
            metric_label="偏离率",
        )

    @classmethod
    def row_background_color(cls, evaluation: ConditionEvaluation) -> str | None:
        if evaluation.value < 0:
            return cls.negative_value_color
        if evaluation.value > 0:
            return cls.positive_value_color
        return None

    def evaluate(self, snapshot: MarketSnapshot, universe: Universe) -> list[ConditionEvaluation]:
        return self.compile(universe).evaluate(snapshot)

    def compile(self, universe: Universe) -> CompiledStrategy:
        return _compile_cp_combo(self, universe)


@dataclass(frozen=True)
class _CPComboCondition:
    key: str
    group_text: str
    expiry: str
    strike: float
    call_symbol: str
    put_symbol: str
    underlying_symbol: str


@dataclass
class _CompiledCPComboStrategy(CompiledStrategy):
    name: str
    min_value: float
    max_value: float
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
        for condition_id in affected_condition_ids(
            self.condition_ids_by_symbol,
            changed_symbols,
            self.condition_count,
        ):
            condition = self.conditions[condition_id]
            future_price = snapshot.prices.get(condition.underlying_symbol)
            if not valid_price(future_price) or future_price <= 0:
                continue
            call_price = snapshot.prices.get(condition.call_symbol)
            put_price = snapshot.prices.get(condition.put_symbol)
            if not (valid_price(call_price) and valid_price(put_price)):
                continue
            deviation = call_price - put_price + condition.strike - future_price
            value = deviation / future_price
            active = in_alert_range(value, self.min_value, self.max_value)
            symbols = (condition.call_symbol, condition.put_symbol, condition.underlying_symbol)
            metrics = {
                CALL_MONEYNESS_METRIC: (future_price - condition.strike) / future_price,
                PUT_MONEYNESS_METRIC: (condition.strike - future_price) / future_price,
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
                        f"{self.name} {condition.group_text} K={format_key_number(condition.strike)} "
                        f"value={value:.8f} range={format_key_range(self.min_value, self.max_value)} "
                        f"symbols={','.join(symbols)}"
                    ),
                    metrics=metrics,
                    strategy_type=CPComboStrategy.type_name,
                    fields={
                        "underlying": condition.underlying_symbol,
                        "expiry": condition.expiry,
                        "strike": format_key_number(condition.strike),
                        "call_symbol": condition.call_symbol,
                        "put_symbol": condition.put_symbol,
                    },
                )
            )
        return evaluations


def _compile_cp_combo(strategy: CPComboStrategy, universe: Universe) -> _CompiledCPComboStrategy:
    conditions: list[_CPComboCondition] = []
    condition_ids_by_symbol: dict[str, set[int]] = {}
    for group_key, options in universe.option_groups().items():
        calls = _options_by_strike(options, "CALL")
        puts = _options_by_strike(options, "PUT")
        for strike in sorted(set(calls) & set(puts)):
            call = calls[strike]
            put = puts[strike]
            group_text = group_key.as_text()
            condition = _CPComboCondition(
                key=CPComboStrategy.make_key(
                    name=strategy.name,
                    group_text=group_text,
                    strike=strike,
                    call_symbol=call.symbol,
                    put_symbol=put.symbol,
                    min_value=strategy.min_value,
                    max_value=strategy.max_value,
                ),
                group_text=group_text,
                expiry=group_text.split(":", 1)[1],
                strike=strike,
                call_symbol=call.symbol,
                put_symbol=put.symbol,
                underlying_symbol=group_key.underlying_symbol,
            )
            add_condition(
                conditions,
                condition_ids_by_symbol,
                condition,
                (call.symbol, put.symbol, group_key.underlying_symbol),
            )
    return _CompiledCPComboStrategy(
        name=strategy.name,
        min_value=strategy.min_value,
        max_value=strategy.max_value,
        conditions=tuple(conditions),
        condition_ids_by_symbol=condition_ids_by_symbol,
    )


def _options_by_strike(options: list[InstrumentMeta], option_class: str) -> dict[float, InstrumentMeta]:
    result: dict[float, InstrumentMeta] = {}
    for option in options:
        if option.option_class == option_class and option.strike_price is not None:
            result[option.strike_price] = option
    return result
