"""EPUB 3 export.

One XHTML file per chapter. Notes are EPUB 3 footnotes (noteref + aside), which most readers
open as a popup. The identifier is urn:uuid:<work id>, so a re-export updates the same book
in a reader's library instead of adding a copy.
"""

from __future__ import annotations

import zipfile
from html import escape
from pathlib import Path
from typing import ClassVar

from ranobe.core.footnotes import split_at_anchors
from ranobe.core.models import SegmentKind, Work
from ranobe.services.exporters.base import (
    ExportBook,
    ExportChapter,
    ExportOptions,
    register_exporter,
)

_COVER_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

STYLE = """\
body { margin: 0 4%; line-height: 1.5; }
h1 { text-align: center; margin: 2em 0 1em; font-size: 1.4em; }
h2 { margin: 1.5em 0 0.5em; font-size: 1.15em; }
p { margin: 0; text-indent: 1.5em; }
p.sep { text-align: center; text-indent: 0; margin: 1em 0; }
p.src { text-indent: 0; margin-top: 0.8em; font-size: 0.85em; color: #666; }
a.noteref { text-decoration: none; font-size: 0.75em; vertical-align: super; }
aside.footnote p { text-indent: 0; font-size: 0.9em; }
div.cover { text-align: center; }
div.cover img { max-width: 100%; max-height: 100%; }
"""


def _x(text: str) -> str:
    return escape(text, quote=False)


def _a(text: str) -> str:
    return escape(text, quote=True)


def _page(lang: str, title: str, body: str, extra_ns: bool = True) -> str:
    ns = ' xmlns:epub="http://www.idpf.org/2007/ops"' if extra_ns else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml"{ns} xml:lang="{lang}" lang="{lang}">\n'
        f'<head>\n<meta charset="UTF-8"/>\n<title>{_x(title)}</title>\n'
        '<link rel="stylesheet" type="text/css" href="style.css"/>\n</head>\n'
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def chapter_xhtml(ch: ExportChapter, work: Work, opts: ExportOptions) -> str:
    lang, src_lang = work.target_lang, work.source_lang
    body = ['<section epub:type="chapter">', f"<h1>{_x(ch.title)}</h1>"]
    asides = []
    for seg in ch.segments:
        if seg.kind is SegmentKind.SEPARATOR:
            body.append(f'<p class="sep">{_x(seg.text)}</p>')
            continue
        if opts.side_by_side:
            body.append(
                f'<p class="src" lang="{src_lang}" xml:lang="{src_lang}">{_x(seg.source)}</p>'
            )
        html = []
        notes = seg.notes if opts.with_notes else []
        for piece in split_at_anchors(seg.text, notes):
            if isinstance(piece, str):
                html.append(_x(piece))
                continue
            n = len(asides) + 1
            html.append(
                f'<a epub:type="noteref" class="noteref" id="ref{n}" href="#note{n}">{n}</a>'
            )
            asides.append(
                f'<aside epub:type="footnote" class="footnote" id="note{n}">'
                f'<p><a href="#ref{n}">{n}.</a> {_x(piece.text)}</p></aside>'
            )
        tag = "h2" if seg.kind is SegmentKind.HEADING else "p"
        body.append(f"<{tag}>{''.join(html)}</{tag}>")
    body.append("</section>")
    body += asides
    return _page(lang, ch.title, "\n".join(body))


def _nav(book: ExportBook, files: list[str]) -> str:
    items = "\n".join(
        f'<li><a href="{f}">{_x(ch.title)}</a></li>'
        for ch, f in zip(book.chapters, files, strict=True)
    )
    body = (
        f'<nav epub:type="toc" id="toc">\n<h1>{_x(book.work.title)}</h1>\n'
        f"<ol>\n{items}\n</ol>\n</nav>"
    )
    return _page(book.work.target_lang, book.work.title, body)


