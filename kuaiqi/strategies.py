from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations

from kuaiqi.config import StrategyConfig
from kuaiqi.models import ConditionEvaluation, InstrumentMeta, MarketSnapshot, Universe


class Strategy:
    name: str

    def evaluate(self, snapshot: MarketSnapshot, universe: Universe) -> list[ConditionEvaluation]:
        raise NotImplementedError


@dataclass
class CPComboStrategy(Strategy):
    threshold: float
    name: str = "cp_combo"

    def evaluate(self, snapshot: MarketSnapshot, universe: Universe) -> list[ConditionEvaluation]:
        evaluations: list[ConditionEvaluation] = []
        for group_key, options in universe.option_groups().items():
            calls = _options_by_strike(options, "CALL")
            puts = _options_by_strike(options, "PUT")
            future_price = snapshot.prices.get(group_key.underlying_symbol)
            if not _valid_price(future_price) or future_price <= 0:
                continue
            for strike in sorted(set(calls) & set(puts)):
                call = calls[strike]
                put = puts[strike]
                call_price = snapshot.prices.get(call.symbol)
                put_price = snapshot.prices.get(put.symbol)
                if not (_valid_price(call_price) and _valid_price(put_price)):
                    continue
                value = (call_price - put_price + strike - future_price) / future_price
                active = abs(value) > self.threshold
                symbols = (call.symbol, put.symbol, group_key.underlying_symbol)
                evaluations.append(
                    ConditionEvaluation(
                        key=(
                            f"{self.name}:{group_key.as_text()}:"
                            f"K={_format_float(strike)}:{call.symbol}:{put.symbol}"
                        ),
                        strategy_name=self.name,
                        active=active,
                        value=value,
                        threshold=self.threshold,
                        symbols=symbols,
                        message=(
                            f"{self.name} {group_key.as_text()} K={_format_float(strike)} "
                            f"value={value:.8f} threshold={self.threshold:.8f} "
                            f"symbols={','.join(symbols)}"
                        ),
                    )
                )
        return evaluations


@dataclass
class AbsSpreadStrategy(Strategy):
    threshold: float
    epsilon: float = 1e-12
    name: str = "abs_spread"

    def evaluate(self, snapshot: MarketSnapshot, universe: Universe) -> list[ConditionEvaluation]:
        evaluations: list[ConditionEvaluation] = []
        for group_key, options in universe.option_groups().items():
            for option_class in ("CALL", "PUT"):
                class_options = [
                    option
                    for option in options
                    if option.option_class == option_class and option.strike_price is not None
                ]
                class_options.sort(key=lambda option: option.strike_price or 0.0)
                for first, second in combinations(class_options, 2):
                    first_price = snapshot.prices.get(first.symbol)
                    second_price = snapshot.prices.get(second.symbol)
                    first_strike = first.strike_price
                    second_strike = second.strike_price
                    if first_strike == second_strike:
                        continue
                    if not (_valid_price(first_price) and _valid_price(second_price)):
                        continue
                    value = abs(first_price - second_price) / (abs(first_strike - second_strike) + self.epsilon)
                    active = value < self.threshold
                    symbols = (first.symbol, second.symbol)
                    evaluations.append(
                        ConditionEvaluation(
                            key=(
                                f"{self.name}:{group_key.as_text()}:{option_class}:"
                                f"{first.symbol}:{second.symbol}"
                            ),
                            strategy_name=self.name,
                            active=active,
                            value=value,
                            threshold=self.threshold,
                            symbols=symbols,
                            message=(
                                f"{self.name} {group_key.as_text()} {option_class} "
                                f"{_format_float(first_strike)}-{_format_float(second_strike)} "
                                f"value={value:.8f} threshold={self.threshold:.8f} "
                                f"symbols={','.join(symbols)}"
                            ),
                        )
                    )
        return evaluations


def build_strategy(config: StrategyConfig) -> Strategy:
    name = config.name or config.type
    if config.type == "cp_combo":
        return CPComboStrategy(threshold=config.threshold, name=name)
    if config.type == "abs_spread":
        return AbsSpreadStrategy(threshold=config.threshold, epsilon=config.epsilon, name=name)
    raise ValueError(f"Unsupported strategy type: {config.type}")


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
