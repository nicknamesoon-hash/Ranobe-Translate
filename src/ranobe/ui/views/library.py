"""Library: the user's works as a list or grid, with search and import."""

from __future__ import annotations

import flet as ft

from ranobe.core.models import SOURCE_LANGUAGES, TARGET_LANGUAGES
from ranobe.i18n import t
from ranobe.services.importers import ImportFailed, UnsupportedFormat, supported_extensions
from ranobe.ui.components.common import card, empty_state, muted, page_title
from ranobe.ui.context import UiContext
from ranobe.ui.layout.breakpoints import Layout
from ranobe.ui.state import Topic, WorkSummary
from ranobe.ui.theme.tokens import Space


class LibraryView:
    topics = frozenset({Topic.WORKS})

    def __init__(self, ctx: UiContext):
        self.ctx = ctx
        self.results = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=Space.S)

    def build(self) -> ft.Control:
        memory = self.ctx.memory
        search = ft.TextField(
            value=memory.library_query,
            hint_text=t("library.search"),
            prefix_icon=ft.Icons.SEARCH,
            dense=True,
            expand=True,
            on_change=self._on_search,
        )
        toggle = ft.IconButton(
            icon=ft.Icons.VIEW_LIST if memory.library_grid else ft.Icons.GRID_VIEW,
            tooltip=t("library.as_list") if memory.library_grid else t("library.as_grid"),
            on_click=self._toggle_grid,
        )
        import_button = ft.FilledButton(
            t("library.import"), icon=ft.Icons.UPLOAD_FILE, on_click=self._on_import
        )
        self._fill_results()
        return ft.Column(
            [
                page_title(t("nav.library"), import_button),
                ft.Row([search, toggle]),
                self.results,
            ],
            spacing=Space.L,
            expand=True,
        )

    # --- results ---

    def _fill_results(self) -> None:
        works = self.ctx.state.works(self.ctx.memory.library_query)
        if not works:
            searching = bool(self.ctx.memory.library_query.strip())
            self.results.controls = [
                empty_state(
                    ft.Icons.SEARCH if searching else ft.Icons.MENU_BOOK,
                    t("library.no_results") if searching else t("library.empty.title"),
                    t("library.no_results_hint") if searching else t("library.empty.hint"),
                )
            ]
            return
        if self.ctx.memory.library_grid:
            extent = 220 if self.ctx.layout is Layout.COMPACT else 260
            grid = ft.GridView(
                [self._tile(w, grid=True) for w in works],
                max_extent=extent,
                child_aspect_ratio=0.9,
                spacing=Space.M,
                run_spacing=Space.M,
                expand=True,
            )
            self.results.controls = [grid]
        else:
            self.results.controls = [self._tile(w, grid=False) for w in works]

    def _tile(self, summary: WorkSummary, grid: bool) -> ft.Control:
        w = summary.work
        title = ft.Text(
            w.title,
            theme_style=ft.TextThemeStyle.TITLE_MEDIUM,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
            expand=True,
        )
        editor = ft.IconButton(
            ft.Icons.EDIT_NOTE,
            tooltip=t("library.open_editor"),
            on_click=lambda _, wid=w.id: self._open(wid, "/editor"),
        )
        lines: list[ft.Control] = [
            ft.Row([title, editor], vertical_alignment=ft.CrossAxisAlignment.START),
            muted(" · ".join(filter(None, [w.author, f"{w.source_lang} → {w.target_lang}"]))),
            ft.ProgressBar(value=summary.fraction, border_radius=4),
            muted(t("library.progress", done=summary.done, total=summary.total)),
        ]
        if summary.needs_review:
            lines.append(
                ft.Text(t("library.needs_review", n=summary.needs_review), color=ft.Colors.ERROR)
            )
        column = ft.Column(lines, spacing=Space.S, tight=not grid)
        return card(column, on_click=lambda _, wid=w.id: self._open(wid))

    # --- events ---

    def _on_search(self, e: ft.Event) -> None:
        self.ctx.memory.library_query = e.control.value or ""
        self._fill_results()
        self.results.update()

    def _toggle_grid(self, _: ft.Event) -> None:
        self.ctx.memory.library_grid = not self.ctx.memory.library_grid
        self.ctx.state.notify(Topic.WORKS)

    def _open(self, work_id, route: str = "/translate") -> None:
        self.ctx.memory.selected_work = work_id
        self.ctx.navigate(route)

    async def _on_import(self, _: ft.Event) -> None:
        exts = [e.lstrip(".") for e in supported_extensions()]
        path = await self.ctx.pick_file(exts)
        if path is None:
            return
        self._ask_languages(path)

    def _ask_languages(self, path) -> None:
        settings = self.ctx.state.settings
        source = ft.Dropdown(
            label=t("library.source_lang"),
            value=SOURCE_LANGUAGES[0],
            options=[ft.DropdownOption(key=c, text=t(f"lang.{c}")) for c in SOURCE_LANGUAGES],
        )
        target = ft.Dropdown(
            label=t("library.target_lang"),
            value=settings.default_target_lang,
            options=[ft.DropdownOption(key=c, text=t(f"lang.{c}")) for c in TARGET_LANGUAGES],
        )

        def confirm(_: ft.Event) -> None:
            self.ctx.close_dialog()
            try:
                work = self.ctx.state.import_path(path, source.value, target.value)
            except (ImportFailed, UnsupportedFormat, OSError) as err:
                self.ctx.toast(t("library.import_failed", error=str(err)))
                return
            self.ctx.toast(t("library.imported", title=work.title))

        self.ctx.show_dialog(
            ft.AlertDialog(
                title=ft.Text(t("library.import_title")),
                content=ft.Column([muted(path.name), source, target], tight=True),
                actions=[
                    ft.TextButton(t("common.cancel"), on_click=lambda _: self.ctx.close_dialog()),
                    ft.FilledButton(t("library.import"), on_click=confirm),
                ],
            )
        )
