"""Plain text import with robust encoding detection."""

from __future__ import annotations

import codecs
from pathlib import Path
from typing import ClassVar

import charset_normalizer

from ranobe.core.models import SegmentKind
from ranobe.core.segmenter import segment_text
from ranobe.services.importers.base import (
    ImportedBlock,
    ImportedBook,
    ImportedChapter,
    ImportFailed,
    register_importer,
)

_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


# Legacy encodings to try for a known source language, with a script check that rejects
# "successful" decodes into the wrong script (Shift_JIS bytes decode fine as CP949, for example).
_LANG_ENCODINGS = {
    "ja": (("cp932", "euc_jp"), lambda ch: "\u3040" <= ch <= "\u30ff"),  # kana
    "ko": (("cp949", "euc_kr"), lambda ch: "\uac00" <= ch <= "\ud7af"),  # Hangul
}


def decode_bytes(data: bytes, lang_hint: str | None = None) -> str:
    """BOM, then strict UTF-8, then the source language's legacy encodings, then detection.

    v1 tried utf-16 before gb18030 and cp1251 before shift_jis, so many files "decoded"
    successfully into garbage. UTF-16 is only trusted with a BOM now.
    """
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data.decode(encoding)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    encodings, in_script = _LANG_ENCODINGS.get(lang_hint or "", ((), None))
    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        letters = [ch for ch in text if ch.isalpha()]
        if letters and sum(map(in_script, letters)) / len(letters) > 0.2:
            return text
    best = charset_normalizer.from_bytes(data).best()
    if best is None:
        raise ImportFailed("unknown text encoding")
    return str(best)


def blocks_to_chapters(text: str, default_title: str) -> list[ImportedChapter]:
    """Each heading starts a new chapter; text before the first heading is its own chapter."""
    chapters: list[ImportedChapter] = []
    current = ImportedChapter(title=default_title)
    for seg in segment_text(text):
        if seg.kind is SegmentKind.HEADING and current.blocks:
            chapters.append(current)
            current = ImportedChapter(title=seg.text)
        elif seg.kind is SegmentKind.HEADING:
            current.title = seg.text
        current.blocks.append(ImportedBlock(seg.kind, seg.text))
    if current.blocks:
        chapters.append(current)
    return chapters


@register_importer
class TextImporter:
    extensions: ClassVar[tuple[str, ...]] = (".txt",)

    def read(self, path: Path, lang_hint: str | None = None) -> ImportedBook:
        text = decode_bytes(path.read_bytes(), lang_hint)
        return ImportedBook(title=path.stem, chapters=blocks_to_chapters(text, path.stem))
