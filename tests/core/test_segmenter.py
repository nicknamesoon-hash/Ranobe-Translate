import re

from hypothesis import given
from hypothesis import strategies as st

from ranobe.core.models import SegmentKind
from ranobe.core.segmenter import segment_text, split_paragraphs, split_sentences


def test_blank_line_paragraphs():
    text = "First paragraph\nstill first.\n\nSecond one.\n\n\nThird."
    assert split_paragraphs(text) == ["First paragraph\nstill first.", "Second one.", "Third."]


def test_one_paragraph_per_line_without_blank_lines():
    text = "彼は笑った。\n「本当か？」\n彼女は頷いた。"
    assert split_paragraphs(text) == ["彼は笑った。", "「本当か？」", "彼女は頷いた。"]


def test_windows_newlines_and_bom():
    assert split_paragraphs("﻿A\r\n\r\nB\r\n") == ["A", "B"]


def test_japanese_sentences_split_without_spaces():
    assert split_sentences("彼は笑った。彼女は泣いた！「本当？」") == [
        "彼は笑った。",
        "彼女は泣いた！",
        "「本当？」",
    ]


def test_korean_and_english_sentences():
    assert split_sentences("그는 웃었다. 그녀는 울었다.") == ["그는 웃었다.", "그녀는 울었다."]
    assert split_sentences("Pi is 3.14. Done!") == ["Pi is 3.14.", "Done!"]


def test_long_japanese_paragraph_splits_on_sentence_boundary():
    para = "彼は笑った。" * 300  # 1800 chars, no spaces
    segs = segment_text(para, max_chars=500)
    assert len(segs) == 4
    assert all(s.text.endswith("。") for s in segs)
    assert all(len(s.text) <= 500 for s in segs)
    assert "".join(s.text for s in segs) == para


def test_runaway_sentence_is_hard_cut():
    segs = segment_text("あ" * 1200, max_chars=500)
    assert [len(s.text) for s in segs] == [500, 500, 200]


def test_headings_and_separators():
    text = "第3章 再会\n本文です。\n＊＊＊\nChapter 12: The End\n제5화\nPrologue"
    kinds = [s.kind for s in segment_text(text)]
    assert kinds == [
        SegmentKind.HEADING,
        SegmentKind.PARAGRAPH,
        SegmentKind.SEPARATOR,
        SegmentKind.HEADING,
        SegmentKind.HEADING,
        SegmentKind.HEADING,
    ]


def test_long_line_starting_like_heading_is_paragraph():
    line = "Chapter " + "x" * 100
    assert segment_text(line)[0].kind is SegmentKind.PARAGRAPH


def test_empty_text():
    assert segment_text("  \n\n ") == []


_ws = re.compile(r"\s+")


@given(st.text(alphabet=st.sampled_from(list("あいう。！？ ab.\n「」")), max_size=3000))
def test_no_characters_lost(text):
    segs = segment_text(text, max_chars=200)
    joined = "".join(s.text for s in segs)
    assert _ws.sub("", joined) == _ws.sub("", text.replace("﻿", ""))
    assert all(len(s.text) <= 200 for s in segs)
