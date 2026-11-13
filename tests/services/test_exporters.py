import os
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from uuid import uuid4

import pytest
from PIL import Image

from ranobe.core.footnotes import split_at_anchors
from ranobe.core.models import Note, NoteType, SegmentKind, SegmentStatus
from ranobe.services.exporters import (
    ExportOptions,
    UnknownFormat,
    collect_book,
    exporter_for_path,
    exporter_ids,
    get_exporter,
)
from ranobe.services.exporters.cbz import wrap
from ranobe.services.importers.base import ImportedBlock, ImportedBook, ImportedChapter
from ranobe.services.library import import_book

XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_NS = "{http://www.idpf.org/2007/ops}"
OPF = "{http://www.idpf.org/2007/opf}"
DC = "{http://purl.org/dc/elements/1.1/}"


def _note(anchor: str, text: str) -> Note:
    return Note(uuid4(), NoteType.CULTURAL, anchor, "", text)


@pytest.fixture
def book(repos):
    imported = ImportedBook(
        title="テスト",
        chapters=[
            ImportedChapter(
                "第1章",
                [
                    ImportedBlock(SegmentKind.HEADING, "第1章　始まり"),
                    ImportedBlock(SegmentKind.PARAGRAPH, "サトウさんは笑った。"),
                    ImportedBlock(SegmentKind.SEPARATOR, "＊＊＊"),
                    ImportedBlock(SegmentKind.PARAGRAPH, "お盆が来た。"),
                ],
            ),
            ImportedChapter("第2章", [ImportedBlock(SegmentKind.PARAGRAPH, "未訳。")]),
        ],
    )
    work = import_book(repos, imported, "ja", "uk")
    work.title, work.author = "Тест & <друзі>", "Автор"
    work.synopsis, work.genres = "Анотація.", ["фентезі"]
    repos.works.save(work)
    first, _second = repos.chapters.for_work(work.id)
    heading, para, sep, obon = repos.segments.for_chapter(first.id)
    translations = [
        (heading, "Розділ 1. Початок"),
        (para, "Сато-сан засміялася."),
        (sep, "＊＊＊"),
        (obon, "Настав Обон."),
    ]
    for seg, text in translations:
        seg.translation, seg.status = text, SegmentStatus.TRANSLATED
        repos.segments.save(seg)
    repos.notes.add(
        Note(para.id, NoteType.CULTURAL, "Сато-сан", "さん", "Ввічливий суфікс <-сан>.")
    )
    repos.notes.add(Note(obon.id, NoteType.CULTURAL, "Обон", "お盆", "Свято пам'яті предків."))
    return repos, work


def test_split_at_anchors_places_notes_after_anchor_and_keeps_lost_ones():
    a, b, lost = _note("Меч", "a"), _note("він", "b"), _note("немає", "lost")
    assert split_at_anchors("Святий Меч, сказав він.", [b, lost, a]) == [
        "Святий Меч", a, ", сказав він", b, ".", lost,
    ]  # fmt: skip
    assert split_at_anchors("Текст", []) == ["Текст"]


def test_registry():
    assert exporter_ids() == ["cbz", "epub", "txt"]
    assert get_exporter("EPUB").id == "epub"
    assert exporter_for_path(__import__("pathlib").Path("x.cbz")).id == "cbz"
    with pytest.raises(UnknownFormat):
        get_exporter("pdf")


def test_collect_uses_translated_heading_as_title(book):
    repos, work = book
    exported = collect_book(repos, work)
    assert [c.title for c in exported.chapters] == ["Розділ 1. Початок", "第2章"]
    assert next(s.kind for s in exported.chapters[0].segments) is SegmentKind.PARAGRAPH
    assert exported.chapters[1].segments[0].text == "未訳。"  # untranslated → original


def test_txt_export(book, tmp_path):
    repos, work = book
    out = tmp_path / "book.txt"
    get_exporter("txt").export(collect_book(repos, work), ExportOptions(), out)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("Тест & <друзі>\nАвтор\n\n\nРозділ 1. Початок\n\n")
    assert "Сато-сан[1] засміялася." in text and "Настав Обон[2]." in text
    assert "———\n[1] Ввічливий суфікс <-сан>.\n[2] Свято пам'яті предків." in text

    get_exporter("txt").export(
        collect_book(repos, work), ExportOptions(side_by_side=True, with_notes=False), out
    )
    text = out.read_text(encoding="utf-8")
    assert "サトウさんは笑った。\nСато-сан засміялася." in text and "[1]" not in text


def _epub(book, tmp_path, **opts):
    repos, work = book
    out = tmp_path / "book.epub"
    get_exporter("epub").export(collect_book(repos, work), ExportOptions(**opts), out)
    return work, zipfile.ZipFile(out)


