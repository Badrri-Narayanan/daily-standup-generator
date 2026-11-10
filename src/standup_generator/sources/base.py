"""The interface every activity source implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import SourceResult, TimeWindow


@runtime_checkable
class Source(Protocol):
    name: str

    def collect(self, window: TimeWindow) -> SourceResult: ...
