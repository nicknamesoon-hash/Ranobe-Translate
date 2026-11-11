import zipfile

import pytest

from ranobe.core.models import SegmentKind, SegmentStatus
from ranobe.services.importers import ImportFailed, UnsupportedFormat, importer_for
from ranobe.services.importers.text import decode_bytes
from ranobe.services.library import import_file

JA = "山田太郎は剣を抜いた。彼は静かに笑った。\n「行くぞ」\n彼女は頷いた。"
KO = "그는 검을 뽑았다. 그리고 조용히 웃었다.\n「가자」\n그녀는 고개를 끄덕였다."


@pytest.mark.parametrize(
    ("text", "encoding", "lang"),
    [
        (JA, "utf-8", None),
        (JA, "utf-8-sig", None),
        (JA, "utf-16", None),
        (JA, "shift_jis", "ja"),
        (JA, "euc_jp", "ja"),
        (KO, "euc-kr", "ko"),
        (KO, "cp949", None),
        ("Привіт, як справи? Усе добре, дякую. " * 5, "cp1251", None),
        ("He drew his sword and smiled.", "ascii", "en"),
    ],
)
def test_decode_bytes(text, encoding, lang):
    assert decode_bytes(text.encode(encoding), lang) == text


def test_txt_import_splits_chapters_on_headings(tmp_path):
    p = tmp_path / "novel.txt"
    p.write_text(
        "前書き。\n第1章 出会い\n本文一。\n本文二。\n第2章 別れ\n本文三。", encoding="utf-8"
    )
    book = importer_for(p).read(p)
    assert [c.title for c in book.chapters] == ["novel", "第1章 出会い", "第2章 別れ"]
    assert book.chapters[1].blocks[0].kind is SegmentKind.HEADING
    assert [b.text for b in book.chapters[1].blocks[1:]] == ["本文一。", "本文二。"]


def _make_epub(path, spine_order, docs, title="テスト", nav=True):
    manifest = "".join(
        f'<item id="{i}" href="text/{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in sorted(docs)  # manifest order differs from spine order on purpose
    )
    if nav:
        manifest += (
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
    spine = "".join(f'<itemref idref="{i}"/>' for i in spine_order)
    opf = f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title><dc:creator>作者</dc:creator><dc:language>ja</dc:language>
  </metadata>
  <manifest>{manifest}</manifest>
  <spine>{'<itemref idref="nav"/>' if nav else ""}{spine}</spine>
</package>"""
    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", "<html><body><nav>目次</nav></body></html>")
        for name, body in docs.items():
            zf.writestr(f"OEBPS/text/{name}.xhtml", f"<html><body>{body}</body></html>")


def test_epub_follows_spine_and_keeps_paragraphs(tmp_path):
    p = tmp_path / "book.epub"
    _make_epub(
        p,
        spine_order=["c_cover", "z_ch1", "a_ch2"],
        docs={
            "c_cover": '<div><img src="cover.jpg"/></div>',
            "z_ch1": "<h1>第一章</h1><p><ruby>剣<rt>けん</rt></ruby>を抜いた。</p><p>二段落目。</p>",
            "a_ch2": "<h2>第二章</h2><p>行1<br/>行2</p><hr/><p>終わり。</p>",
        },
    )
    book = importer_for(p).read(p)
    assert book.title == "テスト" and book.author == "作者" and book.language == "ja"
    assert [c.title for c in book.chapters] == ["第一章", "第二章"]
    assert [(b.kind, b.text) for b in book.chapters[0].blocks] == [
        (SegmentKind.HEADING, "第一章"),
        (SegmentKind.PARAGRAPH, "剣を抜いた。"),  # furigana dropped
        (SegmentKind.PARAGRAPH, "二段落目。"),
    ]
    assert [b.text for b in book.chapters[1].blocks] == [
        "第二章",
        "行1",
        "行2",
        "* * *",
        "終わり。",
    ]


def test_invalid_epub(tmp_path):
    p = tmp_path / "bad.epub"
    p.write_bytes(b"not a zip")
    with pytest.raises(ImportFailed):
        importer_for(p).read(p)


def test_cbz_reads_text_files_in_natural_order(tmp_path):
    p = tmp_path / "pages.cbz"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("10.txt", "十。")
        zf.writestr("2.txt", "二。")
        zf.writestr("1.jpg", b"\xff\xd8")
        zf.writestr("3.html", "<p>三。</p>")
    book = importer_for(p).read(p)
    assert [c.blocks[0].text for c in book.chapters] == ["二。", "三。", "十。"]


def test_cbz_images_only(tmp_path):
    p = tmp_path / "img.cbz"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("1.jpg", b"\xff\xd8")
    with pytest.raises(ImportFailed):
        importer_for(p).read(p)


def test_unsupported_extension(tmp_path):
    with pytest.raises(UnsupportedFormat):
        importer_for(tmp_path / "x.pdf")


def test_import_file_creates_pending_segments(repos, tmp_path):
    p = tmp_path / "n.txt"
    p.write_text("第1章\n一。\n二。", encoding="utf-8")
    work = import_file(repos, p, "ja", "uk")
    chapters = repos.chapters.for_work(work.id)
    segs = repos.segments.for_chapter(chapters[0].id)
    assert [s.source for s in segs] == ["第1章", "一。", "二。"]
    assert all(s.status is SegmentStatus.PENDING for s in segs)
