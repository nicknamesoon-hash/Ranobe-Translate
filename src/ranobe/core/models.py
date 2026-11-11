"""Domain models. Pure data: no I/O, no UI, no provider details."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID


def new_id() -> UUID:
    return uuid.uuid4()


def utcnow() -> datetime:
    return datetime.now(UTC)


SOURCE_LANGUAGES = ("ja", "ko", "en")
TARGET_LANGUAGES = ("uk", "en")


class SegmentStatus(StrEnum):
    PENDING = "pending"
    TRANSLATED = "translated"
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"
    EDITED = "edited"


class SegmentKind(StrEnum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    SEPARATOR = "separator"


class CensorshipLevel(StrEnum):
    ORIGINAL = "original"
    SOFTENED = "softened"
    FAMILY = "family"


class HonorificsMode(StrEnum):
    KEEP = "keep"
    ADAPT = "adapt"
    DROP = "drop"


class TranslationStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    DONE = "done"


class NoteType(StrEnum):
    UNTRANSLATABLE = "untranslatable"
    WORDPLAY = "wordplay"
    CULTURAL = "cultural"
    TERM = "term"
    REFERENCE = "reference"
    TRANSLATOR_CHOICE = "translator_choice"


class GlossaryKind(StrEnum):
    NAME = "name"
    TERM = "term"
    PLACE = "place"
    TECHNIQUE = "technique"
    OTHER = "other"


class JobState(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_QUOTA = "waiting_quota"
    FAILED = "failed"
    DONE = "done"


@dataclass
class QualityPreset:
    id: str
    temperature: float
    chunk_tokens: int  # approximate input budget for source text per request
    tail_chars: int  # how much of the previous chunk is passed as context
    two_pass: bool


QUALITY_PRESETS: dict[str, QualityPreset] = {
    p.id: p
    for p in (
        QualityPreset("fast", temperature=0.3, chunk_tokens=1800, tail_chars=500, two_pass=False),
        QualityPreset(
            "balanced", temperature=0.3, chunk_tokens=1200, tail_chars=900, two_pass=False
        ),
        QualityPreset("quality", temperature=0.2, chunk_tokens=800, tail_chars=1200, two_pass=True),
    )
}


@dataclass
class WorkSettings:
    censorship: CensorshipLevel = CensorshipLevel.ORIGINAL
    honorifics: HonorificsMode = HonorificsMode.KEEP
    quality_preset: str = "balanced"
    with_notes: bool = True
    with_disputes: bool = True
    with_summary: bool = True
    # Account ids in priority order; empty = all enabled accounts by their priority.
    account_chain: list[str] = field(default_factory=list)

    @property
    def preset(self) -> QualityPreset:
        return QUALITY_PRESETS.get(self.quality_preset, QUALITY_PRESETS["balanced"])


@dataclass
class Work:
    title: str
    source_lang: str
    target_lang: str
    id: UUID = field(default_factory=new_id)
    original_title: str | None = None
    author: str | None = None
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    synopsis: str = ""
    translation_status: TranslationStatus = TranslationStatus.PLANNED
    settings: WorkSettings = field(default_factory=WorkSettings)
    updated_at: datetime = field(default_factory=utcnow)
    rev: int = 0


@dataclass
class Chapter:
    work_id: UUID
    index: int
    title: str
    id: UUID = field(default_factory=new_id)
    rev: int = 0


@dataclass
class Segment:
    chapter_id: UUID
    index: int
    source: str
    kind: SegmentKind = SegmentKind.PARAGRAPH
    id: UUID = field(default_factory=new_id)
    translation: str | None = None
    machine_translation: str | None = None
    status: SegmentStatus = SegmentStatus.PENDING
    censored: bool = False
    translated_by: str | None = None  # "provider/model"
    review_reason: str | None = None
    rev: int = 0


@dataclass
class DisputeOption:
    text: str
    rationale: str


@dataclass
class Dispute:
    segment_id: UUID
    source_fragment: str
    issue: str
    options: list[DisputeOption]
    recommended: int
    add_to_glossary: bool = False
    id: UUID = field(default_factory=new_id)
    chosen: int | None = None
    custom_text: str | None = None
    resolved_at: datetime | None = None


@dataclass
class Note:
    segment_id: UUID
    type: NoteType
    anchor: str
    source_fragment: str
    text: str
    first_occurrence: bool = True
    display: Literal["footnote", "tooltip"] = "footnote"
    origin: Literal["llm", "user"] = "llm"
    id: UUID = field(default_factory=new_id)


@dataclass
class GlossaryEntry:
    source: str
    target: str
    work_id: UUID | None = None  # None = global glossary
    kind: GlossaryKind = GlossaryKind.TERM
    note: str | None = None
    origin: Literal["user", "dispute", "llm_suggestion"] = "user"
    locked: bool = False
    id: UUID = field(default_factory=new_id)


@dataclass
class JobStats:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    chunks_done: int = 0
    seconds: float = 0.0


@dataclass
class TranslationJob:
    work_id: UUID
    chapter_ids: list[UUID]
    id: UUID = field(default_factory=new_id)
    state: JobState = JobState.PAUSED
    plot_summary: str = ""
    last_source_tail: str = ""
    last_translation_tail: str = ""
    chunks_since_summary: int = 0
    stats: JobStats = field(default_factory=JobStats)
    resume_after: datetime | None = None
    last_error: str | None = None
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class ProviderAccount:
    provider_id: str
    label: str
    model: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    rpm: float = 5.0
    priority: int = 100  # lower = tried first
    enabled: bool = True
    cooldown_until: datetime | None = None
    exhausted_until: datetime | None = None
    last_error: str | None = None

    @property
    def secret_ref(self) -> str:
        return f"account:{self.id}"
