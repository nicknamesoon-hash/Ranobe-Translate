"""Small reusable controls. All text comes in already translated."""

from __future__ import annotations

import flet as ft

from ranobe.core.models import SegmentStatus
from ranobe.i18n import t
from ranobe.ui.theme.tokens import STATUS_COLORS, Radius, Space, pick


def page_title(text: str, *actions: ft.Control) -> ft.Control:
    return ft.Row(
        [ft.Text(text, theme_style=ft.TextThemeStyle.HEADLINE_SMALL, expand=True), *actions],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def section_title(text: str) -> ft.Control:
    return ft.Text(text, theme_style=ft.TextThemeStyle.TITLE_MEDIUM)


def muted(text: str, size: int | None = None) -> ft.Text:
    return ft.Text(text, size=size, color=ft.Colors.ON_SURFACE_VARIANT)


def empty_state(icon: ft.IconData, title: str, hint: str, action: ft.Control | None = None):
    controls: list[ft.Control] = [
        ft.Icon(icon, size=56, color=ft.Colors.OUTLINE),
        ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM, text_align=ft.TextAlign.CENTER),
        ft.Text(hint, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
    ]
    if action:
        controls.append(action)
    return ft.Container(
        ft.Column(
            controls,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=Space.M,
        ),
        alignment=ft.Alignment.CENTER,
        padding=Space.XXL,
        expand=True,
    )


def status_chip(status: SegmentStatus, count: int, dark: bool) -> ft.Control:
    color = pick(STATUS_COLORS[status], dark)
    return ft.Container(
        ft.Row(
            [
                ft.Container(width=8, height=8, bgcolor=color, border_radius=4),
                ft.Text(f"{t('status.' + status.value)}: {count}", size=12),
            ],
            spacing=Space.XS,
            tight=True,
        ),
        padding=ft.Padding.symmetric(horizontal=Space.S, vertical=Space.XS),
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=Radius.L,
    )


def card(content: ft.Control, on_click=None) -> ft.Control:
    return ft.Card(
        ft.Container(content, padding=Space.L, on_click=on_click, border_radius=Radius.M),
        margin=0,
    )


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return t("time.unknown")
    minutes = int(seconds // 60)
    if minutes < 1:
        return t("time.under_minute")
    hours, minutes = divmod(minutes, 60)
    if hours:
        return t("time.hours_minutes", h=hours, m=minutes)
    return t("time.minutes", n=minutes)
