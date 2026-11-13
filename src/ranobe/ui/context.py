"""What every view gets: the app state plus a few UI services (navigation, dialogs, tasks)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import flet as ft

from ranobe.ui.layout.breakpoints import Layout
from ranobe.ui.state import AppState
from ranobe.ui.theme.theme import is_dark
from ranobe.ui.theme.tokens import Durations


@dataclass
class ViewMemory:
    """UI-only choices that survive a re-render (not stored on disk)."""

    library_query: str = ""
    library_grid: bool = False
    selected_work: UUID | None = None
    selected_chapters: dict[UUID, set[UUID]] = field(default_factory=dict)


class UiContext:
    def __init__(self, page: ft.Page, state: AppState, navigate: Callable[[str], None]):
        self.page = page
        self.state = state
        self.navigate = navigate
        self.memory = ViewMemory()
        self.layout = Layout.EXPANDED
        self._picker = ft.FilePicker()
        page.services.append(self._picker)

    @property
    def dark(self) -> bool:
        return is_dark(self.page)

    @property
    def durations(self) -> Durations:
        return Durations.for_motion(self.state.settings.reduce_motion)

    def run(self, coroutine_fn: Callable[..., Awaitable[Any]], *args: Any) -> None:
        """Run a coroutine in the background; the UI stays responsive."""
        self.page.run_task(coroutine_fn, *args)

    def show_dialog(self, dialog: ft.DialogControl) -> None:
        self.page.show_dialog(dialog)

    def close_dialog(self) -> None:
        self.page.pop_dialog()

    def toast(self, message: str) -> None:
        self.page.show_dialog(ft.SnackBar(ft.Text(message)))

    async def pick_file(self, extensions: list[str]) -> Path | None:
        files = await self._picker.pick_files(allowed_extensions=extensions)
        if not files or not files[0].path:
            return None
        return Path(files[0].path)
