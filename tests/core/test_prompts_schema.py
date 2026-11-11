import json

import pytest

from ranobe.core.errors import InvalidOutput
from ranobe.core.llm_schema import extract_json, parse_translation
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
from ranobe.core.prompts.builder import (
    PromptChunk,
    build_edit_prompt,
    build_summary_prompt,
    build_translation_prompt,
    relevant_glossary,
)
from ranobe.core.refusal import review_reason


def _work(src="ja", tgt="uk", **settings):
    w = Work(title="Тест", source_lang=src, target_lang=tgt)
    for k, v in settings.items():
        setattr(w.settings, k, v)
    return w


def _chunk(*texts):
    from uuid import uuid4

    cid = uuid4()
    return PromptChunk([Segment(chapter_id=cid, index=i, source=t) for i, t in enumerate(texts)])


GLOSSARY = [
    GlossaryEntry(source="剣聖", target="Майстер Меча", locked=True),
    GlossaryEntry(source="魔力", target="мана"),
    GlossaryEntry(source="竜", target="дракон"),
]


def test_relevant_glossary_only_terms_in_chunk():
    got = relevant_glossary(GLOSSARY, "剣聖は笑った。", "魔力が尽きた。")
    assert [e.source for e in got] == ["剣聖", "魔力"]


def test_translation_prompt_contains_blocks_in_order():
    work = _work(censorship=CensorshipLevel.SOFTENED, honorifics=HonorificsMode.KEEP)
    job = TranslationJob(
        work_id=work.id,
        chapter_ids=[],
        plot_summary="Герой прибув до міста.",
        last_source_tail="前の文。",
        last_translation_tail="Попереднє речення.",
    )
    chunk = _chunk("剣聖は笑った。", "第2章")
    chunk.segments[1].kind = SegmentKind.HEADING
    system, user = build_translation_prompt(work, job, chunk, GLOSSARY)

    order = [
        "Japanese into Ukrainian",
        "Лапки «ялинки»",
        "Коваленка",
        "Сато-сан",
        "SOFTENED",
        "剣聖 = Майстер Меча [fixed]",
        '"segments"',
    ]
    positions = [system.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert "竜" not in system  # irrelevant glossary entry left out
    assert "Герой прибув" in user and "do NOT translate it again" in user
    payload = json.loads(user.split("Segments to translate:\n", 1)[1])
    assert payload == [
        {"id": "s1", "text": "剣聖は笑った。"},
        {"id": "s2", "text": "第2章", "kind": "heading"},
    ]


def test_prompt_for_english_target_from_korean_has_no_honorifics():
    system, _ = build_translation_prompt(
        _work("ko", "en"), TranslationJob(work_id=None, chapter_ids=[]), _chunk("그는 웃었다."), []
    )
    assert "Korean into English" in system and "Revised Romanization" in system
    assert "Sato-san" not in system  # honorific rules apply to Japanese sources only


def test_notes_and_disputes_can_be_switched_off():
    work = _work(with_notes=False, with_disputes=False)
    system, _ = build_translation_prompt(
        work, TranslationJob(work_id=work.id, chapter_ids=[]), _chunk("文。"), []
    )
    assert '"notes"' not in system and '"disputes"' not in system


def test_edit_prompt_sees_original_and_draft():
    chunk = _chunk("剣聖は笑った。")
    chunk.segments[0].translation = "Кенсей засміявся."
    system, user = build_edit_prompt(_work(), chunk, GLOSSARY)
    assert "剣聖 = Майстер Меча" in system
    assert json.loads(user.split("\n", 1)[1]) == [
        {"id": "s1", "text": "剣聖は笑った。", "draft": "Кенсей засміявся."}
    ]


def test_summary_prompt():
    system, user = build_summary_prompt(_work(), "", "Він прийшов.")
    assert "300 words" in system and "(none yet)" in user


GOOD = {
    "segments": [
        {"id": "s1", "translation": "Один."},
        {"id": "s2", "translation": "Два.", "censored": True},
    ],
    "notes": [
        {
            "segment": "s1",
            "type": "cultural",
            "anchor": "Обон",
            "source_fragment": "お盆",
            "text": "Свято.",
        },
        {"segment": "s1", "type": "bogus", "anchor": "x", "text": "y"},
        {"segment": "s9", "type": "term", "anchor": "x", "text": "y"},
    ],
    "disputes": [
        {
            "segment": "s2",
            "source_fragment": "剣聖",
            "issue": "Титул",
            "options": [
                {"text": "Святий Меча", "rationale": "a"},
                {"text": "Кенсей", "rationale": "b"},
            ],
            "recommended": 7,
            "add_to_glossary": True,
        },
        {"segment": "s2", "options": [{"text": "only one"}]},
    ],
    "glossary_suggestions": [
        {"source": "魔力", "target": "мана", "kind": "weird"},
        {"source": "", "target": "x"},
    ],
}


def test_parse_translation_lenient_extras():
    result = parse_translation(
        "```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```", ["s1", "s2"]
    )
    assert result.segments["s2"].censored and result.segments["s1"].translation == "Один."
    assert [n.type for n in result.notes] == [NoteType.CULTURAL]
    assert len(result.disputes) == 1 and result.disputes[0].recommended == 0
    assert [(g.source, g.kind.value) for g in result.glossary_suggestions] == [("魔力", "other")]


@pytest.mark.parametrize(
    "reply",
    [
        "not json at all",
        '{"segments": [{"id": "s1", "translation": "a"}]}',  # s2 missing
        '{"segments": [{"id": "s1", "translation": "a"}, {"id": "s1", "translation": "b"},'
        ' {"id": "s2", "translation": "c"}]}',  # duplicate
        '{"translation": "no segments"}',
        "[1, 2]",
    ],
)
def test_parse_translation_strict_segments(reply):
    with pytest.raises(InvalidOutput):
        parse_translation(reply, ["s1", "s2"])


def test_extract_json_with_prose_around():
    assert extract_json('Here you go:\n{"segments": []}\nThanks') == {"segments": []}


@pytest.mark.parametrize(
    ("source", "translation", "src", "expected"),
    [
        ("彼は笑った。", "", "ja", "empty"),
        (
            "彼は剣を抜いて、静かに笑った。それから彼女の方を見て、何も言わずに歩き出した。",
            "I'm sorry, but I can't help with that.",
            "ja",
            "refusal",
        ),
        (
            "彼は剣を抜いて、静かに笑った。それから彼女の方を見て、何も言わずに歩き出した。",
            "Він пішов.",
            "ja",
            "too_short",
        ),
        (
            "彼は剣を抜いて、静かに笑った。それから彼女の方を見て、何も言わずに歩き出した。",
            "Він вихопив меч і тихо засміявся. Потім глянув на неї й мовчки рушив уперед.",
            "ja",
            None,
        ),
        (
            "He said nothing for a long while, then turned away and walked into the dark forest.",
            "He said nothing for a long while, then turned away and walked into the dark forest.",
            "en",
            "untranslated",
        ),
        ("短い。", "Коротко.", "ja", None),
    ],
)
def test_review_reason(source, translation, src, expected):
    assert review_reason(source, translation, src, "uk") == expected
