import ast
import string
from pathlib import Path

import pytest

from ranobe import i18n
from ranobe.i18n import LOCALES, catalog, on_locale_change, set_locale, t
from ranobe.i18n.plural import CATEGORIES, plural_category

UI_DIR = Path(i18n.__file__).resolve().parents[1] / "ui"


@pytest.fixture(autouse=True)
def reset_locale():
    set_locale("uk")
    yield
    set_locale("uk")


def _placeholders(value: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(value) if name}


def test_same_keys_in_every_locale():
    keys = {loc: set(catalog(loc)) for loc in LOCALES}
    assert keys["uk"] == keys["en"], keys["uk"] ^ keys["en"]


def test_placeholders_and_plural_forms_match():
    for key, uk_value in catalog("uk").items():
        en_value = catalog("en")[key]
        assert type(uk_value) is type(en_value), key
        if isinstance(uk_value, dict):
            for loc, value in (("uk", uk_value), ("en", en_value)):
                assert set(value) == set(CATEGORIES[loc]), (key, loc)
            forms = [*uk_value.values(), *en_value.values()]
            assert all(_placeholders(f) == _placeholders(forms[0]) for f in forms), key
        else:
            assert _placeholders(uk_value) == _placeholders(en_value), key


@pytest.mark.parametrize(
    ("n", "uk", "en"),
    [(1, "one", "one"), (2, "few", "other"), (5, "many", "other"), (11, "many", "other"),
     (21, "one", "other"), (22, "few", "other"), (112, "many", "other"), (0, "many", "other")],
)  # fmt: skip
def test_plural_rules(n, uk, en):
    assert plural_category("uk", n) == uk
    assert plural_category("en", n) == en


def test_t_plural_and_switching_with_listeners():
    seen = []
    unsubscribe = on_locale_change(seen.append)
    assert t("library.works", n=21) == "21 твір"
    assert t("library.works", n=3) == "3 твори"
    set_locale("en")
    assert t("library.works", n=3) == "3 works" and t("nav.library") == "Library"
    unsubscribe()
    set_locale("uk")
    assert seen == ["en"]


def test_missing_key_falls_back_to_key():
    assert t("no.such.key") == "no.such.key"
    with pytest.raises(ValueError):
        set_locale("de")


# --- no hard-coded interface text ---------------------------------------------------------

# Strings that are not interface text: identifiers, routes, icon names, keys, formats.
_ALLOWED = string.ascii_letters + string.digits + "._-/:#%{}()[]=,+*<>|@ "


def _looks_like_text(value: str) -> bool:
    letters = [c for c in value if c.isalpha()]
    if not letters:
        return False
    if any(not c.isascii() for c in letters):
        return True  # Cyrillic, CJK…: always interface text
    words = [w for w in value.split() if any(c.isalpha() for c in w)]
    return len(words) >= 2 and value[0].isupper()  # "Add account", not "on_click" or "a.b"


def _hardcoded(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    lines = path.read_text(encoding="utf-8").splitlines()
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and _looks_like_text(node.value)
            and "i18n: ignore" not in lines[node.lineno - 1]
        ):
            found.append((node.lineno, node.value))
    return found


def test_scanner_detects_text():
    assert _looks_like_text("Додати ключ") and _looks_like_text("Add account")
    assert not _looks_like_text("nav.library") and not _looks_like_text("on_click")


def test_no_hardcoded_strings_in_ui():
    problems = {
        str(p.relative_to(UI_DIR)): hits
        for p in sorted(UI_DIR.rglob("*.py"))
        if (hits := _hardcoded(p))
    }
    assert not problems, f"use t() for interface text: {problems}"
