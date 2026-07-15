from __future__ import annotations

from typing import Iterator, Protocol

from optionsentry.models import MarketSnapshot, Universe


class MarketDataSource(Protocol):
    @property
    def mode(self) -> str:
        ...

    def discover_universe(self) -> Universe:
        ...

    def stream(self, universe: Universe) -> Iterator[MarketSnapshot]:
        ...

    def close(self) -> None:
        ...
