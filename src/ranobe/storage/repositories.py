"""Repositories: the only place that knows the SQL schema."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from ranobe.core.models import (
    CensorshipLevel,
    Chapter,
    Dispute,
    DisputeOption,
    GlossaryEntry,
    GlossaryKind,
    HonorificsMode,
    JobState,
    JobStats,
    Note,
    NoteType,
    ProviderAccount,
    Segment,
    SegmentKind,
    SegmentStatus,
    TranslationJob,
    TranslationStatus,
    Work,
    WorkSettings,
    utcnow,
)
from ranobe.storage.db import Database


def _ts(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


def _settings_to_json(s: WorkSettings) -> str:
    return json.dumps(asdict(s))


def _settings_from_json(raw: str) -> WorkSettings:
    data = json.loads(raw)
    return WorkSettings(
        censorship=CensorshipLevel(data.get("censorship", "original")),
        honorifics=HonorificsMode(data.get("honorifics", "keep")),
        quality_preset=data.get("quality_preset", "balanced"),
        with_notes=data.get("with_notes", True),
        with_disputes=data.get("with_disputes", True),
        with_summary=data.get("with_summary", True),
        account_chain=list(data.get("account_chain", [])),
    )


class WorkRepo:
    def __init__(self, db: Database):
        self.db = db

    def save(self, work: Work) -> None:
        work.updated_at = utcnow()
        work.rev += 1
        self.db.conn.execute(
            """INSERT INTO works (id, title, original_title, author, source_lang, target_lang,
                   genres, tags, synopsis, translation_status, settings, updated_at, rev)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                   original_title=excluded.original_title, author=excluded.author,
                   source_lang=excluded.source_lang, target_lang=excluded.target_lang,
                   genres=excluded.genres, tags=excluded.tags, synopsis=excluded.synopsis,
                   translation_status=excluded.translation_status, settings=excluded.settings,
                   updated_at=excluded.updated_at, rev=excluded.rev""",
            (
                str(work.id), work.title, work.original_title, work.author, work.source_lang,
                work.target_lang, json.dumps(work.genres, ensure_ascii=False),
                json.dumps(work.tags, ensure_ascii=False), work.synopsis,
                work.translation_status.value, _settings_to_json(work.settings),
                _ts(work.updated_at), work.rev,
            ),
        )  # fmt: skip

    def get(self, work_id: UUID) -> Work | None:
        row = self.db.conn.execute(
            "SELECT * FROM works WHERE id = ? AND deleted = 0", (str(work_id),)
        ).fetchone()
        return self._from_row(row) if row else None

    def list(self) -> list[Work]:
        rows = self.db.conn.execute(
            "SELECT * FROM works WHERE deleted = 0 ORDER BY updated_at DESC"
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def find(self, prefix: str) -> Work | None:
        """Find by id prefix (for the CLI)."""
        rows = self.db.conn.execute(
            "SELECT * FROM works WHERE id LIKE ? AND deleted = 0", (prefix + "%",)
        ).fetchall()
        return self._from_row(rows[0]) if len(rows) == 1 else None

    @staticmethod
    def _from_row(r: sqlite3.Row) -> Work:
        return Work(
            id=UUID(r["id"]), title=r["title"], original_title=r["original_title"],
            author=r["author"], source_lang=r["source_lang"], target_lang=r["target_lang"],
            genres=json.loads(r["genres"]), tags=json.loads(r["tags"]), synopsis=r["synopsis"],
            translation_status=TranslationStatus(r["translation_status"]),
            settings=_settings_from_json(r["settings"]), updated_at=_dt(r["updated_at"]),
            rev=r["rev"],
        )  # fmt: skip


class ChapterRepo:
    def __init__(self, db: Database):
        self.db = db

    def save(self, ch: Chapter) -> None:
        ch.rev += 1
        self.db.conn.execute(
            """INSERT INTO chapters (id, work_id, idx, title, updated_at, rev)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET idx=excluded.idx, title=excluded.title,
                   updated_at=excluded.updated_at, rev=excluded.rev""",
            (str(ch.id), str(ch.work_id), ch.index, ch.title, _ts(utcnow()), ch.rev),
        )

    def for_work(self, work_id: UUID) -> list[Chapter]:
        rows = self.db.conn.execute(
            "SELECT * FROM chapters WHERE work_id = ? AND deleted = 0 ORDER BY idx",
            (str(work_id),),
        ).fetchall()
        return [
            Chapter(id=UUID(r["id"]), work_id=UUID(r["work_id"]), index=r["idx"],
                    title=r["title"], rev=r["rev"])
            for r in rows
        ]  # fmt: skip


class SegmentRepo:
    def __init__(self, db: Database):
        self.db = db

    def save(self, s: Segment) -> None:
        s.rev += 1
        self.db.conn.execute(
            """INSERT INTO segments (id, chapter_id, idx, kind, source, translation,
                   machine_translation, status, censored, translated_by, review_reason,
                   updated_at, rev)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET idx=excluded.idx, kind=excluded.kind,
                   source=excluded.source, translation=excluded.translation,
                   machine_translation=excluded.machine_translation, status=excluded.status,
                   censored=excluded.censored, translated_by=excluded.translated_by,
                   review_reason=excluded.review_reason, updated_at=excluded.updated_at,
                   rev=excluded.rev""",
            (
                str(s.id), str(s.chapter_id), s.index, s.kind.value, s.source, s.translation,
                s.machine_translation, s.status.value, int(s.censored), s.translated_by,
                s.review_reason, _ts(utcnow()), s.rev,
            ),
        )  # fmt: skip

    def save_many(self, segments: list[Segment]) -> None:
        with self.db.transaction():
            for s in segments:
                self.save(s)

    def for_chapter(self, chapter_id: UUID) -> list[Segment]:
        rows = self.db.conn.execute(
            "SELECT * FROM segments WHERE chapter_id = ? AND deleted = 0 ORDER BY idx",
            (str(chapter_id),),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get(self, segment_id: UUID) -> Segment | None:
        row = self.db.conn.execute(
            "SELECT * FROM segments WHERE id = ? AND deleted = 0", (str(segment_id),)
        ).fetchone()
        return self._from_row(row) if row else None

    def previous(self, segment: Segment) -> Segment | None:
        """The segment just before this one in the same chapter."""
        row = self.db.conn.execute(
            """SELECT * FROM segments WHERE chapter_id = ? AND idx < ? AND deleted = 0
               ORDER BY idx DESC LIMIT 1""",
            (str(segment.chapter_id), segment.index),
        ).fetchone()
        return self._from_row(row) if row else None

    def work_id_of(self, segment_id: UUID) -> UUID | None:
        row = self.db.conn.execute(
            """SELECT c.work_id FROM segments s JOIN chapters c ON c.id = s.chapter_id
               WHERE s.id = ?""",
            (str(segment_id),),
        ).fetchone()
        return UUID(row[0]) if row else None

    def pending(self, chapter_ids: list[UUID], limit: int = 200) -> list[Segment]:
        """Next untranslated segments in reading order across the given chapters."""
        result: list[Segment] = []
        for cid in chapter_ids:
            rows = self.db.conn.execute(
                """SELECT * FROM segments WHERE chapter_id = ? AND status = 'pending'
                   AND deleted = 0 ORDER BY idx LIMIT ?""",
                (str(cid), limit - len(result)),
            ).fetchall()
            result.extend(self._from_row(r) for r in rows)
            if len(result) >= limit:
                break
        return result

    def count_by_status(self, chapter_ids: list[UUID]) -> dict[SegmentStatus, int]:
        counts = dict.fromkeys(SegmentStatus, 0)
        for cid in chapter_ids:
            for r in self.db.conn.execute(
                """SELECT status, COUNT(*) AS n FROM segments
                   WHERE chapter_id = ? AND deleted = 0 GROUP BY status""",
                (str(cid),),
            ):
                counts[SegmentStatus(r["status"])] += r["n"]
        return counts

    @staticmethod
    def _from_row(r: sqlite3.Row) -> Segment:
        return Segment(
            id=UUID(r["id"]), chapter_id=UUID(r["chapter_id"]), index=r["idx"],
            kind=SegmentKind(r["kind"]), source=r["source"], translation=r["translation"],
            machine_translation=r["machine_translation"], status=SegmentStatus(r["status"]),
            censored=bool(r["censored"]), translated_by=r["translated_by"],
            review_reason=r["review_reason"], rev=r["rev"],
        )  # fmt: skip


class NoteRepo:
    def __init__(self, db: Database):
        self.db = db

    def add(self, n: Note) -> None:
        self.db.conn.execute(
            """INSERT INTO notes (id, segment_id, type, anchor, source_fragment, text,
                   first_occurrence, display, origin, updated_at, rev)
               VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
            (str(n.id), str(n.segment_id), n.type.value, n.anchor, n.source_fragment, n.text,
             int(n.first_occurrence), n.display, n.origin, _ts(utcnow())),
        )  # fmt: skip

    def update(self, n: Note) -> None:
        self.db.conn.execute(
            """UPDATE notes SET type = ?, anchor = ?, source_fragment = ?, text = ?,
                   display = ?, updated_at = ?, rev = rev + 1 WHERE id = ?""",
            (n.type.value, n.anchor, n.source_fragment, n.text, n.display, _ts(utcnow()),
             str(n.id)),
        )  # fmt: skip

    def delete(self, note_id: UUID) -> None:
        """Soft delete, so the deletion can be synced later."""
        self.db.conn.execute(
            "UPDATE notes SET deleted = 1, updated_at = ?, rev = rev + 1 WHERE id = ?",
            (_ts(utcnow()), str(note_id)),
        )

    def delete_model_notes(self, segment_id: UUID) -> None:
        self.db.conn.execute(
            """UPDATE notes SET deleted = 1, updated_at = ?, rev = rev + 1
               WHERE segment_id = ? AND origin = 'llm' AND deleted = 0""",
            (_ts(utcnow()), str(segment_id)),
        )

    def get(self, note_id: UUID) -> Note | None:
        row = self.db.conn.execute(
            "SELECT * FROM notes WHERE id = ? AND deleted = 0", (str(note_id),)
        ).fetchone()
        return self._from_row(row) if row else None

    def for_segment(self, segment_id: UUID) -> list[Note]:
        rows = self.db.conn.execute(
            "SELECT * FROM notes WHERE segment_id = ? AND deleted = 0", (str(segment_id),)
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def for_work(self, work_id: UUID) -> list[Note]:
        """Notes of a work in reading order."""
        rows = self.db.conn.execute(
            """SELECT n.* FROM notes n JOIN segments s ON s.id = n.segment_id
               JOIN chapters c ON c.id = s.chapter_id
               WHERE c.work_id = ? AND n.deleted = 0 ORDER BY c.idx, s.idx""",
            (str(work_id),),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    @staticmethod
    def _from_row(r: sqlite3.Row) -> Note:
        return Note(
            id=UUID(r["id"]), segment_id=UUID(r["segment_id"]), type=NoteType(r["type"]),
            anchor=r["anchor"], source_fragment=r["source_fragment"], text=r["text"],
            first_occurrence=bool(r["first_occurrence"]), display=r["display"],
            origin=r["origin"],
        )  # fmt: skip


class DisputeRepo:
    def __init__(self, db: Database):
        self.db = db

    def add(self, d: Dispute) -> None:
        self.db.conn.execute(
            """INSERT INTO disputes (id, segment_id, source_fragment, issue, options,
                   recommended, add_to_glossary, chosen, custom_text, resolved_at,
                   updated_at, rev)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
            (str(d.id), str(d.segment_id), d.source_fragment, d.issue,
             json.dumps([asdict(o) for o in d.options], ensure_ascii=False), d.recommended,
             int(d.add_to_glossary), d.chosen, d.custom_text, _ts(d.resolved_at),
             _ts(utcnow())),
        )  # fmt: skip

    def get(self, dispute_id: UUID) -> Dispute | None:
        row = self.db.conn.execute(
            "SELECT * FROM disputes WHERE id = ? AND deleted = 0", (str(dispute_id),)
        ).fetchone()
        return self._from_row(row) if row else None

    def save_resolution(self, d: Dispute) -> None:
        self.db.conn.execute(
            """UPDATE disputes SET chosen = ?, custom_text = ?, resolved_at = ?, updated_at = ?,
                   rev = rev + 1 WHERE id = ?""",
            (d.chosen, d.custom_text, _ts(d.resolved_at), _ts(utcnow()), str(d.id)),
        )

    def delete_unresolved(self, segment_id: UUID) -> None:
        self.db.conn.execute(
            """UPDATE disputes SET deleted = 1, updated_at = ?, rev = rev + 1
               WHERE segment_id = ? AND resolved_at IS NULL AND deleted = 0""",
            (_ts(utcnow()), str(segment_id)),
        )

    def for_segment(self, segment_id: UUID) -> list[Dispute]:
        rows = self.db.conn.execute(
            "SELECT * FROM disputes WHERE segment_id = ? AND deleted = 0", (str(segment_id),)
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def for_work(self, work_id: UUID, unresolved_only: bool = False) -> list[Dispute]:
        """Disputes of a work in reading order (chapter, then segment)."""
        rows = self.db.conn.execute(
            f"""SELECT d.* FROM disputes d JOIN segments s ON s.id = d.segment_id
                JOIN chapters c ON c.id = s.chapter_id
                WHERE c.work_id = ? AND d.deleted = 0
                {"AND d.resolved_at IS NULL" if unresolved_only else ""}
                ORDER BY c.idx, s.idx""",
            (str(work_id),),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    @staticmethod
    def _from_row(r: sqlite3.Row) -> Dispute:
        return Dispute(
            id=UUID(r["id"]), segment_id=UUID(r["segment_id"]),
            source_fragment=r["source_fragment"], issue=r["issue"],
            options=[DisputeOption(**o) for o in json.loads(r["options"])],
            recommended=r["recommended"], add_to_glossary=bool(r["add_to_glossary"]),
            chosen=r["chosen"], custom_text=r["custom_text"],
            resolved_at=_dt(r["resolved_at"]),
        )  # fmt: skip

    def unresolved_count(self, work_id: UUID) -> int:
        return self.db.conn.execute(
            """SELECT COUNT(*) FROM disputes d JOIN segments s ON s.id = d.segment_id
               JOIN chapters c ON c.id = s.chapter_id
               WHERE c.work_id = ? AND d.resolved_at IS NULL AND d.deleted = 0""",
            (str(work_id),),
        ).fetchone()[0]


class GlossaryRepo:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, e: GlossaryEntry) -> None:
        """Insert, or update the existing entry for the same source term in the same scope.
        A locked entry is only overwritten by another locked entry (user decisions win)."""
        existing = self._find(e.work_id, e.source)
        if existing:
            if existing.locked and not e.locked:
                return
            e.id = existing.id
        self.db.conn.execute(
            """INSERT INTO glossary (id, work_id, source, target, kind, note, origin, locked,
                   review, updated_at, rev)
               VALUES (?,?,?,?,?,?,?,?,?,?,1)
               ON CONFLICT(id) DO UPDATE SET target=excluded.target, kind=excluded.kind,
                   note=excluded.note, origin=excluded.origin, locked=excluded.locked,
                   review=excluded.review, updated_at=excluded.updated_at,
                   rev=glossary.rev + 1""",
            (str(e.id), str(e.work_id) if e.work_id else None, e.source, e.target, e.kind.value,
             e.note, e.origin, int(e.locked), e.review, _ts(utcnow())),
        )  # fmt: skip

    def add_if_missing(self, e: GlossaryEntry) -> bool:
        """For model suggestions: never touch an existing entry. Returns True if added."""
        if self._find(e.work_id, e.source):
            return False
        self.upsert(e)
        return True

    def _find(self, work_id: UUID | None, source: str) -> GlossaryEntry | None:
        row = self.db.conn.execute(
            """SELECT * FROM glossary WHERE COALESCE(work_id, '') = ? AND source = ?
               AND deleted = 0""",
            (str(work_id) if work_id else "", source),
        ).fetchone()
        return self._from_row(row) if row else None

    def get(self, entry_id: UUID) -> GlossaryEntry | None:
        row = self.db.conn.execute(
            "SELECT * FROM glossary WHERE id = ? AND deleted = 0", (str(entry_id),)
        ).fetchone()
        return self._from_row(row) if row else None

    def pending(self, work_id: UUID) -> list[GlossaryEntry]:
        """Model suggestions of a work waiting for the user's review."""
        rows = self.db.conn.execute(
            """SELECT * FROM glossary WHERE work_id = ? AND review = 'pending' AND deleted = 0
               ORDER BY source""",
            (str(work_id),),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def for_work(self, work_id: UUID) -> list[GlossaryEntry]:
        """Work entries plus global ones; a work entry shadows a global entry.
        Rejected suggestions are left out."""
        rows = self.db.conn.execute(
            """SELECT * FROM glossary WHERE (work_id = ? OR work_id IS NULL) AND deleted = 0
               AND review != 'rejected' ORDER BY work_id IS NULL, source""",
            (str(work_id),),
        ).fetchall()
        seen: dict[str, GlossaryEntry] = {}
        for r in rows:
            e = self._from_row(r)
            seen.setdefault(e.source, e)
        return list(seen.values())

    @staticmethod
    def _from_row(r: sqlite3.Row) -> GlossaryEntry:
        return GlossaryEntry(
            id=UUID(r["id"]), work_id=_uuid(r["work_id"]), source=r["source"],
            target=r["target"], kind=GlossaryKind(r["kind"]), note=r["note"],
            origin=r["origin"], locked=bool(r["locked"]), review=r["review"],
        )  # fmt: skip


class JobRepo:
    def __init__(self, db: Database):
        self.db = db

    def save(self, j: TranslationJob) -> None:
        j.updated_at = utcnow()
        self.db.conn.execute(
            """INSERT INTO jobs (id, work_id, chapter_ids, state, plot_summary,
                   last_source_tail, last_translation_tail, chunks_since_summary, stats,
                   resume_after, last_error, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET state=excluded.state,
                   chapter_ids=excluded.chapter_ids, plot_summary=excluded.plot_summary,
                   last_source_tail=excluded.last_source_tail,
                   last_translation_tail=excluded.last_translation_tail,
                   chunks_since_summary=excluded.chunks_since_summary, stats=excluded.stats,
                   resume_after=excluded.resume_after, last_error=excluded.last_error,
                   updated_at=excluded.updated_at""",
            (str(j.id), str(j.work_id), json.dumps([str(c) for c in j.chapter_ids]),
             j.state.value, j.plot_summary, j.last_source_tail, j.last_translation_tail,
             j.chunks_since_summary, json.dumps(asdict(j.stats)), _ts(j.resume_after),
             j.last_error, _ts(j.updated_at)),
        )  # fmt: skip

    def get(self, job_id: UUID) -> TranslationJob | None:
        row = self.db.conn.execute("SELECT * FROM jobs WHERE id = ?", (str(job_id),)).fetchone()
        return self._from_row(row) if row else None

    def latest_for_work(self, work_id: UUID) -> TranslationJob | None:
        row = self.db.conn.execute(
            "SELECT * FROM jobs WHERE work_id = ? ORDER BY updated_at DESC LIMIT 1",
            (str(work_id),),
        ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _from_row(r: sqlite3.Row) -> TranslationJob:
        return TranslationJob(
            id=UUID(r["id"]), work_id=UUID(r["work_id"]),
            chapter_ids=[UUID(c) for c in json.loads(r["chapter_ids"])],
            state=JobState(r["state"]), plot_summary=r["plot_summary"],
            last_source_tail=r["last_source_tail"],
            last_translation_tail=r["last_translation_tail"],
            chunks_since_summary=r["chunks_since_summary"],
            stats=JobStats(**json.loads(r["stats"])), resume_after=_dt(r["resume_after"]),
            last_error=r["last_error"], updated_at=_dt(r["updated_at"]),
        )  # fmt: skip


class AccountRepo:
    def __init__(self, db: Database):
        self.db = db

    def save(self, a: ProviderAccount) -> None:
        self.db.conn.execute(
            """INSERT INTO provider_accounts (id, provider_id, label, model, rpm, priority,
                   enabled, cooldown_until, exhausted_until, last_error)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET label=excluded.label, model=excluded.model,
                   rpm=excluded.rpm, priority=excluded.priority, enabled=excluded.enabled,
                   cooldown_until=excluded.cooldown_until,
                   exhausted_until=excluded.exhausted_until, last_error=excluded.last_error""",
            (a.id, a.provider_id, a.label, a.model, a.rpm, a.priority, int(a.enabled),
             _ts(a.cooldown_until), _ts(a.exhausted_until), a.last_error),
        )  # fmt: skip

    def list(self) -> list[ProviderAccount]:
        rows = self.db.conn.execute(
            "SELECT * FROM provider_accounts ORDER BY priority, label"
        ).fetchall()
        return [
            ProviderAccount(id=r["id"], provider_id=r["provider_id"], label=r["label"],
                            model=r["model"], rpm=r["rpm"], priority=r["priority"],
                            enabled=bool(r["enabled"]), cooldown_until=_dt(r["cooldown_until"]),
                            exhausted_until=_dt(r["exhausted_until"]), last_error=r["last_error"])
            for r in rows
        ]  # fmt: skip

    def delete(self, account_id: str) -> None:
        self.db.conn.execute("DELETE FROM provider_accounts WHERE id = ?", (account_id,))


class Repositories:
    """All repositories over one database, so a chunk commit can span them in one transaction."""

    def __init__(self, db: Database):
        self.db = db
        self.works = WorkRepo(db)
        self.chapters = ChapterRepo(db)
        self.segments = SegmentRepo(db)
        self.notes = NoteRepo(db)
        self.disputes = DisputeRepo(db)
        self.glossary = GlossaryRepo(db)
        self.jobs = JobRepo(db)
        self.accounts = AccountRepo(db)
