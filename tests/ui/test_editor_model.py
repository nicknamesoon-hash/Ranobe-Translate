import pytest

from ranobe.core.models import SegmentKind
from ranobe.services.importers.base import ImportedBlock, ImportedBook, ImportedChapter
from ranobe.services.library import import_book
from ranobe.ui.editor_model import EditorModel


def _work(repos, chapters=3):
    book = ImportedBook(
        "T",
        [
            ImportedChapter(
                f"c{i}", [ImportedBlock(SegmentKind.PARAGRAPH, f"p{i}-{j}") for j in range(2)]
            )
            for i in range(chapters)
        ],
    )
    return import_book(repos, book, "ja", "uk")


def test_chapter_navigation(repos):
    model = EditorModel(repos, _work(repos).id)
    assert model.chapter.title == "c0" and not model.has_previous and model.has_next
    assert [s.source for s in model.segments()] == ["p0-0", "p0-1"]
    model.open_chapter(99)
    assert model.chapter.title == "c2" and not model.has_next
    model.open_chapter(-5)
    assert model.chapter_index == 0


def test_unknown_work(repos):
    from uuid import uuid4

    with pytest.raises(KeyError):
        EditorModel(repos, uuid4())
