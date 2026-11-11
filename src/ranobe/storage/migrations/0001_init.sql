-- Initial schema. Every synced table has rev/updated_at/deleted for phase 6 sync.

CREATE TABLE works (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    original_title TEXT,
    author TEXT,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    genres TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    synopsis TEXT NOT NULL DEFAULT '',
    translation_status TEXT NOT NULL,
    settings TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    rev INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE chapters (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    title TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    rev INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX chapters_work ON chapters(work_id, idx);

CREATE TABLE segments (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    translation TEXT,
    machine_translation TEXT,
    status TEXT NOT NULL,
    censored INTEGER NOT NULL DEFAULT 0,
    translated_by TEXT,
    review_reason TEXT,
    updated_at TEXT NOT NULL,
    rev INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX segments_chapter ON segments(chapter_id, idx);
CREATE INDEX segments_status ON segments(chapter_id, status);

CREATE TABLE notes (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    anchor TEXT NOT NULL,
    source_fragment TEXT NOT NULL,
    text TEXT NOT NULL,
    first_occurrence INTEGER NOT NULL,
    display TEXT NOT NULL,
    origin TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    rev INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX notes_segment ON notes(segment_id);

CREATE TABLE disputes (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    source_fragment TEXT NOT NULL,
    issue TEXT NOT NULL,
    options TEXT NOT NULL,
    recommended INTEGER NOT NULL,
    add_to_glossary INTEGER NOT NULL,
    chosen INTEGER,
    custom_text TEXT,
    resolved_at TEXT,
    updated_at TEXT NOT NULL,
    rev INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX disputes_segment ON disputes(segment_id);

CREATE TABLE glossary (
    id TEXT PRIMARY KEY,
    work_id TEXT REFERENCES works(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    kind TEXT NOT NULL,
    note TEXT,
    origin TEXT NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    rev INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0
);
-- One entry per source term per scope; '' stands for the global scope.
CREATE UNIQUE INDEX glossary_unique ON glossary(COALESCE(work_id, ''), source);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    chapter_ids TEXT NOT NULL,
    state TEXT NOT NULL,
    plot_summary TEXT NOT NULL DEFAULT '',
    last_source_tail TEXT NOT NULL DEFAULT '',
    last_translation_tail TEXT NOT NULL DEFAULT '',
    chunks_since_summary INTEGER NOT NULL DEFAULT 0,
    stats TEXT NOT NULL,
    resume_after TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL
);

-- Device-local: never synced, never exported. Keys live in the secret store, not here.
CREATE TABLE provider_accounts (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    label TEXT NOT NULL,
    model TEXT NOT NULL,
    rpm REAL NOT NULL,
    priority INTEGER NOT NULL,
    enabled INTEGER NOT NULL,
    cooldown_until TEXT,
    exhausted_until TEXT,
    last_error TEXT
);
