"""Translate: pick chapters, start or pause, and watch progress, ETA and the key pool."""

from __future__ import annotations

from uuid import UUID

import flet as ft

from ranobe.core.models import JobState, SegmentStatus, utcnow
from ranobe.i18n import t
from ranobe.ui.components.common import (
    card,
    empty_state,
    format_duration,
    muted,
    page_title,
    section_title,
    status_chip,
)
from ranobe.ui.context import UiContext
from ranobe.ui.layout.breakpoints import Layout
from ranobe.ui.state import Topic
from ranobe.ui.theme.tokens import Space


class TranslateView:
    topics = frozenset({Topic.PROGRESS, Topic.WORKS, Topic.ACCOUNTS})

    def __init__(self, ctx: UiContext):
        self.ctx = ctx

    def build(self) -> ft.Control:
        state, memory = self.ctx.state, self.ctx.memory
        work = state.repos.works.get(memory.selected_work) if memory.selected_work else None
        if work is None:
            return ft.Column(
                [
                    page_title(t("nav.translate")),
                    empty_state(
                        ft.Icons.TRANSLATE,
                        t("translate.no_work.title"),
                        t("translate.no_work.hint"),
                        ft.FilledButton(
                            t("nav.library"), on_click=lambda _: self.ctx.navigate("/library")
                        ),
                    ),
                ],
                expand=True,
            )
        chapters = state.repos.chapters.for_work(work.id)
        selected = memory.selected_chapters.setdefault(work.id, {c.id for c in chapters})
        running = state.translating
        start = ft.FilledButton(
            t("translate.pause") if running else t("translate.start"),
            icon=ft.Icons.PAUSE if running else ft.Icons.PLAY_ARROW,
            on_click=self._toggle,
            disabled=not running and not selected,
        )
        progress = self._progress_panel(work.id, [c.id for c in chapters])
        chapter_list = self._chapters(work.id, chapters, selected, disabled=running)
        if self.ctx.layout is Layout.EXPANDED:
            body: ft.Control = ft.Row(
                [
                    ft.Container(chapter_list, width=320),
                    ft.Column(
                        [progress, self._accounts_panel()],
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                        spacing=Space.L,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.START,
                spacing=Space.XL,
                expand=True,
            )
        else:
            body = ft.Column(
                [progress, self._accounts_panel(), chapter_list],
                scroll=ft.ScrollMode.AUTO,
                spacing=Space.L,
                expand=True,
            )
        return ft.Column(
            [
                page_title(work.title, start),
                muted(f"{work.source_lang} → {work.target_lang}"),
                body,
            ],
            spacing=Space.M,
            expand=True,
        )

    # --- panels ---

    def _chapters(self, work_id: UUID, chapters, selected: set[UUID], disabled: bool):
        def toggle(e: ft.Event, cid: UUID) -> None:
            (selected.add if e.control.value else selected.discard)(cid)
            self.ctx.state.notify(Topic.PROGRESS)

        def toggle_all(e: ft.Event) -> None:
            selected.clear()
            if e.control.value:
                selected.update(c.id for c in chapters)
            self.ctx.state.notify(Topic.PROGRESS)

        rows: list[ft.Control] = [
            ft.Checkbox(
                label=t("translate.all_chapters", n=len(chapters)),
                value=len(selected) == len(chapters),
                on_change=toggle_all,
                disabled=disabled,
            ),
            ft.Divider(height=1),
        ]
        rows += [
            ft.Checkbox(
                label=c.title,
                value=c.id in selected,
                on_change=lambda e, cid=c.id: toggle(e, cid),
                disabled=disabled,
            )
            for c in chapters
        ]
        return card(
            ft.Column(
                [
                    section_title(t("translate.chapters")),
                    ft.Column(rows, spacing=0, scroll=ft.ScrollMode.AUTO, height=360),
                ],
                spacing=Space.S,
            )
        )

    def _progress_panel(self, work_id: UUID, chapter_ids: list[UUID]) -> ft.Control:
        state = self.ctx.state
        counts = state.repos.segments.count_by_status(chapter_ids)
        total = sum(counts.values())
        done = total - counts[SegmentStatus.PENDING]
        p = state.progress if state.progress and state.progress.work_id == work_id else None
        if p and p.total:
            done, total = p.done, p.total
        lines: list[ft.Control] = [
            section_title(t("translate.progress")),
            ft.ProgressBar(value=done / total if total else 0, border_radius=4, bar_height=8),
            ft.Text(t("library.progress", done=done, total=total)),
            ft.Row(
                [status_chip(s, n, self.ctx.dark) for s, n in counts.items() if n],
                wrap=True,
                spacing=Space.S,
            ),
        ]
        if p:
            lines.append(ft.Text(self._state_text(p), weight=ft.FontWeight.W_500))
            if p.state is JobState.RUNNING:
                lines.append(muted(t("translate.eta", time=format_duration(p.eta_seconds()))))
            if p.account:
                lines.append(muted(t("translate.active_key", account=p.account)))
            if p.preview:
                lines.append(
                    ft.Text(p.preview, italic=True, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS)
                )
            for switch in p.switches:
                lines.append(muted(t("translate.switched", detail=switch), size=12))
        return card(ft.Column(lines, spacing=Space.S))

    def _state_text(self, p) -> str:
        if p.state is JobState.WAITING_QUOTA:
            if p.resume_at is None:  # no usable key at all, not a temporary limit
                return t("translate.state.no_keys")
            return t("translate.state.waiting_quota", time=f"{p.resume_at:%Y-%m-%d %H:%M} UTC")
        if p.state is JobState.FAILED:
            return t("translate.state.failed", error=p.error or "")
        return t(f"translate.state.{p.state.value}")

    def _accounts_panel(self) -> ft.Control:
        now = utcnow()
        accounts = self.ctx.state.accounts()
        if not accounts:
            return card(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.ERROR),
                        ft.Text(t("translate.no_accounts"), expand=True),
                        ft.TextButton(
                            t("nav.accounts"), on_click=lambda _: self.ctx.navigate("/accounts")
                        ),
                    ]
                )
            )
        rows = []
        for a in accounts:
            if not a.enabled:
                status = t("accounts.status.disabled")
            elif a.exhausted_until and a.exhausted_until > now:
                status = t("accounts.status.quota", time=f"{a.exhausted_until:%m-%d %H:%M} UTC")
            elif a.cooldown_until and a.cooldown_until > now:
                status = t("accounts.status.cooldown")
            else:
                status = t("accounts.status.ready")
            rows.append(ft.Row([ft.Text(a.label, expand=True), muted(status)]))
        return card(ft.Column([section_title(t("translate.key_pool")), *rows], spacing=Space.S))

    # --- actions ---

    def _toggle(self, _: ft.Event) -> None:
        state = self.ctx.state
        if state.translating:
            state.stop()
            return
        work_id = self.ctx.memory.selected_work
        chapters = state.repos.chapters.for_work(work_id)
        selected = self.ctx.memory.selected_chapters.get(work_id, set())
        chapter_ids = (
            None if len(selected) == len(chapters) else [c.id for c in chapters if c.id in selected]
        )
        self.ctx.run(state.translate, work_id, chapter_ids)
