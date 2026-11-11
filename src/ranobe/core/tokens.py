"""Cheap token estimate. Good enough to size chunks; never used for billing."""

from __future__ import annotations


def _is_dense(ch: str) -> bool:
    # Han, kana, Hangul and full-width forms cost roughly one token per character.
    return "぀" <= ch <= "ヿ" or "㐀" <= ch <= "鿿" or "가" <= ch <= "힯" or "＀" <= ch <= "￯"


def estimate_tokens(text: str) -> int:
    dense = sum(1 for ch in text if _is_dense(ch))
    other = len(text) - dense
    return dense + (other + 3) // 4
