"""Placing note markers into translated text. Pure logic shared by all exporters."""

from __future__ import annotations

from ranobe.core.models import Note


def split_at_anchors(text: str, notes: list[Note]) -> list[str | Note]:
    """Split `text` into pieces with each note right after the first occurrence of its anchor.

    A note whose anchor is not in the text (the translation was edited) goes to the end, so
    no note is ever lost. Text pieces are never empty; notes keep their given order when they
    share a position.
    """
    placed: list[tuple[int, int, Note]] = []
    for order, note in enumerate(notes):
        found = text.find(note.anchor) if note.anchor else -1
        position = found + len(note.anchor) if found >= 0 else len(text)
        placed.append((position, order, note))
    placed.sort(key=lambda p: (p[0], p[1]))

    pieces: list[str | Note] = []
    start = 0
    for position, _, note in placed:
        if position > start:
            pieces.append(text[start:position])
            start = position
        pieces.append(note)
    if start < len(text):
        pieces.append(text[start:])
    return pieces
