"""The app frame: navigation (bottom bar on phones, rail on wider windows) and the current view.

Views are rebuilt from state: on navigation, on a state topic they care about, on a
language or theme switch, and when the window crosses a breakpoint. Nothing needs a restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import flet as ft

from ranobe.i18n import on_locale_change, t
from ranobe.ui.context import UiContext
from ranobe.ui.layout.breakpoints import Layout, layout_for
from ranobe.ui.state import AppState, Topic
from ranobe.ui.theme.theme import apply_theme


class View(Protocol):
    topics: frozenset[str]  # AppState topics that require a rebuild

    def build(self) -> ft.Control: ...


@dataclass(frozen=True)
class Destination:
    route: str
    label_key: str
    icon: ft.IconData
    selected_icon: ft.IconData


DESTINATIONS = (
    Destination("/library", "nav.library", ft.Icons.LIBRARY_BOOKS_OUTLINED, ft.Icons.LIBRARY_BOOKS),
    Destination("/translate", "nav.translate", ft.Icons.TRANSLATE_OUTLINED, ft.Icons.TRANSLATE),
    Destination("/accounts", "nav.accounts", ft.Icons.KEY_OUTLINED, ft.Icons.KEY),
    Destination("/settings", "nav.settings", ft.Icons.SETTINGS_OUTLINED, ft.Icons.SETTINGS),
)
ROUTES = tuple(d.route for d in DESTINATIONS)


class Shell:
    def __init__(self, page: ft.Page, state: AppState, views: dict[str, type]):
        self.page = page
        self.state = state
        self.ctx = UiContext(page, state, self.navigate)
        self.views: dict[str, View] = {route: cls(self.ctx) for route, cls in views.items()}
        self.route = ROUTES[0]
        self.ctx.layout = layout_for(page.width)
        self.switcher = ft.AnimatedSwitcher(
            content=ft.Container(),
            transition=ft.AnimatedSwitcherTransition.FADE,
            switch_in_curve=ft.AnimationCurve.EASE_OUT_CUBIC,
            switch_out_curve=ft.AnimationCurve.EASE_OUT_CUBIC,
            expand=True,
        )
        page.on_resize = self._on_resize
        self._unsubscribe = [
            state.subscribe(self._on_topic),
            on_locale_change(lambda _: self.render()),
        ]

    def close(self) -> None:
        """Stop listening to state and language changes (the page is gone)."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()

    # --- navigation and events ---

    def navigate(self, route: str) -> None:
        if route in self.views and route != self.route:
            self.route = route
            self.render()

    def _on_resize(self, e: ft.PageResizeEvent) -> None:
        layout = layout_for(e.width)
        if layout != self.ctx.layout:
            self.ctx.layout = layout
            self.render()

    def _on_topic(self, topic: str) -> None:
        if topic == Topic.SETTINGS:
            settings = self.state.settings
            apply_theme(self.page, settings.theme, settings.reduce_motion)
            self.render()
        elif topic in self.views[self.route].topics:
            self.refresh()

    def _on_nav_change(self, e: ft.Event) -> None:
        self.navigate(ROUTES[int(e.control.selected_index)])

    # --- rendering ---

    def refresh(self) -> None:
        """Rebuild only the current view (state changed)."""
        self.switcher.content = self._view_container()
        self.page.update()

    def render(self) -> None:
        """Rebuild navigation and the current view (route, layout, language or theme)."""
        self.switcher.duration = self.ctx.durations.slow
        self.switcher.reverse_duration = self.ctx.durations.fast
        self.switcher.content = self._view_container()
        index = ROUTES.index(self.route)
        self.page.title = t("app.title")
        if self.ctx.layout is Layout.COMPACT:
            nav = ft.NavigationBar(
                destinations=[
                    ft.NavigationBarDestination(
                        icon=d.icon, selected_icon=d.selected_icon, label=t(d.label_key)
                    )
                    for d in DESTINATIONS
                ],
                selected_index=index,
                on_change=self._on_nav_change,
            )
            root = ft.Column([self.switcher, nav], spacing=0, expand=True)
        else:
            rail = ft.NavigationRail(
                destinations=[
                    ft.NavigationRailDestination(
                        icon=d.icon, selected_icon=d.selected_icon, label=t(d.label_key)
                    )
                    for d in DESTINATIONS
                ],
                selected_index=index,
                label_type=ft.NavigationRailLabelType.ALL,
                extended=False,
                on_change=self._on_nav_change,
            )
            root = ft.Row([rail, ft.VerticalDivider(width=1), self.switcher], expand=True)
        self.page.controls = [ft.SafeArea(root, expand=True)]
        self.page.update()

    def _view_container(self) -> ft.Control:
        compact = self.ctx.layout is Layout.COMPACT
        return ft.Container(
            self.views[self.route].build(),
            key=self.route,  # the switcher animates only when the key (route) changes
            padding=ft.Padding.all(16 if compact else 24),
            expand=True,
        )
