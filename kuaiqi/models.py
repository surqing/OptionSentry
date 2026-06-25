from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class InstrumentMeta:
    symbol: str
    ins_class: str
    underlying_symbol: str = ""
    strike_price: float | None = None
    option_class: str = ""
    exercise_year: int | None = None
    exercise_month: int | None = None
    instrument_name: str = ""
    product_id: str = ""

    @property
    def is_option(self) -> bool:
        return self.ins_class == "OPTION"

    @property
    def is_future(self) -> bool:
        return self.ins_class == "FUTURE"

    @property
    def expiry_key(self) -> str:
        year = self.exercise_year if self.exercise_year is not None else "NA"
        month = self.exercise_month if self.exercise_month is not None else "NA"
        return f"{year}-{month}"


@dataclass(frozen=True)
class OptionGroupKey:
    underlying_symbol: str
    exercise_year: int | None
    exercise_month: int | None

    def as_text(self) -> str:
        year = self.exercise_year if self.exercise_year is not None else "NA"
        month = self.exercise_month if self.exercise_month is not None else "NA"
        return f"{self.underlying_symbol}:{year}-{month}"


@dataclass
class Universe:
    instruments: dict[str, InstrumentMeta]
    requested_symbols: tuple[str, ...] = ()

    @property
    def options(self) -> list[InstrumentMeta]:
        return [meta for meta in self.instruments.values() if meta.is_option]

    @property
    def futures(self) -> list[InstrumentMeta]:
        return [meta for meta in self.instruments.values() if meta.is_future]

    @property
    def underlying_symbols(self) -> set[str]:
        return {meta.underlying_symbol for meta in self.options if meta.underlying_symbol}

    def price_symbols(self) -> set[str]:
        return {meta.symbol for meta in self.options} | self.underlying_symbols

    def option_groups(self) -> dict[OptionGroupKey, list[InstrumentMeta]]:
        groups: dict[OptionGroupKey, list[InstrumentMeta]] = {}
        for option in self.options:
            key = OptionGroupKey(
                option.underlying_symbol,
                option.exercise_year,
                option.exercise_month,
            )
            groups.setdefault(key, []).append(option)
        return groups

    def subset(self, symbols: Iterable[str]) -> "Universe":
        wanted = set(symbols)
        instruments = {
            symbol: meta
            for symbol, meta in self.instruments.items()
            if symbol in wanted or (meta.is_future and symbol in wanted)
        }
        return Universe(instruments=instruments, requested_symbols=tuple(sorted(wanted)))

    def strategy_groups(self) -> list["Universe"]:
        groups: list[Universe] = []
        for key, options in self.option_groups().items():
            symbols = {key.underlying_symbol, *(option.symbol for option in options)}
            groups.append(self.subset(symbols))
        return groups or [self]


@dataclass(frozen=True)
class MarketSnapshot:
    timestamp: str
    prices: dict[str, float]
    changed_symbols: set[str]
    universe: Universe


@dataclass(frozen=True)
class ConditionEvaluation:
    key: str
    strategy_name: str
    active: bool
    value: float
    threshold: float
    symbols: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class AlertEvent:
    timestamp: str
    evaluation: ConditionEvaluation
    metadata: dict[str, str] = field(default_factory=dict)
