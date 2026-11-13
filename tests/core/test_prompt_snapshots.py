"""Snapshot tests: the full prompt for every content level and honorifics mode.

A change in prompt wording shows up here as a diff to review. To accept intended changes:
    UPDATE_SNAPSHOTS=1 pytest tests/core/test_prompt_snapshots.py
"""

import os
from pathlib import Path
from uuid import UUID

import pytest

from ranobe.core.models import (
    CensorshipLevel,
    GlossaryEntry,
    HonorificsMode,
    Segment,
    TranslationJob,
    Work,
)
from ranobe.core.prompts.builder import PromptChunk, build_edit_prompt, build_translation_prompt

SNAPSHOTS = Path(__file__).parent / "snapshots"
CHAPTER = UUID(int=1)


def _check(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if os.environ.get("UPDATE_SNAPSHOTS") or not path.exists():
        existed = path.exists()
        path.write_text(text, encoding="utf-8", newline="\n")
        if not existed and not os.environ.get("UPDATE_SNAPSHOTS"):
            pytest.fail(f"snapshot {path.name} was missing and has been created; run again")
        return
    assert text == path.read_text(encoding="utf-8"), f"prompt changed: {path.name}"


def _render(system: str, user: str) -> str:
    return f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n"


def _setup(target: str, censorship: CensorshipLevel, honorifics: HonorificsMode):
    work = Work(title="Тест", source_lang="ja", target_lang=target)
    work.settings.censorship = censorship
    work.settings.honorifics = honorifics
    job = TranslationJob(work_id=work.id, chapter_ids=[CHAPTER], plot_summary="Summary.")
    seg = Segment(chapter_id=CHAPTER, index=0, source="剣聖は笑った。", translation="Draft.")
    glossary = [GlossaryEntry(source="剣聖", target="Sword Saint", locked=True)]
    return work, job, PromptChunk([seg]), glossary


CASES = [("uk", c, h) for c in CensorshipLevel for h in HonorificsMode] + [
    ("en", c, HonorificsMode.KEEP) for c in CensorshipLevel
]


@pytest.mark.parametrize(("target", "censorship", "honorifics"), CASES)
def test_translation_prompt_snapshot(target, censorship, honorifics):
    work, job, chunk, glossary = _setup(target, censorship, honorifics)
    prompt = _render(*build_translation_prompt(work, job, chunk, glossary))
    _check(f"translate_{target}_{censorship.value}_{honorifics.value}", prompt)


@pytest.mark.parametrize("censorship", list(CensorshipLevel))
def test_edit_prompt_snapshot(censorship):
    work, _, chunk, glossary = _setup("uk", censorship, HonorificsMode.KEEP)
    _check(f"edit_uk_{censorship.value}", _render(*build_edit_prompt(work, chunk, glossary)))
