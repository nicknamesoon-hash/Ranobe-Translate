"""Plural categories (CLDR rules) for the interface languages."""

from __future__ import annotations

from collections.abc import Callable


def _uk(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "one"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "few"
    return "many"


def _en(n: int) -> str:
    return "one" if n == 1 else "other"


RULES: dict[str, Callable[[int], str]] = {"uk": _uk, "en": _en}
CATEGORIES: dict[str, tuple[str, ...]] = {"uk": ("one", "few", "many"), "en": ("one", "other")}


def plural_category(locale: str, n: int) -> str:
    return RULES.get(locale, _en)(abs(n))
