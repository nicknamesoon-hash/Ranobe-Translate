"""Design tokens: the only source of colors, spacing, radii and durations in the UI.

Plain values without Flet, so they can be tested and reused anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from ranobe.core.models import NoteType, SegmentStatus

SEED_COLOR = "#4F5BD5"  # indigo; Material 3 derives light and dark schemes from it
FONT_FAMILY = "Noto Sans"  # i18n: ignore (font name)
FONT_FILES = {FONT_FAMILY: "fonts/NotoSans-Variable.ttf"}  # relative to ranobe/assets


class Space:
    XS = 4
    S = 8
    M = 12
    L = 16
    XL = 24
    XXL = 32
    XXXL = 48


class Radius:
    S = 4
    M = 8
    L = 16
    XL = 28


class Breakpoint:
    """Window width in logical pixels."""

    MEDIUM = 600  # below: phone layout with a bottom navigation bar
    EXPANDED = 1024  # from here: side panels next to the content


@dataclass(frozen=True)
class Durations:
    fast: int = 150  # hover, chips
    normal: int = 250  # panels appearing
    slow: int = 400  # page transitions

    @classmethod
    def for_motion(cls, reduce_motion: bool) -> Durations:
        return cls(0, 0, 0) if reduce_motion else cls()


# Semantic colors, as (light, dark).
STATUS_COLORS: dict[SegmentStatus, tuple[str, str]] = {
    SegmentStatus.PENDING: ("#8A8A99", "#9A9AAB"),
    SegmentStatus.TRANSLATED: ("#2E7D32", "#81C784"),
    SegmentStatus.NEEDS_REVIEW: ("#C62828", "#EF9A9A"),
    SegmentStatus.REVIEWED: ("#1565C0", "#90CAF9"),
    SegmentStatus.EDITED: ("#6A1B9A", "#CE93D8"),
}
NOTE_COLORS: dict[NoteType, tuple[str, str]] = {
    NoteType.UNTRANSLATABLE: ("#AD1457", "#F48FB1"),
    NoteType.WORDPLAY: ("#EF6C00", "#FFCC80"),
    NoteType.CULTURAL: ("#00838F", "#80DEEA"),
    NoteType.TERM: ("#283593", "#9FA8DA"),
    NoteType.REFERENCE: ("#4E342E", "#BCAAA4"),
    NoteType.TRANSLATOR_CHOICE: ("#558B2F", "#C5E1A5"),
}
DISPUTE_HIGHLIGHT = ("#FFF3C4", "#5C4B00")


def pick(pair: tuple[str, str], dark: bool) -> str:
    return pair[1] if dark else pair[0]
