"""EPUB 2/3 import using only the standard library (no lxml, keeps Android builds simple).

Fixes from v1: chapters follow the spine order, paragraphs come from block elements instead of
line breaks, ruby annotations (furigana) are dropped, and chapter titles are kept.
"""

from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar
from urllib.parse import unquote

from ranobe.core.models import SegmentKind
from ranobe.core.segmenter import MAX_SEGMENT_CHARS, classify, segment_text
from ranobe.services.importers.base import (
    ImportedBlock,
    ImportedBook,
    ImportedChapter,
    ImportFailed,
    register_importer,
)

_NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}

_BLOCK_TAGS = {"p", "div", "li", "blockquote", "section", "article", "tr", "dd", "dt"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {"rt", "rp", "script", "style", "head", "title"}


class _XhtmlBlocks(HTMLParser):
    """Collect text blocks; a block ends at every block-level open/close tag."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[ImportedBlock] = []
        self._buf: list[str] = []
        self._skip = 0
        self._heading = 0

    def _flush(self) -> None:
        text = "".join(self._buf).strip()
        self._buf = []
        if not text:
            return
        if self._heading:
            self.blocks.append(ImportedBlock(SegmentKind.HEADING, " ".join(text.split())))
        else:
            for seg in segment_text(text, MAX_SEGMENT_CHARS):
                kind = (
                    SegmentKind.SEPARATOR
                    if seg.kind is SegmentKind.SEPARATOR
                    else (SegmentKind.PARAGRAPH)
                )
                self.blocks.append(ImportedBlock(kind, seg.text))

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "br":
            self._buf.append("\n")
        elif tag == "hr":
            self._flush()
            self.blocks.append(ImportedBlock(SegmentKind.SEPARATOR, "* * *"))
        elif tag in _BLOCK_TAGS or tag in _HEADING_TAGS:
            self._flush()
            if tag in _HEADING_TAGS:
                self._heading += 1

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS or tag in _HEADING_TAGS:
            self._flush()
            if tag in _HEADING_TAGS:
                self._heading = max(0, self._heading - 1)

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


def xhtml_blocks(markup: str) -> list[ImportedBlock]:
    parser = _XhtmlBlocks()
    parser.feed(markup)
    parser.close()
    # Paragraph text inside a <br>-only document is one block per line; split it.
    result: list[ImportedBlock] = []
    for b in parser.blocks:
        if b.kind is SegmentKind.PARAGRAPH and "\n" in b.text:
            for line in (x.strip() for x in b.text.split("\n")):
                if line:
                    result.append(ImportedBlock(classify(line), line))
        else:
            result.append(b)
    return result


@register_importer
class EpubImporter:
    extensions: ClassVar[tuple[str, ...]] = (".epub",)

    def read(self, path: Path, lang_hint: str | None = None) -> ImportedBook:
        try:
            with zipfile.ZipFile(path) as zf:
                return self._read(zf, path.stem)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
            raise ImportFailed(f"invalid EPUB: {e}") from e

    def _read(self, zf: zipfile.ZipFile, fallback_title: str) -> ImportedBook:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = container.find(".//c:rootfile", _NS)
        if rootfile is None:
            raise ImportFailed("EPUB has no rootfile")
        opf_path = rootfile.attrib["full-path"]
        opf_dir = posixpath.dirname(opf_path)
        opf = ET.fromstring(zf.read(opf_path))

        title = _text(opf.find(".//dc:title", _NS)) or fallback_title
        author = _text(opf.find(".//dc:creator", _NS))
        language = _text(opf.find(".//dc:language", _NS))

        manifest = {
            item.attrib["id"]: item.attrib for item in opf.findall(".//opf:manifest/opf:item", _NS)
        }
        chapters: list[ImportedChapter] = []
        for itemref in opf.findall(".//opf:spine/opf:itemref", _NS):
            item = manifest.get(itemref.attrib.get("idref", ""))
            if not item or "nav" in item.get("properties", ""):
                continue
            if "html" not in item.get("media-type", ""):
                continue
            href = posixpath.normpath(posixpath.join(opf_dir, unquote(item["href"])))
            markup = zf.read(href).decode("utf-8", errors="replace")
            blocks = xhtml_blocks(markup)
            if not any(b.kind is not SegmentKind.SEPARATOR for b in blocks):
                continue  # cover or image-only page
            heading = next((b.text for b in blocks if b.kind is SegmentKind.HEADING), None)
            chapters.append(
                ImportedChapter(title=heading or posixpath.basename(href), blocks=blocks)
            )
        if not chapters:
            raise ImportFailed("EPUB has no text")
        return ImportedBook(title=title, author=author, language=language, chapters=chapters)


def _text(el: ET.Element | None) -> str | None:
    if el is None or not (el.text or "").strip():
        return None
    return el.text.strip()
