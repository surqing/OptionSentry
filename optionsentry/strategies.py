"""Compatibility façade for strategy classes and construction helpers."""

from __future__ import annotations

from optionsentry.config import StrategyConfig
from optionsentry.strategy_base import CompiledStrategy, Strategy, StrategyCompilation
from optionsentry.strategy_registry import create_strategy, get_strategy_class


CPComboStrategy = get_strategy_class("cp_combo")
AbsSpreadStrategy = get_strategy_class("abs_spread")

CALL_MONEYNESS_METRIC = CPComboStrategy.metric_columns[0].name
PUT_MONEYNESS_METRIC = CPComboStrategy.metric_columns[1].name
SPREAD_A_MONEYNESS_METRIC = AbsSpreadStrategy.metric_columns[0].name
SPREAD_B_MONEYNESS_METRIC = AbsSpreadStrategy.metric_columns[1].name
SPREAD_AVG_MONEYNESS_METRIC = AbsSpreadStrategy.metric_columns[2].name
CP_NEGATIVE_VALUE_COLOR = CPComboStrategy.negative_value_color
CP_POSITIVE_VALUE_COLOR = CPComboStrategy.positive_value_color


def build_strategy(config: StrategyConfig) -> Strategy:
    return create_strategy(config)


__all__ = [
    "AbsSpreadStrategy",
    "CALL_MONEYNESS_METRIC",
    "CP_NEGATIVE_VALUE_COLOR",
    "CP_POSITIVE_VALUE_COLOR",
    "CPComboStrategy",
    "CompiledStrategy",
    "PUT_MONEYNESS_METRIC",
    "SPREAD_A_MONEYNESS_METRIC",
    "SPREAD_AVG_MONEYNESS_METRIC",
    "SPREAD_B_MONEYNESS_METRIC",
    "Strategy",
    "StrategyCompilation",
    "build_strategy",
]
