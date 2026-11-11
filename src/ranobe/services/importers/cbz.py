"""CBZ import (ported from v1): only text files inside the archive are read, one per chapter.
Images are illustrations and carry no text to translate."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import ClassVar

from ranobe.services.importers.base import (
    ImportedBook,
    ImportedChapter,
    ImportFailed,
    register_importer,
)
from ranobe.services.importers.epub import xhtml_blocks
from ranobe.services.importers.text import blocks_to_chapters, decode_bytes

_TEXT_EXTS = {".txt", ".html", ".htm", ".xhtml"}


def _natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


@register_importer
class CbzImporter:
    extensions: ClassVar[tuple[str, ...]] = (".cbz",)

    def read(self, path: Path, lang_hint: str | None = None) -> ImportedBook:
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile as e:
            raise ImportFailed(f"invalid CBZ: {e}") from e
        with zf:
            names = sorted(
                (n for n in zf.namelist()
                 if not n.endswith("/") and PurePosixPath(n).suffix.lower() in _TEXT_EXTS),
                key=_natural_key,
            )  # fmt: skip
            if not names:
                raise ImportFailed("CBZ contains only images, nothing to translate")
            chapters = []
            for name in names:
                stem = PurePosixPath(name).stem
                text = decode_bytes(zf.read(name), lang_hint)
                if PurePosixPath(name).suffix.lower() == ".txt":
                    chapters.extend(blocks_to_chapters(text, stem))
                else:
                    blocks = xhtml_blocks(text)
                    if blocks:
                        chapters.append(ImportedChapter(title=stem, blocks=blocks))
        return ImportedBook(title=path.stem, chapters=chapters)
