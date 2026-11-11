"""Detect model refusals and silent distortions, so a segment is flagged for manual review
instead of being accepted quietly (skill section 8)."""

from __future__ import annotations

import re

_REFUSALS = re.compile(
    r"(i\s*(?:can(?:'|’)?t|cannot|am unable to|won(?:'|’)t)\s+(?:help|assist|translate|"
    r"provide|comply|continue)|i(?:'|’)m sorry,? but|as an ai\b|"
    r"вибачте,?\s+але\s+я\s+не\s+можу|я\s+не\s+можу\s+(?:допомогти|перекласти|виконати))",
    re.IGNORECASE,
)

# Typical character-length ratio translation/source by source language (Japanese and Korean
# are denser than Ukrainian or English). Far below the typical ratio means content was dropped.
TYPICAL_RATIO = {"ja": 1.8, "ko": 1.5, "en": 1.1}
TOO_SHORT_FACTOR = 0.35
MIN_SOURCE_CHARS = {"ja": 30, "ko": 30, "en": 80}


def review_reason(source: str, translation: str, source_lang: str, target_lang: str) -> str | None:
    """Return a short machine-readable reason, or None if the segment looks fine."""
    if not translation.strip():
        return "empty"
    if _REFUSALS.search(translation) and not _REFUSALS.search(source):
        return "refusal"
    src_len = len(source.strip())
    if src_len >= MIN_SOURCE_CHARS.get(source_lang, 50):
        ratio = len(translation.strip()) / src_len
        if ratio < TYPICAL_RATIO.get(source_lang, 1.0) * TOO_SHORT_FACTOR:
            return "too_short"
        if source_lang != target_lang and translation.strip() == source.strip():
            return "untranslated"
    return None
