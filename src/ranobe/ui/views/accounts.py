"""Accounts: the key pool across providers, adding keys and checking them in the background."""

from __future__ import annotations

import flet as ft

from ranobe.core.models import ProviderAccount
from ranobe.i18n import t
from ranobe.services.providers import provider_infos
from ranobe.ui.components.common import card, empty_state, muted, page_title
from ranobe.ui.context import UiContext
from ranobe.ui.state import Topic
from ranobe.ui.theme.tokens import Space


class AccountsView:
    topics = frozenset({Topic.ACCOUNTS})

    def __init__(self, ctx: UiContext):
        self.ctx = ctx
        self.checking = False

    def build(self) -> ft.Control:
        accounts = self.ctx.state.accounts()
        actions = [
            ft.OutlinedButton(
                t("accounts.check"),
                icon=ft.Icons.REFRESH,
                on_click=self._check,
                disabled=self.checking or not accounts,
            ),
            ft.FilledButton(t("accounts.add"), icon=ft.Icons.ADD, on_click=self._add_dialog),
        ]
        if accounts:
            items: list[ft.Control] = [self._row(a) for a in accounts]
        else:
            items = [empty_state(ft.Icons.KEY, t("accounts.empty.title"), t("accounts.empty.hint"))]
        return ft.Column(
            [
                page_title(t("nav.accounts")),
                ft.Row(actions, wrap=True, spacing=Space.S),
                muted(t("accounts.intro")),
                ft.Column(items, spacing=Space.S, scroll=ft.ScrollMode.AUTO, expand=True),
            ],
            spacing=Space.L,
            expand=True,
        )

    def _row(self, a: ProviderAccount) -> ft.Control:
        check = self.ctx.state.key_checks.get(a.id)
        if check is None:
            badge: ft.Control = ft.Container()
        elif check.ok:
            badge = ft.Icon(
                ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN, tooltip=t("accounts.check.ok")
            )
        else:
            badge = ft.Icon(
                ft.Icons.ERROR_OUTLINE,
                color=ft.Colors.ERROR,
                tooltip=t("accounts.check.failed", detail=_check_detail(check.detail)),
            )
        details = t(
            "accounts.details",
            provider=a.provider_id,
            model=a.model,
            rpm=f"{a.rpm:g}",
            priority=a.priority,
        )
        if a.last_error:
            details += "\n" + t("accounts.last_error", error=a.last_error[:120])
        return card(
            ft.Row(
                [
                    ft.Column(
                        [ft.Text(a.label, weight=ft.FontWeight.W_500), muted(details)],
                        spacing=Space.XS,
                        expand=True,
                    ),
                    badge,
                    ft.Switch(
                        value=a.enabled,
                        tooltip=t("accounts.enabled"),
                        on_change=lambda e, aid=a.id: self.ctx.state.set_account_enabled(
                            aid, bool(e.control.value)
                        ),
                    ),
                    ft.IconButton(
                        ft.Icons.DELETE_OUTLINE,
                        tooltip=t("common.delete"),
                        on_click=lambda _, acc=a: self._confirm_delete(acc),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

    # --- actions ---

    async def _check(self, _: ft.Event) -> None:
        self.checking = True
        self.ctx.state.notify(Topic.ACCOUNTS)
        try:
            await self.ctx.state.check_keys()
        finally:
            self.checking = False
            self.ctx.state.notify(Topic.ACCOUNTS)

    def _confirm_delete(self, account: ProviderAccount) -> None:
        def delete(_: ft.Event) -> None:
            self.ctx.close_dialog()
            self.ctx.state.remove_account(account.id)

        self.ctx.show_dialog(
            ft.AlertDialog(
                title=ft.Text(t("accounts.delete.title")),
                content=ft.Text(t("accounts.delete.body", label=account.label)),
                actions=[
                    ft.TextButton(t("common.cancel"), on_click=lambda _: self.ctx.close_dialog()),
                    ft.FilledButton(t("common.delete"), on_click=delete),
                ],
            )
        )

    def _add_dialog(self, _: ft.Event) -> None:
        infos = provider_infos()
        default = self.ctx.state.settings.default_provider or infos[0].id
        provider = ft.Dropdown(
            label=t("accounts.provider"),
            value=default,
            options=[
                ft.DropdownOption(
                    key=p.id,
                    text=f"{p.name} · " + t("accounts.free" if p.free_tier else "accounts.paid"),
                )
                for p in infos
            ],
            expand=True,
        )
        label = ft.TextField(label=t("accounts.label"))
        key = ft.TextField(label=t("accounts.key"), password=True, can_reveal_password=True)
        model = ft.TextField(label=t("accounts.model"), hint_text=t("accounts.model_hint"))
        rpm = ft.TextField(
            label=t("accounts.rpm"), value="5", keyboard_type=ft.KeyboardType.NUMBER, expand=True
        )
        priority = ft.TextField(
            label=t("accounts.priority"),
            value="100",
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
        )
        link = ft.TextButton(t("accounts.get_key"), icon=ft.Icons.OPEN_IN_NEW)
        error = ft.Text("", color=ft.Colors.ERROR, visible=False)

        def sync_link(_: ft.Event | None = None) -> None:
            info = next(p for p in infos if p.id == provider.value)
            link.url = info.key_url

        provider.on_select = lambda e: (sync_link(e), link.update())
        sync_link()

        def save(_: ft.Event) -> None:
            try:
                self.ctx.state.add_account(
                    provider.value,
                    label.value or "",
                    key.value or "",
                    model.value or "",
                    rpm=float(rpm.value or 5),
                    priority=int(priority.value or 100),
                )
            except ValueError:
                error.value, error.visible = t("accounts.add_error"), True
                error.update()
                return
            self.ctx.close_dialog()

        self.ctx.show_dialog(
            ft.AlertDialog(
                title=ft.Text(t("accounts.add")),
                content=ft.Column(
                    [ft.Row([provider]), link, label, key, model, ft.Row([rpm, priority]), error],
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    spacing=Space.M,
                    width=420,
                    scroll=ft.ScrollMode.AUTO,
                ),
                actions=[
                    ft.TextButton(t("common.cancel"), on_click=lambda _: self.ctx.close_dialog()),
                    ft.FilledButton(t("common.save"), on_click=save),
                ],
            )
        )


def _check_detail(detail: str) -> str:
    known = {"no_key": "accounts.check.no_key", "model_missing": "accounts.check.model_missing"}
    return t(known[detail]) if detail in known else detail
