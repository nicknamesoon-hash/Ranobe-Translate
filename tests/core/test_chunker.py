from dataclasses import dataclass

from ranobe.core.chunker import split_chunks, take_chunk
from ranobe.core.tokens import estimate_tokens


@dataclass
class S:
    source: str


def test_estimate_tokens_dense_vs_latin():
    assert estimate_tokens("あいうえお") == 5
    assert estimate_tokens("한국어") == 3
    assert estimate_tokens("abcdefgh") == 2
    assert estimate_tokens("") == 0


def test_take_chunk_respects_budget():
    segs = [S("あ" * 40) for _ in range(5)]
    assert len(take_chunk(segs, 100)) == 2


def test_take_chunk_always_takes_one():
    assert len(take_chunk([S("あ" * 500)], 100)) == 1


def test_split_chunks_covers_all_in_order():
    segs = [S("あ" * n) for n in (10, 50, 60, 5, 90, 30)]
    chunks = split_chunks(segs, 100)
    assert [s for c in chunks for s in c] == segs
    assert all(sum(estimate_tokens(s.source) for s in c) <= 100 or len(c) == 1 for c in chunks)