def test_epub_structure_and_metadata(book, tmp_path):
    work, zf = _epub(book, tmp_path)
    first = zf.infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert zf.read("mimetype") == b"application/epub+zip"
    assert b"OEBPS/content.opf" in zf.read("META-INF/container.xml")

    opf = ET.fromstring(zf.read("OEBPS/content.opf"))
    meta = opf.find(f"{OPF}metadata")
    assert meta.find(f"{DC}identifier").text == f"urn:uuid:{work.id}"
    assert meta.find(f"{DC}title").text == "Тест & <друзі>"
    assert meta.find(f"{DC}language").text == "uk"
    assert meta.find(f"{DC}creator").text == "Автор"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", meta.find(f"{OPF}meta").text)
    hrefs = {i.get("href") for i in opf.iter(f"{OPF}item")}
    spine = [i.get("idref") for i in opf.iter(f"{OPF}itemref")]
    assert {"nav.xhtml", "toc.ncx", "style.css", "ch0001.xhtml", "ch0002.xhtml"} <= hrefs
    assert spine == ["ch1", "ch2"]
    for href in hrefs:  # every manifest item exists, every XHTML is well-formed XML
        data = zf.read(f"OEBPS/{href}")
        if href.endswith((".xhtml", ".ncx")):
            ET.fromstring(data)


def test_epub_footnotes_pair_up(book, tmp_path):
    _, zf = _epub(book, tmp_path)
    root = ET.fromstring(zf.read("OEBPS/ch0001.xhtml"))
    refs = [a for a in root.iter(f"{XHTML}a") if a.get(f"{EPUB_NS}type") == "noteref"]
    asides = [a for a in root.iter(f"{XHTML}aside") if a.get(f"{EPUB_NS}type") == "footnote"]
    assert [r.get("href") for r in refs] == [f"#{a.get('id')}" for a in asides] == [
        "#note1", "#note2",
    ]  # fmt: skip
    assert "Ввічливий суфікс <-сан>." in "".join(asides[0].itertext())
    assert root.find(f".//{XHTML}h1").text == "Розділ 1. Початок"


def test_epub_cover_and_side_by_side(book, tmp_path):
    cover = tmp_path / "cover.png"
    Image.new("RGB", (60, 90), "red").save(cover)
    _, zf = _epub(book, tmp_path, cover=cover, side_by_side=True)
    opf = ET.fromstring(zf.read("OEBPS/content.opf"))
    items = {i.get("id"): i for i in opf.iter(f"{OPF}item")}
    assert items["cover-image"].get("properties") == "cover-image"
    assert next(i.get("idref") for i in opf.iter(f"{OPF}itemref")) == "cover"
    assert zf.read("OEBPS/cover.png") == cover.read_bytes()
    chapter = zf.read("OEBPS/ch0001.xhtml").decode()
    assert '<p class="src" lang="ja" xml:lang="ja">サトウさんは笑った。</p>' in chapter


def test_epub_identifier_is_stable(book, tmp_path):
    work, zf = _epub(book, tmp_path)
    again = zipfile.ZipFile(tmp_path / "book.epub")
    assert zf.read("OEBPS/content.opf") == again.read("OEBPS/content.opf")
    assert f"urn:uuid:{work.id}".encode() in again.read("OEBPS/toc.ncx")


def test_wrap_breaks_long_words_between_characters():
    from ranobe.services.exporters.cbz import _Fonts

    font = _Fonts.load(30).body
    lines = wrap(["一" * 40, "кіт", "пес"], font, 300)
    assert all(font.getlength(" ".join(line)) <= 300 for line in lines)
    assert "".join(lines[0]) == "一" * len(lines[0][0]) and lines[-1][-1] == "пес"


def test_cbz_pages(book, tmp_path):
    repos, work = book
    out = tmp_path / "book.cbz"
    opts = ExportOptions(page_size=(400, 600), font_size=20)
    get_exporter("cbz").export(collect_book(repos, work), opts, out)
    zf = zipfile.ZipFile(out)
    pages = sorted(n for n in zf.namelist() if n.endswith(".png"))
    # title page, then each chapter starts on its own page
    assert pages == ["0001.png", "0002.png", "0003.png"]
    for name in pages:
        with Image.open(zf.open(name)) as img:
            assert img.size == (400, 600) and img.getextrema()[0] < 128  # has dark text
    info = ET.fromstring(zf.read("ComicInfo.xml"))
    assert info.find("Title").text == "Тест & <друзі>" and info.find("PageCount").text == "3"
    with Image.open(zf.open("0002.png")) as img:  # chapter 1 has notes: bottom is not blank
        assert img.crop((0, 450, 400, 560)).getextrema()[0] < 128


def test_cbz_cover_and_page_breaks(book, tmp_path):
    repos, work = book
    first = repos.chapters.for_work(work.id)[0]
    para = repos.segments.for_chapter(first.id)[1]
    para.translation = "Дуже довгий абзац тексту. " * 120
    repos.segments.save(para)
    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (300, 300), "white").save(cover)
    out = tmp_path / "book.cbz"
    get_exporter("cbz").export(
        collect_book(repos, work), ExportOptions(cover=cover, page_size=(400, 600)), out
    )
    pages = [n for n in zipfile.ZipFile(out).namelist() if n.endswith(".png")]
    assert len(pages) > 4  # cover + several pages for the long paragraph + chapter 2


@pytest.mark.skipif(
    not os.environ.get("EPUBCHECK_JAR"), reason="EPUBCHECK_JAR not set (runs in CI)"
)
def test_epubcheck_accepts_export(book, tmp_path):
    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (600, 900), "navy").save(cover)
    _epub(book, tmp_path, cover=cover, side_by_side=True)
    result = subprocess.run(
        ["java", "-jar", os.environ["EPUBCHECK_JAR"], str(tmp_path / "book.epub")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
