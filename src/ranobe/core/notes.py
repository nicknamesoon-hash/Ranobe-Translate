"""Rules for translator's notes that do not depend on storage."""

from __future__ import annotations


def note_key(source_fragment: str, anchor: str) -> str:
    """What a note explains. Two notes with the same key explain the same thing."""
    return (source_fragment or anchor).strip().casefold()


def first_occurrences[T](candidates: list[T], key, seen: set[str]) -> list[T]:
    """Keep only notes whose key is not in `seen` yet (the work's existing notes), and only
    the first of several equal keys. `seen` is updated with what was kept."""
    kept = []
    for item in candidates:
        k = key(item)
        if not k or k in seen:
            continue
        seen.add(k)
        kept.append(item)
    return kept
