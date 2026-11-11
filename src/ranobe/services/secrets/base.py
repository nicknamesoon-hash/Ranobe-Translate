"""Secret store interface. API keys never go to the database, settings, logs or sync."""

from __future__ import annotations

from typing import Protocol


class SecretStore(Protocol):
    name: str

    def available(self) -> bool: ...

    def get(self, ref: str) -> str | None: ...

    def set(self, ref: str, secret: str) -> None: ...

    def delete(self, ref: str) -> None: ...


class SecretStoreLocked(Exception):
    """The encrypted store needs the master password first."""


class MemorySecretStore:
    """In-memory store for tests and for a session without persistence."""

    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def available(self) -> bool:
        return True

    def get(self, ref: str) -> str | None:
        return self._data.get(ref)

    def set(self, ref: str, secret: str) -> None:
        self._data[ref] = secret

    def delete(self, ref: str) -> None:
        self._data.pop(ref, None)
