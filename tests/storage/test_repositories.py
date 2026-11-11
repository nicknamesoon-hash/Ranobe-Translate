import pytest

from ranobe.core.models import (
    CensorshipLevel,
    Chapter,
    Dispute,
    DisputeOption,
    GlossaryEntry,
    JobState,
    Note,
    NoteType,
    ProviderAccount,
    Segment,
    SegmentStatus,
    TranslationJob,
    Work,
)
from ranobe.storage.db import Database
from ranobe.storage.settings import AppSettings


def _work_with_segments(repos, n=3):
    work = Work(title="Test", source_lang="ja", target_lang="uk")
    work.settings.censorship = CensorshipLevel.SOFTENED
    repos.works.save(work)
    ch = Chapter(work_id=work.id, index=0, title="第1章")
    repos.chapters.save(ch)
    segs = [Segment(chapter_id=ch.id, index=i, source=f"文{i}。") for i in range(n)]
    repos.segments.save_many(segs)
    return work, ch, segs


def test_migration_sets_version(tmp_path):
    db = Database(tmp_path / "a.db")
    assert db.version == 1
    db.close()
    db = Database(tmp_path / "a.db")  # second open does not re-run migrations
    assert db.version == 1


def test_work_round_trip(repos):
    work, _, _ = _work_with_segments(repos)
    loaded = repos.works.get(work.id)
    assert loaded.title == "Test"
    assert loaded.settings.censorship is CensorshipLevel.SOFTENED
    assert repos.works.find(str(work.id)[:8]).id == work.id


def test_pending_segments_in_order(repos):
    _, ch, segs = _work_with_segments(repos, 5)
    segs[1].status = SegmentStatus.TRANSLATED
    repos.segments.save(segs[1])
    pending = repos.segments.pending([ch.id])
    assert [s.index for s in pending] == [0, 2, 3, 4]
    counts = repos.segments.count_by_status([ch.id])
    assert counts[SegmentStatus.PENDING] == 4
    assert counts[SegmentStatus.TRANSLATED] == 1


def test_transaction_rollback(repos):
    _, ch, segs = _work_with_segments(repos)
    segs[0].status = SegmentStatus.TRANSLATED
    with pytest.raises(RuntimeError), repos.db.transaction():
        repos.segments.save(segs[0])
        raise RuntimeError("boom")
    assert repos.segments.for_chapter(ch.id)[0].status is SegmentStatus.PENDING


def test_glossary_locked_entry_wins(repos):
    work, _, _ = _work_with_segments(repos)
    repos.glossary.upsert(
        GlossaryEntry(
            source="剣聖", target="Майстер Меча", work_id=work.id, locked=True, origin="dispute"
        )
    )
    repos.glossary.upsert(
        GlossaryEntry(source="剣聖", target="Кенсей", work_id=work.id, origin="llm_suggestion")
    )
    entries = repos.glossary.for_work(work.id)
    assert [(e.source, e.target) for e in entries] == [("剣聖", "Майстер Меча")]


def test_work_glossary_shadows_global(repos):
    work, _, _ = _work_with_segments(repos)
    repos.glossary.upsert(GlossaryEntry(source="魔力", target="магічна сила"))
    repos.glossary.upsert(GlossaryEntry(source="魔力", target="мана", work_id=work.id))
    repos.glossary.upsert(GlossaryEntry(source="魔法", target="магія"))
    got = {e.source: e.target for e in repos.glossary.for_work(work.id)}
    assert got == {"魔力": "мана", "魔法": "магія"}


def test_notes_disputes_jobs_accounts(repos):
    work, ch, segs = _work_with_segments(repos)
    repos.notes.add(
        Note(
            segment_id=segs[0].id,
            type=NoteType.CULTURAL,
            anchor="Обон",
            source_fragment="お盆",
            text="Свято.",
        )
    )
    repos.disputes.add(
        Dispute(
            segment_id=segs[0].id,
            source_fragment="剣聖",
            issue="Титул",
            options=[DisputeOption("A", "a"), DisputeOption("B", "b")],
            recommended=1,
        )
    )
    assert repos.notes.for_segment(segs[0].id)[0].anchor == "Обон"
    assert repos.disputes.for_segment(segs[0].id)[0].options[1].text == "B"
    assert repos.disputes.unresolved_count(work.id) == 1

    job = TranslationJob(work_id=work.id, chapter_ids=[ch.id], plot_summary="Summary")
    job.stats.requests = 3
    repos.jobs.save(job)
    job.state = JobState.DONE
    repos.jobs.save(job)
    loaded = repos.jobs.latest_for_work(work.id)
    assert loaded.state is JobState.DONE and loaded.stats.requests == 3

    acc = ProviderAccount(provider_id="gemini", label="main", model="gemini-2.5-flash")
    repos.accounts.save(acc)
    assert repos.accounts.list()[0].secret_ref == f"account:{acc.id}"


def test_settings_round_trip_ignores_unknown(tmp_path):
    p = tmp_path / "settings.json"
    AppSettings(ui_locale="en").save(p)
    p.write_text(p.read_text().replace("{", '{"unknown": 1,', 1))
    assert AppSettings.load(p).ui_locale == "en"
    assert AppSettings.load(tmp_path / "missing.json").ui_locale == "uk"
