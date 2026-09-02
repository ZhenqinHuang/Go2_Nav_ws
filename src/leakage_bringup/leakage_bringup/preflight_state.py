from __future__ import annotations


class PreflightState:
    def __init__(self, required: set[str]) -> None:
        self._required = required
        self._seen: set[str] = set()

    def mark_seen(self, name: str) -> None:
        self._seen.add(name)

    @property
    def ready(self) -> bool:
        return self._required <= self._seen
