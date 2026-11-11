"""Parse and validate LLM JSON replies.

Segments are strict: every requested id exactly once, or the reply is invalid. Notes, disputes
and glossary suggestions are lenient: a malformed item is dropped, not the whole chunk.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ranobe.core.errors import InvalidOutput
from ranobe.core.models import GlossaryKind, NoteType

MAX_DISPUTES = 5


@dataclass
class SegmentResult:
    translation: str
    censored: bool = False


@dataclass
class NoteResult:
    segment: str
    type: NoteType
    anchor: str
    source_fragment: str
    text: str
    first_occurrence: bool = True


@dataclass
class DisputeResult:
    segment: str
    source_fragment: str
    issue: str
    options: list[tuple[str, str]]
    recommended: int
    add_to_glossary: bool


@dataclass
class GlossarySuggestion:
    source: str
    target: str
    kind: GlossaryKind


@dataclass
class TranslationResult:
    segments: dict[str, SegmentResult]
    notes: list[NoteResult] = field(default_factory=list)
    disputes: list[DisputeResult] = field(default_factory=list)
    glossary_suggestions: list[GlossarySuggestion] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(text: str) -> dict[str, Any]:
    cleaned = _FENCE.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise InvalidOutput("reply is not JSON") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as e:
            raise InvalidOutput(f"reply is not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise InvalidOutput("reply JSON is not an object")
    return data


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_translation(text: str, expected_ids: list[str]) -> TranslationResult:
    data = extract_json(text)
    raw_segments = data.get("segments")
    if not isinstance(raw_segments, list):
        raise InvalidOutput('missing "segments" list')

    segments: dict[str, SegmentResult] = {}
    duplicates: list[str] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        sid = _str(item.get("id"))
        if sid not in expected_ids:
            continue
        if sid in segments:
            duplicates.append(sid)
            continue
        translation = item.get("translation")
        if not isinstance(translation, str):
            continue
        segments[sid] = SegmentResult(translation.strip(), bool(item.get("censored", False)))
    missing = [i for i in expected_ids if i not in segments]
    if missing or duplicates:
        raise InvalidOutput(
            f"segments mismatch: missing {missing or 'none'}, duplicated {duplicates or 'none'}"
        )

    result = TranslationResult(segments=segments)
    for item in data.get("notes") or []:
        note = _parse_note(item, expected_ids)
        if note:
            result.notes.append(note)
    for item in data.get("disputes") or []:
        dispute = _parse_dispute(item, expected_ids)
        if dispute and len(result.disputes) < MAX_DISPUTES:
            result.disputes.append(dispute)
    for item in data.get("glossary_suggestions") or []:
        suggestion = _parse_suggestion(item)
        if suggestion:
            result.glossary_suggestions.append(suggestion)
    result.changes = [c for c in data.get("changes") or [] if isinstance(c, str)]
    return result


def _parse_note(item: Any, ids: list[str]) -> NoteResult | None:
    if not isinstance(item, dict) or _str(item.get("segment")) not in ids:
        return None
    try:
        note_type = NoteType(_str(item.get("type")))
    except ValueError:
        return None
    text, anchor = _str(item.get("text")), _str(item.get("anchor"))
    if not text or not anchor:
        return None
    return NoteResult(
        segment=_str(item.get("segment")),
        type=note_type,
        anchor=anchor,
        source_fragment=_str(item.get("source_fragment")),
        text=text,
        first_occurrence=bool(item.get("first_occurrence", True)),
    )


def _parse_dispute(item: Any, ids: list[str]) -> DisputeResult | None:
    if not isinstance(item, dict) or _str(item.get("segment")) not in ids:
        return None
    options = [
        (_str(o.get("text")), _str(o.get("rationale")))
        for o in item.get("options") or []
        if isinstance(o, dict) and _str(o.get("text"))
    ]
    if not 2 <= len(options) <= 4:
        return None
    recommended = item.get("recommended", 0)
    if not isinstance(recommended, int) or not 0 <= recommended < len(options):
        recommended = 0
    return DisputeResult(
        segment=_str(item.get("segment")),
        source_fragment=_str(item.get("source_fragment")),
        issue=_str(item.get("issue")),
        options=options,
        recommended=recommended,
        add_to_glossary=bool(item.get("add_to_glossary", False)),
    )


def _parse_suggestion(item: Any) -> GlossarySuggestion | None:
    if not isinstance(item, dict):
        return None
    source, target = _str(item.get("source")), _str(item.get("target"))
    if not source or not target:
        return None
    try:
        kind = GlossaryKind(_str(item.get("kind")) or "term")
    except ValueError:
        kind = GlossaryKind.OTHER
    return GlossarySuggestion(source, target, kind)
