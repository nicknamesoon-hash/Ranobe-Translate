"""Assemble prompts from blocks, in the order of skill section 9:
role → rules → work settings → relevant glossary → context → output format.

Every request is rebuilt from stored project state, so any account can serve any chunk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from ranobe.core.models import (
    CensorshipLevel,
    GlossaryEntry,
    HonorificsMode,
    NoteType,
    Segment,
    SegmentKind,
    TranslationJob,
    Work,
)
from ranobe.core.prompts import rules_en, rules_uk

LANGUAGE_NAMES = {"ja": "Japanese", "ko": "Korean", "en": "English", "uk": "Ukrainian"}
_RULES = {"uk": rules_uk, "en": rules_en}

CENSORSHIP = {
    CensorshipLevel.ORIGINAL: (
        "Content level: ORIGINAL. Render profanity, violence and explicit scenes with the same "
        "intensity as the source, within your usage policies."
    ),
    CensorshipLevel.SOFTENED: (
        "Content level: SOFTENED. Tone down profanity (mild substitutes), describe violence "
        "without graphic detail, describe intimate scenes without explicit detail."
    ),
    CensorshipLevel.FAMILY: (
        "Content level: FAMILY. Remove or replace profanity, keep violence minimal with no "
        "descriptions of wounds, fade intimate scenes to black."
    ),
}
CENSORSHIP_ALWAYS = (
    "The content level changes presentation, never the plot: events stay the same and the "
    'reader must understand what happened. Set "censored": true on every segment whose '
    "content you softened or removed. Never drop a segment silently."
)


@dataclass
class PromptChunk:
    """Segments of one request with short local ids (s1, s2, ...) mapped to real ids."""

    segments: list[Segment]

    @property
    def ids(self) -> dict[str, UUID]:
        return {f"s{i + 1}": seg.id for i, seg in enumerate(self.segments)}

    def payload(self, with_translation: bool = False) -> list[dict]:
        items = []
        for local_id, seg in zip(self.ids, self.segments, strict=True):
            item = {"id": local_id, "text": seg.source}
            if seg.kind is not SegmentKind.PARAGRAPH:
                item["kind"] = seg.kind.value
            if with_translation:
                item["draft"] = seg.translation or ""
            items.append(item)
        return items

    @property
    def source_text(self) -> str:
        return "\n".join(s.source for s in self.segments)


def relevant_glossary(entries: list[GlossaryEntry], *texts: str) -> list[GlossaryEntry]:
    """Only terms that occur in the chunk (or its context tail), to save context."""
    haystack = "\n".join(texts)
    return [e for e in entries if e.source and e.source in haystack]


def _glossary_block(entries: list[GlossaryEntry]) -> str:
    if not entries:
        return ""
    lines = []
    for e in sorted(entries, key=lambda e: e.source):
        mark = " [fixed]" if e.locked else ""
        note = f" — {e.note}" if e.note else ""
        lines.append(f"{e.source} = {e.target}{mark}{note}")
    return (
        "Glossary. Use these renderings exactly; entries marked [fixed] were chosen by the "
        "user and must never be changed:\n" + "\n".join(lines)
    )


def _rules_block(work: Work) -> str:
    rules = _RULES.get(work.target_lang, rules_en)
    parts = [rules.BASE]
    names = rules.NAMES.get(work.source_lang, "")
    if names:
        parts.append(names)
    if work.source_lang == "ja":
        parts.append(rules.HONORIFICS[HonorificsMode(work.settings.honorifics).value])
        parts.append(rules.HONORIFICS_ALWAYS)
    return "\n\n".join(parts)


def _format_block(work: Work) -> str:
    note_types = ", ".join(t.value for t in NoteType)
    lines = [
        "Reply with ONE JSON object and nothing else:",
        "{",
        '  "segments": [{"id": "s1", "translation": "...", "censored": false}],',
    ]
    if work.settings.with_notes:
        lines.append(
            '  "notes": [{"segment": "s1", "type": "cultural", "anchor": "<word in your '
            'translation>", "source_fragment": "<original>", "text": "<1-3 sentences>", '
            '"first_occurrence": true}],'
        )
    if work.settings.with_disputes:
        lines.append(
            '  "disputes": [{"segment": "s1", "source_fragment": "...", "issue": "...", '
            '"options": [{"text": "...", "rationale": "..."}], "recommended": 0, '
            '"add_to_glossary": true}],'
        )
    lines += ['  "glossary_suggestions": [{"source": "...", "target": "...", "kind": "term"}]', "}"]
    rules = [
        "Return every input segment exactly once, with the same id, in the same order. Never "
        "merge or split segments.",
        "Put the recommended option of a dispute into the translation text itself.",
        "glossary_suggestions: new names and terms not in the glossary; kind is one of name, "
        "term, place, technique, other.",
    ]
    if work.settings.with_notes:
        rules.append(
            f"notes: only for wordplay, cultural realia, specialised terms, references and "
            f"deliberate adaptation choices, on first occurrence only; types: {note_types}. "
            f"Short, neutral, in the target language, no spoilers."
        )
    if work.settings.with_disputes:
        rules.append(
            "disputes: only when there are several well-founded options and the choice depends "
            "on taste or wider context; 2-4 options with a short rationale each; at most 5 per "
            "request; add_to_glossary true if it concerns a term or name."
        )
    return "\n".join(lines) + "\n" + "\n".join(f"- {r}" for r in rules)


def build_translation_prompt(
    work: Work,
    job: TranslationJob,
    chunk: PromptChunk,
    glossary: list[GlossaryEntry],
) -> tuple[str, str]:
    src = LANGUAGE_NAMES.get(work.source_lang, work.source_lang)
    tgt = LANGUAGE_NAMES.get(work.target_lang, work.target_lang)
    terms = relevant_glossary(glossary, chunk.source_text, job.last_source_tail)
    blocks = [
        f"You are a professional literary translator of light novels and web novels from "
        f"{src} into {tgt}. Translate the given segments of «{work.title}».",
        _rules_block(work),
        CENSORSHIP[CensorshipLevel(work.settings.censorship)] + " " + CENSORSHIP_ALWAYS,
        _glossary_block(terms),
        _format_block(work),
    ]
    system = "\n\n".join(b for b in blocks if b)

    context = []
    if job.plot_summary:
        context.append(f"Story so far (for context only):\n{job.plot_summary}")
    if job.last_source_tail:
        context.append(
            "End of the previous passage (context only, do NOT translate it again):\n"
            f"Original:\n{job.last_source_tail}\nTranslation:\n{job.last_translation_tail}"
        )
    context.append(
        "Segments to translate:\n" + json.dumps(chunk.payload(), ensure_ascii=False, indent=1)
    )
    return system, "\n\n".join(context)


def build_edit_prompt(
    work: Work, chunk: PromptChunk, glossary: list[GlossaryEntry]
) -> tuple[str, str]:
    """Second pass: the editor sees the original, the draft and the glossary (v1 saw only the
    draft and could 'fix' names)."""
    tgt = LANGUAGE_NAMES.get(work.target_lang, work.target_lang)
    terms = relevant_glossary(glossary, chunk.source_text)
    rules = _RULES.get(work.target_lang, rules_en)
    blocks = [
        f"You are a literary editor of {tgt} translations of light novels. Improve each draft "
        f"against its original. Keep meaning, names and terms. Change only what needs changing.",
        _rules_block(work),
        CENSORSHIP[CensorshipLevel(work.settings.censorship)] + " " + CENSORSHIP_ALWAYS,
        _glossary_block(terms),
        "Check every draft against this list:\n" + rules.CHECKLIST,
        'Reply with ONE JSON object: {"segments": [{"id": "s1", "translation": "...", '
        '"censored": false}], "changes": ["short description of each change"]}. Return every '
        "segment exactly once.",
    ]
    system = "\n\n".join(b for b in blocks if b)
    user = "Segments:\n" + json.dumps(
        chunk.payload(with_translation=True), ensure_ascii=False, indent=1
    )
    return system, user


def build_summary_prompt(
    work: Work, previous_summary: str, new_translation: str
) -> tuple[str, str]:
    tgt = LANGUAGE_NAMES.get(work.target_lang, work.target_lang)
    system = (
        f"You maintain a running plot summary of a novel for its translator. Write in {tgt}, "
        f"at most 300 words: main characters and their relationships, key events, open threads, "
        f"tone. Plain text, no headings."
    )
    user = (
        f"Current summary:\n{previous_summary or '(none yet)'}\n\n"
        f"New passage (translated):\n{new_translation}\n\nUpdated summary:"
    )
    return system, user
