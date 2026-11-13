"""Which layout fits a window width. Pure logic, tested without Flet."""

from __future__ import annotations

from enum import StrEnum

from ranobe.ui.theme.tokens import Breakpoint


class Layout(StrEnum):
    COMPACT = "compact"  # phone: bottom navigation bar, one column
    MEDIUM = "medium"  # tablet / small window: navigation rail
    EXPANDED = "expanded"  # desktop: rail with labels, side panels


def layout_for(width: float | None) -> Layout:
    if width is None or width <= 0:
        return Layout.EXPANDED  # unknown yet: the desktop default
    if width < Breakpoint.MEDIUM:
        return Layout.COMPACT
    if width < Breakpoint.EXPANDED:
        return Layout.MEDIUM
    return Layout.EXPANDED
