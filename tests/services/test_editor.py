from uuid import uuid4

import pytest

from ranobe.core.models import (
    Chapter,
    Dispute,
    DisputeOption,
    NoteType,
    Segment,
    SegmentStatus,
    TranslationJob,
    Work,
)
from ranobe.core.notes import first_occurrences, note_key
from ranobe.core.prompts.builder import PromptChunk, build_translation_prompt
from ranobe.services.editor import Editor


@pytest.fixture
def book(repos):
    work = Work(title="Test", source_lang="ja", target_lang="uk")
    repos.works.save(work)
    ch = Chapter(work_id=work.id, index=0, title="第1章")
    repos.chapters.save(ch)
    first = Segment(
        chapter_id=ch.id,
        index=0,
        source="剣聖が来た。剣聖は強い。",
        translation="Святий Меч прийшов. Святий Меч сильний.",
        status=SegmentStatus.TRANSLATED,
    )
    second = Segment(
        chapter_id=ch.id,
        index=1,
        source="剣聖だ。",
        translation="Це Святий Меч.",
        status=SegmentStatus.TRANSLATED,
    )
    repos.segments.save_many([first, second])
    dispute = Dispute(
        segment_id=first.id,
        source_fragment="剣聖",
        issue="title or literal?",
        options=[DisputeOption("Святий Меч", "literal"), DisputeOption("Мечник-святий", "title")],
        recommended=0,
        add_to_glossary=True,
    )
    repos.disputes.add(dispute)
    return work, ch, first, second, dispute


def test_choose_option_replaces_only_inside_its_segment(repos, book):
    work, _, first, second, dispute = book
    result = Editor(repos).resolve_dispute(dispute.id, chosen=1)

    assert result.applied
    seg = repos.segments.get(first.id)
    assert seg.translation == "Мечник-святий прийшов. Мечник-святий сильний."
    assert seg.status is SegmentStatus.EDITED
    assert repos.segments.get(second.id).translation == "Це Святий Меч."
    stored = repos.disputes.get(dispute.id)
    assert stored.chosen == 1 and stored.resolved_at is not None
    assert repos.disputes.unresolved_count(work.id) == 0


def test_choice_becomes_locked_glossary_entry_used_by_next_chunks(repos, book):
    work, ch, _, second, dispute = book
    Editor(repos).resolve_dispute(dispute.id, chosen=1)

    [entry] = repos.glossary.for_work(work.id)
    assert (entry.source, entry.target, entry.origin, entry.locked) == (
        "剣聖", "Мечник-святий", "dispute", True,
    )  # fmt: skip
    job = TranslationJob(work_id=work.id, chapter_ids=[ch.id])
    system, _ = build_translation_prompt(
        work, job, PromptChunk([second]), repos.glossary.for_work(work.id)
    )
    assert "剣聖 = Мечник-святий [fixed]" in system


def test_custom_text_and_re_resolution(repos, book):
    _, _, first, _, dispute = book
    editor = Editor(repos)
    editor.resolve_dispute(dispute.id, custom="  Меч-Святець ")
    assert repos.segments.get(first.id).translation.startswith("Меч-Святець прийшов")

    # Changing the mind later replaces the custom text, not the original recommendation.
    editor.resolve_dispute(dispute.id, chosen=0)
    assert repos.segments.get(first.id).translation == "Святий Меч прийшов. Святий Меч сильний."
    assert repos.disputes.get(dispute.id).custom_text is None


def test_hand_edited_fragment_is_not_applied_but_still_resolved(repos, book):
    _, _, first, _, dispute = book
    first.translation = "Хтось прийшов."
    repos.segments.save(first)

    result = Editor(repos).resolve_dispute(dispute.id, chosen=1)
    assert not result.applied
    assert repos.segments.get(first.id).translation == "Хтось прийшов."
    assert repos.disputes.get(dispute.id).resolved_at is not None


def test_dispute_without_glossary_flag_leaves_glossary_alone(repos, book):
    work, _, first, _, _ = book
    other = Dispute(
        segment_id=first.id,
        source_fragment="強い",
        issue="tone",
        options=[DisputeOption("сильний", "neutral"), DisputeOption("могутній", "epic")],
        recommended=0,
    )
    repos.disputes.add(other)
    result = Editor(repos).resolve_dispute(other.id, chosen=1)
    assert result.glossary_entry is None
    assert repos.glossary.for_work(work.id) == []
    assert repos.segments.get(first.id).translation.endswith("Святий Меч могутній.")


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"chosen": 0, "custom": "x"}, {"chosen": 5}, {"custom": "   "}],
)
def test_invalid_arguments(repos, book, kwargs):
    *_, dispute = book
    with pytest.raises(ValueError):
        Editor(repos).resolve_dispute(dispute.id, **kwargs)


def test_disputes_for_work_in_reading_order(repos, book):
    work, _, _, second, dispute = book
    later = Dispute(
        segment_id=second.id,
        source_fragment="だ",
        issue="x",
        options=[DisputeOption("a", ""), DisputeOption("b", "")],
        recommended=0,
    )
    repos.disputes.add(later)
    assert [d.id for d in repos.disputes.for_work(work.id)] == [dispute.id, later.id]
    Editor(repos).resolve_dispute(dispute.id, chosen=0)
    assert [d.id for d in repos.disputes.for_work(work.id, unresolved_only=True)] == [later.id]


# --- notes -------------------------------------------------------------------------------


def test_note_crud(repos, book):
    work, _, first, second, _ = book
    editor = Editor(repos)
    note = editor.add_note(second.id, " Святий Меч ", "Титул найкращого мечника.")
    assert (note.origin, note.type, note.anchor) == (
        "user",
        NoteType.TRANSLATOR_CHOICE,
        "Святий Меч",
    )

    editor.update_note(note.id, text="Новий текст.", type=NoteType.TERM, display="tooltip")
    stored = repos.notes.get(note.id)
    assert (stored.text, stored.type, stored.display) == ("Новий текст.", NoteType.TERM, "tooltip")

    early = editor.add_note(first.id, "прийшов", "Ранній сегмент.")
    assert [n.id for n in repos.notes.for_work(work.id)] == [early.id, note.id]

    editor.delete_note(note.id)
    assert repos.notes.get(note.id) is None
    assert repos.notes.for_segment(second.id) == []


def test_note_validation(repos, book):
    *_, second, _ = book
    editor = Editor(repos)
    with pytest.raises(ValueError):
        editor.add_note(second.id, "  ", "text")
    note = editor.add_note(second.id, "Меч", "text")
    with pytest.raises(ValueError):
        editor.update_note(note.id, display="popup")
    with pytest.raises(KeyError):
        editor.delete_note(uuid4())


def test_first_occurrences_rule():
    seen = {note_key("お盆", "")}
    items = [("お盆", "Обон"), ("剣聖", "Святий Меч"), ("", "Святий меч"), ("", "")]
    kept = first_occurrences(items, lambda i: note_key(*i), seen)
    assert kept == [("剣聖", "Святий Меч"), ("", "Святий меч")]
    assert note_key("", " Святий МЕЧ ") in seen
