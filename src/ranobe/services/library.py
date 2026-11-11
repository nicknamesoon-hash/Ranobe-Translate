"""Library operations that span several repositories."""

from __future__ import annotations

from pathlib import Path

from ranobe.core.models import Chapter, Segment, Work
from ranobe.services.importers import ImportedBook, importer_for
from ranobe.storage.repositories import Repositories


def import_book(
    repos: Repositories, book: ImportedBook, source_lang: str, target_lang: str
) -> Work:
    work = Work(
        title=book.title,
        author=book.author,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    with repos.db.transaction():
        repos.works.save(work)
        for ci, imported in enumerate(book.chapters):
            chapter = Chapter(work_id=work.id, index=ci, title=imported.title)
            repos.chapters.save(chapter)
            for si, block in enumerate(imported.blocks):
                repos.segments.save(
                    Segment(chapter_id=chapter.id, index=si, source=block.text, kind=block.kind)
                )
    return work


def import_file(repos: Repositories, path: Path, source_lang: str, target_lang: str) -> Work:
    book = importer_for(path).read(path, lang_hint=source_lang)
    return import_book(repos, book, source_lang, target_lang)
