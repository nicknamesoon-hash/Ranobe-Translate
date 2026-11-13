"""Master password dialog, shown at start when keys live in the encrypted file store."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ranobe.i18n import t
from ranobe.services.secrets import WrongPassword
from ranobe.ui.context import UiContext
from ranobe.ui.theme.tokens import Space

MIN_LENGTH = 8


def master_password_dialog(ctx: UiContext, on_done: Callable[[], None]) -> ft.AlertDialog:
    state = ctx.state
    new = state.master_password_is_new
    password = ft.TextField(
        label=t("master.password"), password=True, can_reveal_password=True, autofocus=True
    )
    repeat = ft.TextField(label=t("master.repeat"), password=True, visible=new)
    remember = ft.Checkbox(label=t("master.remember"), value=False)
    error = ft.Text("", color=ft.Colors.ERROR, visible=False)

    def fail(key: str) -> None:
        error.value, error.visible = t(key), True
        error.update()

    def submit(_: ft.Event) -> None:
        value = password.value or ""
        if new and len(value) < MIN_LENGTH:
            return fail("master.too_short")
        if new and value != repeat.value:
            return fail("master.mismatch")
        try:
            state.unlock(value, remember=bool(remember.value))
        except WrongPassword:
            return fail("master.wrong")
        ctx.close_dialog()
        on_done()

    password.on_submit = submit
    return ft.AlertDialog(
        modal=True,
        icon=ft.Icon(ft.Icons.LOCK_OUTLINE),
        title=ft.Text(t("master.title_new") if new else t("master.title")),
        content=ft.Column(
            [
                ft.Text(t("master.explain")),
                password,
                repeat,
                remember,
                ft.Text(t("master.remember_hint"), size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                error,
            ],
            tight=True,
            spacing=Space.M,
            width=400,
        ),
        actions=[ft.FilledButton(t("master.unlock"), on_click=submit)],
    )
