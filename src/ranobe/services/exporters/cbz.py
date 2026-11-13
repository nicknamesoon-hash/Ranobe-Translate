"""CBZ export: the translation rendered as page images, for comic readers and easy sharing.

Pages are drawn with the bundled Noto Serif font (works on every platform, Android included).
The cover (or a generated title page) comes first, every chapter starts on a new page, and
notes are printed at the bottom of the page where their marker is.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import ClassVar

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ranobe.core.footnotes import split_at_anchors
from ranobe.core.models import SegmentKind
from ranobe.services.exporters.base import (
    ExportBook,
    ExportOptions,
    ExportSegment,
    register_exporter,
)

FONTS = Path(__file__).resolve().parents[2] / "assets" / "fonts"
_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def marker(n: int) -> str:
    return str(n).translate(_SUPERSCRIPT)


@dataclass
class _Fonts:
    body: ImageFont.FreeTypeFont
    title: ImageFont.FreeTypeFont
    note: ImageFont.FreeTypeFont

    @classmethod
    def load(cls, size: int) -> _Fonts:
        regular, bold = FONTS / "NotoSerif-Regular.ttf", FONTS / "NotoSerif-Bold.ttf"
        return cls(
            body=ImageFont.truetype(str(regular), size),
            title=ImageFont.truetype(str(bold), round(size * 1.4)),
            note=ImageFont.truetype(str(regular), round(size * 0.75)),
        )


@dataclass
class _Line:
    text: str
    font: ImageFont.FreeTypeFont
    gap_before: int = 0
    centered: bool = False
    notes: list[tuple[int, str]] = field(default_factory=list)  # (number, text)


def _height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return round((ascent + descent) * 1.25)


def wrap(words: list[str], font: ImageFont.FreeTypeFont, width: int) -> list[list[str]]:
    """Greedy word wrap. A word wider than the line (CJK text has no spaces) is broken
    between characters."""
    lines: list[list[str]] = []
    current: list[str] = []
    for word in words:
        if font.getlength(word) > width:
            if current:
                lines.append(current)
                current = []
            chunk = ""
            for char in word:
                if chunk and font.getlength(chunk + char) > width:
                    lines.append([chunk])
                    chunk = ""
                chunk += char
            current = [chunk] if chunk else []
            continue
        if current and font.getlength(" ".join([*current, word])) > width:
            lines.append(current)
            current = []
        current.append(word)
    if current:
        lines.append(current)
    return lines


class _Layout:
    """Fills pages line by line, keeping room at the bottom for the page's notes."""

    def __init__(self, opts: ExportOptions):
        self.width, self.height = opts.page_size
        self.margin = round(self.width * 0.07)
        self.text_width = self.width - 2 * self.margin
        self.fonts = _Fonts.load(opts.font_size)
        self.pages: list[Image.Image] = []
        self._lines: list[_Line] = []
        self._notes: list[tuple[int, str]] = []
        self._used = 0

    # --- building ---

    def new_page(self) -> None:
        if self._lines or self._notes:
            self.pages.append(self._render())
        self._lines, self._notes, self._used = [], [], 0

    def add_title(self, title: str) -> None:
        self.new_page()
        for words in wrap(title.split(), self.fonts.title, self.text_width):
            self._add(_Line(" ".join(words), self.fonts.title, centered=True))
        self._used += _height(self.fonts.body)

    def add_segment(self, seg: ExportSegment, first_note: int, with_notes: bool) -> int:
        """Lay out one segment; returns the next free note number in the chapter."""
        gap = _height(self.fonts.body) // 3
        if seg.kind is SegmentKind.SEPARATOR:
            self._add(_Line(seg.text, self.fonts.body, gap_before=gap, centered=True))
            return first_note
        font = self.fonts.title if seg.kind is SegmentKind.HEADING else self.fonts.body
        words: list[str] = []
        word_notes: list[list[tuple[int, str]]] = []
        n = first_note
        for piece in split_at_anchors(seg.text, seg.notes if with_notes else []):
            if isinstance(piece, str):
                piece = " ".join(piece.splitlines())
                parts = piece.split(" ")
                if words and not piece.startswith(" "):  # continues the previous word
                    words[-1] += parts.pop(0)
                for part in parts:
                    if part:
                        words.append(part)
                        word_notes.append([])
            else:
                if not words:
                    words.append("")
                    word_notes.append([])
                words[-1] += marker(n)
                word_notes[-1].append((n, piece.text))
                n += 1
        index = 0
        for i, line_words in enumerate(wrap(words, font, self.text_width)):
            notes = [note for w in word_notes[index : index + len(line_words)] for note in w]
            index += len(line_words)
            self._add(_Line(" ".join(line_words), font, gap if i == 0 else 0, notes=notes))
        return n

    def _notes_height(self, notes: list[tuple[int, str]]) -> int:
        if not notes:
            return 0
        lines = sum(len(self._note_lines(n)) for n in notes)
        return lines * _height(self.fonts.note) + _height(self.fonts.note)  # + rule above

    def _note_lines(self, note: tuple[int, str]) -> list[str]:
        number, text = note
        words = f"{marker(number)} {text}".split()
        return [" ".join(w) for w in wrap(words, self.fonts.note, self.text_width)]

    def _add(self, line: _Line) -> None:
        room = self.height - 2 * self.margin
        need = line.gap_before + _height(line.font)
        if self._lines and (
            self._used + need + self._notes_height(self._notes + line.notes) > room
        ):
            self.new_page()
        if not self._lines:
            line.gap_before = 0
            need = _height(line.font)
        self._lines.append(line)
        self._notes += line.notes
        self._used += need

    # --- drawing ---

    def _blank(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        page = Image.new("L", (self.width, self.height), 255)
        return page, ImageDraw.Draw(page)

    def _render(self) -> Image.Image:
        page, draw = self._blank()
        y = self.margin
        for line in self._lines:
            y += line.gap_before
            x = self.margin
            if line.centered:
                x = (self.width - line.font.getlength(line.text)) / 2
            draw.text((x, y), line.text, font=line.font, fill=0)
            y += _height(line.font)
        if self._notes:
            note_lines = [t for n in self._notes for t in self._note_lines(n)]
            h = _height(self.fonts.note)
            y = self.height - self.margin - len(note_lines) * h
            rule_y = y - h // 2
            draw.line((self.margin, rule_y, self.margin + self.text_width // 3, rule_y), fill=0)
            for text in note_lines:
                draw.text((self.margin, y), text, font=self.fonts.note, fill=0)
                y += h
        return page

    def cover_page(self, path: Path) -> None:
        page, _ = self._blank()
        with Image.open(path) as img:
            fitted = ImageOps.contain(img.convert("L"), (self.width, self.height))
        page.paste(fitted, ((self.width - fitted.width) // 2, (self.height - fitted.height) // 2))
        self.pages.append(page)

    def title_page(self, title: str, author: str | None) -> None:
        page, draw = self._blank()
        title_lines = wrap(title.split(), self.fonts.title, self.text_width)
        lines = [(" ".join(words), self.fonts.title) for words in title_lines]
        if author:
            lines.append(("", self.fonts.body))
            lines.append((author, self.fonts.body))
        y = self.height // 3
        for text, font in lines:
            draw.text(((self.width - font.getlength(text)) / 2, y), text, font=font, fill=0)
            y += _height(font)
        self.pages.append(page)


def _comic_info(book: ExportBook, pages: int) -> str:
    w = book.work
    fields = {
        "Title": w.title,
        "Writer": w.author or "",
        "Summary": w.synopsis,
        "Genre": ", ".join(w.genres),
        "LanguageISO": w.target_lang,
        "PageCount": str(pages),
    }
    body = "".join(f"<{k}>{escape(v, quote=False)}</{k}>" for k, v in fields.items() if v)
    return f'<?xml version="1.0" encoding="utf-8"?>\n<ComicInfo>{body}</ComicInfo>\n'


@register_exporter
class CbzExporter:
    id: ClassVar[str] = "cbz"
    extension: ClassVar[str] = ".cbz"
    display_key: ClassVar[str] = "export.format.cbz"

    def export(self, book: ExportBook, opts: ExportOptions, out: Path) -> None:
        layout = _Layout(opts)
        if opts.cover:
            layout.cover_page(opts.cover)
        else:
            layout.title_page(book.work.title, book.work.author)
        for ch in book.chapters:
            layout.add_title(ch.title)
            n = 1
            for seg in ch.segments:
                n = layout.add_segment(seg, n, opts.with_notes)
        layout.new_page()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:  # PNG is already compressed
            digits = max(4, len(str(len(layout.pages))))
            for i, page in enumerate(layout.pages, start=1):
                buffer = io.BytesIO()
                page.save(buffer, "PNG", optimize=True)
                zf.writestr(f"{i:0{digits}d}.png", buffer.getvalue())
            zf.writestr("ComicInfo.xml", _comic_info(book, len(layout.pages)))
