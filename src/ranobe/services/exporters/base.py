"""Exporter interface, registry and the book view that every exporter reads.

A new format = one module with a registered class; nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol
from uuid import UUID

from ranobe.core.models import Chapter, Note, Segment, SegmentKind, Work
from ranobe.storage.repositories import Repositories


@dataclass
class ExportOptions:
    side_by_side: bool = False  # original above each translated paragraph (TXT, EPUB)
    with_notes: bool = True
    cover: Path | None = None  # JPEG or PNG
    page_size: tuple[int, int] = (1080, 1620)  # CBZ page in pixels
    font_size: int = 34  # CBZ body text in pixels


@dataclass
class ExportSegment:
    segment: Segment
    notes: list[Note] = field(default_factory=list)

    @property
    def kind(self) -> SegmentKind:
        return self.segment.kind

    @property
    def text(self) -> str:
        """The translation, or the original while the segment is not translated yet."""
        return self.segment.translation or self.segment.source

    @property
    def source(self) -> str:
        return self.segment.source


@dataclass
class ExportChapter:
    chapter: Chapter
    title: str
    segments: list[ExportSegment]


@dataclass
class ExportBook:
    work: Work
    chapters: list[ExportChapter]


def collect_book(
    repos: Repositories, work: Work, chapter_ids: list[UUID] | None = None
) -> ExportBook:
    """Read a work for export. A chapter that opens with a heading segment uses its
    translation as the chapter title, and the heading is not repeated in the body."""
    chapters = []
    for ch in repos.chapters.for_work(work.id):
        if chapter_ids is not None and ch.id not in chapter_ids:
            continue
        segments = [
            ExportSegment(s, repos.notes.for_segment(s.id))
            for s in repos.segments.for_chapter(ch.id)
        ]
        title = ch.title
        if segments and segments[0].kind is SegmentKind.HEADING:
            title = segments.pop(0).text
        chapters.append(ExportChapter(ch, title, segments))
    return ExportBook(work, chapters)


class Exporter(Protocol):
    id: ClassVar[str]
    extension: ClassVar[str]
    display_key: ClassVar[str]  # i18n key of the format name

    def export(self, book: ExportBook, opts: ExportOptions, out: Path) -> None: ...


class UnknownFormat(Exception):
    pass


_REGISTRY: dict[str, type[Exporter]] = {}


def register_exporter[T](cls: type[T]) -> type[T]:
    _REGISTRY[cls.id] = cls  # type: ignore[attr-defined]
    return cls


def get_exporter(format_id: str) -> Exporter:
    cls = _REGISTRY.get(format_id.lower())
    if cls is None:
        raise UnknownFormat(format_id)
    return cls()


def exporter_for_path(path: Path) -> Exporter:
    for cls in _REGISTRY.values():
        if cls.extension == path.suffix.lower():
            return cls()
    raise UnknownFormat(path.suffix)


def exporter_ids() -> list[str]:
    return sorted(_REGISTRY)
