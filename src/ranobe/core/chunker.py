"""Group consecutive segments into chunks that fit a token budget.

Chunks are not stored. Resume works by picking the next pending segments again, so changing
the preset or this algorithm never breaks a paused translation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ranobe.core.tokens import estimate_tokens


def take_chunk[T](segments: Iterable[T], budget_tokens: int, text_of=lambda s: s.source) -> list[T]:
    """Take segments from the front until the budget is used. Always takes at least one."""
    chunk: list[T] = []
    used = 0
    for seg in segments:
        cost = estimate_tokens(text_of(seg))
        if chunk and used + cost > budget_tokens:
            break
        chunk.append(seg)
        used += cost
    return chunk


def split_chunks[T](
    segments: Sequence[T], budget_tokens: int, text_of=lambda s: s.source
) -> list[list[T]]:
    chunks: list[list[T]] = []
    rest = list(segments)
    while rest:
        chunk = take_chunk(rest, budget_tokens, text_of)
        chunks.append(chunk)
        rest = rest[len(chunk) :]
    return chunks
