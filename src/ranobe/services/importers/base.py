"""Importer interface and registry. A new format = one module with a registered class."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol

from ranobe.core.models import SegmentKind


@dataclass
class ImportedBlock:
    kind: SegmentKind
    text: str


@dataclass
class ImportedChapter:
    title: str
    blocks: list[ImportedBlock] = field(default_factory=list)


@dataclass
class ImportedBook:
    title: str
    chapters: list[ImportedChapter]
    author: str | None = None
    language: str | None = None  # BCP-47 from metadata, if any


class Importer(Protocol):
    extensions: ClassVar[tuple[str, ...]]

    def read(self, path: Path, lang_hint: str | None = None) -> ImportedBook: ...


class UnsupportedFormat(Exception):
    pass


class ImportFailed(Exception):
    pass


_REGISTRY: dict[str, type[Importer]] = {}


def register_importer[T](cls: type[T]) -> type[T]:
    for ext in cls.extensions:  # type: ignore[attr-defined]
        _REGISTRY[ext.lower()] = cls  # type: ignore[assignment]
    return cls


def importer_for(path: Path) -> Importer:
    cls = _REGISTRY.get(path.suffix.lower())
    if cls is None:
        raise UnsupportedFormat(path.suffix)
    return cls()


def supported_extensions() -> list[str]:
    return sorted(_REGISTRY)
