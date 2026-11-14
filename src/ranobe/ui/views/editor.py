"""Editor: a chapter as rows of original | translation (one column on a phone)."""

from __future__ import annotations

import flet as ft

from ranobe.core.models import Segment, SegmentKind
from ranobe.i18n import t
from ranobe.ui.components.common import empty_state, muted
from ranobe.ui.context import UiContext
from ranobe.ui.editor_model import EditorModel
from ranobe.ui.layout.breakpoints import Layout
from ranobe.ui.state import Topic
from ranobe.ui.theme.tokens import STATUS_COLORS, Radius, Space, pick


class EditorView:
    # Not PROGRESS: rebuilding the list on every translated chunk would reset the scroll.
    topics = frozenset({Topic.WORKS})

    def __init__(self, ctx: UiContext):
        self.ctx = ctx
        self.model: EditorModel | None = None
        self.show_original_compact = False

    def _model(self) -> EditorModel | None:
        work_id = self.ctx.memory.selected_work
        if work_id is None:
            return None
        if self.model is None or self.model.work.id != work_id:
            self.model = EditorModel(self.ctx.state.repos, work_id)
        return self.model

    def build(self) -> ft.Control:
        model = self._model()
        if model is None or model.chapter is None:
            return empty_state(
                ft.Icons.EDIT_NOTE,
                t("editor.no_work.title"),
                t("editor.no_work.hint"),
                ft.FilledButton(t("nav.library"), on_click=lambda _: self.ctx.navigate("/library")),
            )
        compact = self.ctx.layout is Layout.COMPACT
        segments = model.segments()
        rows = [self._row(s, compact) for s in segments]
        return ft.Column(
            [self._header(model, compact), ft.ListView(rows, spacing=Space.XS, expand=True)],
            spacing=Space.M,
            expand=True,
        )

    # --- header ---

    def _header(self, model: EditorModel, compact: bool) -> ft.Control:
        back = ft.IconButton(
            ft.Icons.ARROW_BACK,
            tooltip=t("common.back"),
            on_click=lambda _: self.ctx.navigate("/library"),
        )
        chapter = ft.Dropdown(
            value=str(model.chapter_index),
            options=[
                ft.DropdownOption(key=str(i), text=c.title) for i, c in enumerate(model.chapters)
            ],
            on_select=lambda e: self._open(int(e.control.value)),
            dense=True,
            expand=True,
        )
        prev_button = ft.IconButton(
            ft.Icons.CHEVRON_LEFT,
            tooltip=t("editor.previous_chapter"),
            disabled=not model.has_previous,
            on_click=lambda _: self._open(model.chapter_index - 1),
        )
        next_button = ft.IconButton(
            ft.Icons.CHEVRON_RIGHT,
            tooltip=t("editor.next_chapter"),
            disabled=not model.has_next,
            on_click=lambda _: self._open(model.chapter_index + 1),
        )
        controls: list[ft.Control] = [back, prev_button, chapter, next_button]
        if compact:
            controls.append(
                ft.IconButton(
                    ft.Icons.TRANSLATE,
                    selected=self.show_original_compact,
                    tooltip=t("editor.show_original"),
                    on_click=self._toggle_original,
                )
            )
        title = ft.Text(
            model.work.title,
            theme_style=ft.TextThemeStyle.TITLE_LARGE,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        return ft.Column([title, ft.Row(controls, spacing=Space.XS)], spacing=Space.S)

    # --- rows ---

    def _row(self, seg: Segment, compact: bool) -> ft.Control:
        dark = self.ctx.dark
        translated = seg.translation is not None
        translation = ft.Text(
            seg.translation if translated else t("editor.not_translated"),
            selectable=True,
            italic=not translated,
            color=None if translated else ft.Colors.ON_SURFACE_VARIANT,
            weight=ft.FontWeight.W_600 if seg.kind is SegmentKind.HEADING else None,
        )
        original = ft.Text(
            seg.source,
            selectable=True,
            color=ft.Colors.ON_SURFACE_VARIANT,
            size=13 if compact else None,
        )
        if compact:
            body = ft.Column(
                [translation, original] if self.show_original_compact else [translation],
                spacing=Space.XS,
                expand=True,
            )
        else:
            body = ft.Row(
                [ft.Container(original, expand=1), ft.Container(translation, expand=1)],
                vertical_alignment=ft.CrossAxisAlignment.START,
                spacing=Space.L,
                expand=True,
            )
        status_bar = ft.Container(
            width=3, bgcolor=pick(STATUS_COLORS[seg.status], dark), border_radius=Radius.S
        )
        return ft.Container(
            ft.Row(
                [status_bar, ft.Container(muted(str(seg.index + 1), size=11), width=28), body],
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                intrinsic_height=True,  # lets the status bar stretch to the row height
                spacing=Space.S,
            ),
            padding=ft.Padding.symmetric(vertical=Space.S, horizontal=Space.XS),
            border=ft.Border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        )

    # --- actions ---

    def _open(self, index: int) -> None:
        if self.model:
            self.model.open_chapter(index)
            self.ctx.state.notify(Topic.WORKS)

    def _toggle_original(self, _: ft.Event) -> None:
        self.show_original_compact = not self.show_original_compact
        self.ctx.state.notify(Topic.WORKS)