def _ncx(book: ExportBook, files: list[str]) -> str:
    points = "\n".join(
        f'<navPoint id="np{i}" playOrder="{i}"><navLabel><text>{_x(ch.title)}</text>'
        f'</navLabel><content src="{f}"/></navPoint>'
        for i, (ch, f) in enumerate(zip(book.chapters, files, strict=True), start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        f'<head><meta name="dtb:uid" content="urn:uuid:{book.work.id}"/></head>\n'
        f"<docTitle><text>{_x(book.work.title)}</text></docTitle>\n"
        f"<navMap>\n{points}\n</navMap>\n</ncx>\n"
    )


def _opf(book: ExportBook, files: list[str], cover: tuple[str, str] | None) -> str:
    w = book.work
    meta = [
        f'<dc:identifier id="bookid">urn:uuid:{w.id}</dc:identifier>',
        f"<dc:title>{_x(w.title)}</dc:title>",
        f"<dc:language>{w.target_lang}</dc:language>",
        f'<meta property="dcterms:modified">{w.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ")}</meta>',
    ]
    if w.author:
        meta.append(f"<dc:creator>{_x(w.author)}</dc:creator>")
    if w.synopsis:
        meta.append(f"<dc:description>{_x(w.synopsis)}</dc:description>")
    meta += [f"<dc:subject>{_x(g)}</dc:subject>" for g in w.genres]
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
    ]
    spine = []
    if cover:
        name, media_type = cover
        meta.append('<meta name="cover" content="cover-image"/>')  # EPUB 2 readers
        manifest += [
            f'<item id="cover-image" href="{name}" media-type="{media_type}" '
            'properties="cover-image"/>',
            '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>',
        ]
        spine.append('<itemref idref="cover"/>')
    for i, f in enumerate(files, start=1):
        manifest.append(f'<item id="ch{i}" href="{f}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="ch{i}"/>')
    nl = "\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        f'unique-identifier="bookid" xml:lang="{w.target_lang}">\n'
        f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n{nl.join(meta)}\n</metadata>\n'
        f"<manifest>\n{nl.join(manifest)}\n</manifest>\n"
        f'<spine toc="ncx">\n{nl.join(spine)}\n</spine>\n</package>\n'
    )


CONTAINER = """\
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles>
<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles>
</container>
"""


@register_exporter
class EpubExporter:
    id: ClassVar[str] = "epub"
    extension: ClassVar[str] = ".epub"
    display_key: ClassVar[str] = "export.format.epub"

    def export(self, book: ExportBook, opts: ExportOptions, out: Path) -> None:
        files = [f"ch{i:04d}.xhtml" for i in range(1, len(book.chapters) + 1)]
        cover = None
        if opts.cover:
            media_type = _COVER_TYPES.get(opts.cover.suffix.lower())
            if media_type is None:
                raise ValueError(f"cover must be JPEG or PNG, got {opts.cover.suffix}")
            cover = (f"cover{opts.cover.suffix.lower()}", media_type)
        with zipfile.ZipFile(out, "w") as zf:
            # The mimetype entry must come first and be stored uncompressed.
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

            def put(name: str, data: str | bytes) -> None:
                zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)

            put("META-INF/container.xml", CONTAINER)
            put("OEBPS/content.opf", _opf(book, files, cover))
            put("OEBPS/nav.xhtml", _nav(book, files))
            put("OEBPS/toc.ncx", _ncx(book, files))
            put("OEBPS/style.css", STYLE)
            if cover and opts.cover:
                put(f"OEBPS/{cover[0]}", opts.cover.read_bytes())
                body = (
                    f'<div class="cover"><img src="{cover[0]}" alt="{_a(book.work.title)}"/></div>'
                )
                put("OEBPS/cover.xhtml", _page(book.work.target_lang, book.work.title, body, False))
            for ch, name in zip(book.chapters, files, strict=True):
                put(f"OEBPS/{name}", chapter_xhtml(ch, book.work, opts))
