"""Editor view-model: which chapter is open and which segments it shows. No Flet."""

from __future__ import annotations

from uuid import UUID

from ranobe.core.models import Chapter, Segment, Work
from ranobe.storage.repositories import Repositories


class EditorModel:
    def __init__(self, repos: Repositories, work_id: UUID):
        self.repos = repos
        work = repos.works.get(work_id)
        if work is None:
            raise KeyError(work_id)
        self.work: Work = work
        self.chapters: list[Chapter] = repos.chapters.for_work(work_id)
        self.chapter_index = 0

    @property
    def chapter(self) -> Chapter | None:
        return self.chapters[self.chapter_index] if self.chapters else None

    def open_chapter(self, index: int) -> None:
        if self.chapters:
            self.chapter_index = max(0, min(index, len(self.chapters) - 1))

    @property
    def has_previous(self) -> bool:
        return self.chapter_index > 0

    @property
    def has_next(self) -> bool:
        return self.chapter_index < len(self.chapters) - 1

    def segments(self) -> list[Segment]:
        chapter = self.chapter
        return self.repos.segments.for_chapter(chapter.id) if chapter else []
