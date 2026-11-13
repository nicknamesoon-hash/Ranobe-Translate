"""Applying the theme to a Flet page: light, dark or system, switchable without a restart."""

from __future__ import annotations

import flet as ft

from ranobe.ui.theme.tokens import FONT_FAMILY, FONT_FILES, SEED_COLOR, Durations

THEME_MODES = {
    "light": ft.ThemeMode.LIGHT,
    "dark": ft.ThemeMode.DARK,
    "system": ft.ThemeMode.SYSTEM,
}


def _theme() -> ft.Theme:
    return ft.Theme(color_scheme_seed=SEED_COLOR, font_family=FONT_FAMILY, use_material3=True)


def apply_theme(page: ft.Page, mode: str, reduce_motion: bool) -> None:
    page.fonts = dict(FONT_FILES)
    page.theme = _theme()
    page.dark_theme = _theme()
    page.theme_mode = THEME_MODES.get(mode, ft.ThemeMode.SYSTEM)
    duration = Durations.for_motion(reduce_motion).normal
    page.theme_animation_style = ft.AnimationStyle(duration=duration)


def is_dark(page: ft.Page) -> bool:
    if page.theme_mode == ft.ThemeMode.DARK:
        return True
    if page.theme_mode == ft.ThemeMode.LIGHT:
        return False
    return page.platform_brightness == ft.Brightness.DARK
