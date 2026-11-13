"""Plain text export: chapters, paragraphs, notes as [n] with a list after each chapter."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from ranobe.core.footnotes import split_at_anchors
from ranobe.core.models import SegmentKind
from ranobe.services.exporters.base import (
    ExportBook,
    ExportChapter,
    ExportOptions,
    register_exporter,
)


@register_exporter
class TxtExporter:
    id: ClassVar[str] = "txt"
    extension: ClassVar[str] = ".txt"
    display_key: ClassVar[str] = "export.format.txt"

    def export(self, book: ExportBook, opts: ExportOptions, out: Path) -> None:
        header = [book.work.title]
        if book.work.author:
            header.append(book.work.author)
        parts = ["\n".join(header)]
        parts += [_chapter(ch, opts) for ch in book.chapters]
        out.write_text("\n\n\n".join(parts) + "\n", encoding="utf-8")


def _chapter(ch: ExportChapter, opts: ExportOptions) -> str:
    blocks = [ch.title]
    notes: list[str] = []
    for seg in ch.segments:
        text = seg.text
        if opts.with_notes and seg.notes:
            pieces = []
            for piece in split_at_anchors(text, seg.notes):
                if isinstance(piece, str):
                    pieces.append(piece)
                else:
                    notes.append(f"[{len(notes) + 1}] {piece.text}")
                    pieces.append(f"[{len(notes)}]")
            text = "".join(pieces)
        if opts.side_by_side and seg.kind is not SegmentKind.SEPARATOR:
            text = f"{seg.source}\n{text}"
        blocks.append(text)
    if notes:
        blocks.append("———\n" + "\n".join(notes))
    return "\n\n".join(blocks)
