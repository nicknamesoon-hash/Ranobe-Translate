"""Flet entry point: build the state, theme and shell for a page."""

from __future__ import annotations

from pathlib import Path

import flet as ft

from ranobe.core.redact import install_log_redaction
from ranobe.services.secrets import select_store
from ranobe.storage import paths
from ranobe.storage.db import Database
from ranobe.storage.repositories import Repositories
from ranobe.storage.settings import AppSettings
from ranobe.ui.components.master_password import master_password_dialog
from ranobe.ui.layout.shell import Shell
from ranobe.ui.state import AppState
from ranobe.ui.theme.theme import apply_theme
from ranobe.ui.views.accounts import AccountsView
from ranobe.ui.views.library import LibraryView
from ranobe.ui.views.settings import SettingsView
from ranobe.ui.views.translate import TranslateView

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
VIEWS = {
    "/library": LibraryView,
    "/translate": TranslateView,
    "/accounts": AccountsView,
    "/settings": SettingsView,
}


def create_state() -> AppState:
    settings = AppSettings.load(paths.settings_path())
    repos = Repositories(Database(paths.db_path()))
    secrets = select_store(paths.data_dir(), settings.secret_backend)
    return AppState(repos, settings, paths.settings_path(), secrets)


def main(page: ft.Page, state: AppState | None = None) -> None:
    install_log_redaction()
    state = state or create_state()
    apply_theme(page, state.settings.theme, state.settings.reduce_motion)
    page.window.min_width, page.window.min_height = 360, 560
    shell = Shell(page, state, VIEWS)
    shell.render()
    if state.needs_master_password:
        shell.ctx.show_dialog(master_password_dialog(shell.ctx, on_done=shell.refresh))

    async def on_close(_: ft.Event) -> None:
        shell.close()
        await state.aclose()

    page.on_close = on_close


def run(web: bool = False, port: int = 0) -> None:
    view = ft.AppView.WEB_BROWSER if web else ft.AppView.FLET_APP
    ft.run(main, view=view, port=port, assets_dir=str(ASSETS_DIR))
