"""Smoke test: every route renders in every layout and language, without a Flet client.

A fake page stands in for the Flutter side; the test walks the built control tree and
checks that no i18n key leaked into the interface untranslated.
"""

import dataclasses
import re

import flet as ft
import pytest

from ranobe import i18n
from ranobe.core.models import SegmentKind
from ranobe.services.importers.base import ImportedBlock, ImportedBook, ImportedChapter
from ranobe.services.secrets import MemorySecretStore
from ranobe.storage.settings import AppSettings
from ranobe.ui.app import VIEWS
from ranobe.ui.layout.breakpoints import Layout, layout_for
from ranobe.ui.layout.shell import ROUTES, Shell
from ranobe.ui.state import AppState

KEY_LIKE = re.compile(r"^[a-z_]+(\.[a-z_]+)+$")


class FakeWindow:
    min_width = min_height = 0


class FakePage:
    def __init__(self, width: float):
        self.width = width
        self.services: list = []
        self.controls: list = []
        self.dialogs: list = []
        self.theme_mode = ft.ThemeMode.LIGHT
        self.platform_brightness = ft.Brightness.LIGHT
        self.window = FakeWindow()
        self.updates = 0

    def update(self, *_):
        self.updates += 1

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        self.dialogs.pop()

    def run_task(self, fn, *args):
        self.ran = (fn, args)


def _texts(control, seen=None):
    """All Text values in a control tree."""
    seen = seen if seen is not None else set()
    if id(control) in seen:
        return
    seen.add(id(control))
    if isinstance(control, ft.Text) and isinstance(control.value, str):
        yield control.value
    if isinstance(control, list | tuple):
        for item in control:
            yield from _texts(item, seen)
        return
    if not isinstance(control, ft.BaseControl) and not dataclasses.is_dataclass(control):
        return
    for field in dataclasses.fields(control):
        if field.name.startswith("_") or field.name == "parent":
            continue
        value = getattr(control, field.name, None)
        if isinstance(value, ft.BaseControl | list | tuple) or (
            dataclasses.is_dataclass(value) and not isinstance(value, type)
        ):
            yield from _texts(value, seen)
        elif isinstance(value, str) and field.name in ("label", "hint_text", "tooltip", "title"):
            yield value


@pytest.fixture
def state(repos, tmp_path):
    s = AppState(repos, AppSettings(), tmp_path / "s.json", MemorySecretStore())
    blocks = [ImportedBlock(SegmentKind.PARAGRAPH, "文。")]
    s.import_book(ImportedBook("テスト", [ImportedChapter("第1章", blocks)]), "ja", "uk")
    s.add_account("gemini", "main", "key")
    yield s
    i18n.set_locale("uk")


@pytest.mark.parametrize("width", [360, 800, 1440])
@pytest.mark.parametrize("locale", ["uk", "en"])
def test_every_route_renders(state, width, locale, request):
    state.update_settings(ui_locale=locale)
    page = FakePage(width)
    shell = Shell(page, state, VIEWS)
    request.addfinalizer(shell.close)
    assert shell.ctx.layout is layout_for(width)
    for route in ROUTES:
        shell.navigate(route) if route != shell.route else shell.render()
        texts = list(_texts(page.controls))
        assert texts, route
        leaked = [t for t in texts if KEY_LIKE.match(t)]
        assert not leaked, (route, leaked)
    # the translate screen with a work selected
    shell.ctx.memory.selected_work = state.works()[0].work.id
    shell.navigate("/library")
    shell.navigate("/translate")
    assert "テスト" in list(_texts(page.controls))


def test_layout_switches_on_resize(state, request):
    page = FakePage(1440)
    shell = Shell(page, state, VIEWS)
    request.addfinalizer(shell.close)
    shell.render()
    assert isinstance(page.controls[0].content.controls[0], ft.NavigationRail)
    shell._on_resize(ft.PageResizeEvent(name="resize", control=page, width=360, height=700))
    assert shell.ctx.layout is Layout.COMPACT
    assert isinstance(page.controls[0].content.controls[-1], ft.NavigationBar)
