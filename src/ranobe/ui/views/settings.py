"""Settings: interface language, theme, animations, defaults for new works and accounts."""

from __future__ import annotations

import flet as ft

from ranobe.core.models import TARGET_LANGUAGES
from ranobe.i18n import LOCALES, t
from ranobe.services.providers import provider_infos
from ranobe.ui.components.common import card, muted, page_title, section_title
from ranobe.ui.context import UiContext
from ranobe.ui.layout.breakpoints import Layout
from ranobe.ui.state import Topic
from ranobe.ui.theme.tokens import Space

THEMES = ("light", "dark", "system")


class SettingsView:
    topics = frozenset({Topic.SETTINGS})

    def __init__(self, ctx: UiContext):
        self.ctx = ctx

    def build(self) -> ft.Control:
        s = self.ctx.state.settings
        update = self.ctx.state.update_settings

        def choice(values, current, key_prefix, field):
            if self.ctx.layout is Layout.COMPACT:  # segments get too narrow on a phone
                return ft.RadioGroup(
                    ft.Column(
                        [ft.Radio(value=v, label=t(f"{key_prefix}.{v}")) for v in values],
                        spacing=0,
                    ),
                    value=current,
                    on_change=lambda e: update(**{field: e.control.value}),
                )
            return ft.SegmentedButton(
                segments=[
                    ft.Segment(value=v, label=ft.Text(t(f"{key_prefix}.{v}"))) for v in values
                ],
                selected=[current],
                on_change=lambda e: update(**{field: e.control.selected[0]}),
            )

        provider = ft.Dropdown(
            label=t("settings.default_provider"),
            value=s.default_provider or provider_infos()[0].id,
            options=[ft.DropdownOption(key=p.id, text=p.name) for p in provider_infos()],
            on_select=lambda e: update(default_provider=e.control.value),
        )
        target = ft.Dropdown(
            label=t("settings.default_target"),
            value=s.default_target_lang,
            options=[ft.DropdownOption(key=c, text=t(f"lang.{c}")) for c in TARGET_LANGUAGES],
            on_select=lambda e: update(default_target_lang=e.control.value),
        )
        sections = [
            card(
                ft.Column(
                    [
                        section_title(t("settings.language")),
                        choice(LOCALES, s.ui_locale, "locale", "ui_locale"),
                    ],
                    spacing=Space.M,
                )
            ),
            card(
                ft.Column(
                    [
                        section_title(t("settings.theme")),
                        choice(THEMES, s.theme, "settings.theme", "theme"),
                        ft.Switch(
                            label=t("settings.reduce_motion"),
                            value=s.reduce_motion,
                            on_change=lambda e: update(reduce_motion=bool(e.control.value)),
                        ),
                        muted(t("settings.reduce_motion_hint")),
                    ],
                    spacing=Space.M,
                )
            ),
            card(
                ft.Column(
                    [section_title(t("settings.defaults")), target, provider], spacing=Space.M
                )
            ),
        ]
        return ft.Column(
            [page_title(t("nav.settings")), *sections],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=Space.L,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
