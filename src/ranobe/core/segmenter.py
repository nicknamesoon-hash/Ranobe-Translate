"""Split raw text into segments: paragraphs, headings and scene separators.

A segment is the unit of translation, review, notes and sync. Segments are never cut by the
chunker later, so oversized paragraphs are split here, at sentence boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ranobe.core.models import SegmentKind

MAX_SEGMENT_CHARS = 1500

# Sentence end: CJK or Latin terminal punctuation, optionally followed by closing quotes or
# brackets. CJK text has no space after the punctuation, so whitespace is optional there.
_CLOSERS = re.escape("」』）)]】〉》\"'”’")
_SENTENCE_END = re.compile(
    rf"""
      [。！？…‥]+[{_CLOSERS}]*\s*        # CJK: no space needed after the punctuation
    | [.!?]+[{_CLOSERS}]*\s+             # Latin: whitespace required, so "3.14" stays whole
    """,
    re.VERBOSE,
)

_HEADING = re.compile(
    r"""^\s*(?:
        第\s*[0-9０-９一二三四五六七八九十百千零〇]+\s*[章話话節节幕部巻卷]   # 第3章, 第十二話
      | 제\s*[0-9]+\s*[화장부권]                                             # 제12화
      | (?:chapter|prologue|epilogue|interlude|afterword|side\s+story)\b      # English
      | (?:プロローグ|エピローグ|あとがき|幕間|序章|終章|閑話|番外編)
      | (?:프롤로그|에필로그|후기|외전)
    )""",
    re.IGNORECASE | re.VERBOSE,
)

_SEPARATOR = re.compile(r"^\s*[*＊◆◇■□●○◎★☆♢♦\-—=~～・\s]{3,}\s*$")


@dataclass(frozen=True)
class RawSegment:
    kind: SegmentKind
    text: str


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("﻿", "")
    return "\n".join(line.rstrip() for line in text.split("\n"))


def split_paragraphs(text: str) -> list[str]:
    """Return paragraphs.

    Two layouts are common: paragraphs separated by blank lines (EPUB, English TXT) and one
    paragraph per line with no blank lines (most Japanese/Korean web novel dumps). If blank
    lines make up at least a fifth of line breaks, blocks are paragraphs; otherwise each line is.
    """
    text = normalize(text).strip("\n")
    if not text.strip():
        return []
    lines = text.split("\n")
    blank = sum(1 for line in lines if not line.strip())
    if blank * 5 >= len(lines):
        blocks = re.split(r"\n\s*\n", text)
        return [b.strip() for b in blocks if b.strip()]
    return [line.strip() for line in lines if line.strip()]


def split_sentences(paragraph: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for m in _SENTENCE_END.finditer(paragraph):
        end = m.end()
        piece = paragraph[start:end].strip()
        if piece:
            parts.append(piece)
        start = end
    rest = paragraph[start:].strip()
    if rest:
        parts.append(rest)
    return parts


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    pieces: list[str] = []
    current = ""
    for sentence in split_sentences(paragraph):
        while len(sentence) > max_chars:  # a single runaway sentence: hard cut
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        sep = "" if _is_cjk(sentence[:1]) else " "
        if current and len(current) + len(sep) + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current}{sep}{sentence}" if current else sentence
    if current:
        pieces.append(current)
    return pieces


def _is_cjk(ch: str) -> bool:
    return bool(ch) and ("　" <= ch <= "鿿" or "가" <= ch <= "힯" or "＀" <= ch <= "￯")


def classify(paragraph: str) -> SegmentKind:
    if _SEPARATOR.match(paragraph):
        return SegmentKind.SEPARATOR
    if len(paragraph) <= 80 and _HEADING.match(paragraph):
        return SegmentKind.HEADING
    return SegmentKind.PARAGRAPH


def segment_text(text: str, max_chars: int = MAX_SEGMENT_CHARS) -> list[RawSegment]:
    result: list[RawSegment] = []
    for para in split_paragraphs(text):
        kind = classify(para)
        if kind is SegmentKind.PARAGRAPH:
            result.extend(RawSegment(kind, piece) for piece in _split_long(para, max_chars))
        else:
            result.append(RawSegment(kind, para))
    return result
