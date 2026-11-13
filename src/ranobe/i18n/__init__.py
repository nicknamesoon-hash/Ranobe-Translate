"""Interface strings in Ukrainian and English.

    t("library.empty.title")                    # plain string
    t("translate.progress", done=3, total=40)   # placeholders
    t("library.works", n=5)                     # plural: value is {"one": …, "few": …, …}
    set_locale("en")                            # notifies subscribers, UI rebuilds itself

A missing key falls back to English, then to the key itself, so a gap is visible but never
crashes the interface.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from functools import cache
from importlib import resources

from ranobe.i18n.plural import plural_category

log = logging.getLogger(__name__)

LOCALES = ("uk", "en")
FALLBACK = "en"

_state = {"locale": "uk"}
_listeners: list[Callable[[str], None]] = []


@cache
def catalog(locale: str) -> dict[str, str | dict[str, str]]:
    path = resources.files("ranobe.i18n") / "locales" / f"{locale}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def get_locale() -> str:
    return _state["locale"]


def set_locale(locale: str) -> None:
    if locale not in LOCALES:
        raise ValueError(f"unsupported locale {locale!r}")
    if locale == _state["locale"]:
        return
    _state["locale"] = locale
    for listener in list(_listeners):
        listener(locale)


def on_locale_change(listener: Callable[[str], None]) -> Callable[[], None]:
    """Subscribe; returns a function that unsubscribes."""
    _listeners.append(listener)
    return lambda: _listeners.remove(listener) if listener in _listeners else None


def t(key: str, **params: object) -> str:
    locale = _state["locale"]
    value = catalog(locale).get(key)
    if value is None:
        locale = FALLBACK
        value = catalog(FALLBACK).get(key)
    if value is None:
        log.warning("missing i18n key %s", key)
        return key
    if isinstance(value, dict):
        n = params.get("n")
        if not isinstance(n, int):
            raise TypeError(f"plural key {key} needs an integer n")
        value = (
            value.get(plural_category(locale, n))
            or value.get("other")
            or next(iter(value.values()))
        )
    return value.format(**params) if params else value
