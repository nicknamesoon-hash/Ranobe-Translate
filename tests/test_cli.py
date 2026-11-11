import io

import httpx
import pytest
import respx

from ranobe import cli
from ranobe.services.secrets import MemorySecretStore

GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RANOBE_DATA_DIR", str(tmp_path / "data"))
    store = MemorySecretStore()
    monkeypatch.setattr(cli, "select_store", lambda *a, **k: store)
    return tmp_path, store


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def test_end_to_end_with_mocked_gemini(cli_env, capsys, monkeypatch):
    tmp_path, store = cli_env
    book = tmp_path / "book.txt"
    book.write_text("第1章 始まり\n彼は笑った。\n彼女は頷いた。", encoding="utf-8")

    monkeypatch.setattr("sys.stdin", io.StringIO("AIzaSyFAKEFAKEFAKEFAKEFAKE0000\n"))
    code, out = run(
        capsys,
        "accounts",
        "add",
        "--provider",
        "gemini",
        "--label",
        "main",
        "--key-stdin",
        "--rpm",
        "6000",
    )
    assert code == 0 and "added" in out
    assert list(store._data.values()) == ["AIzaSyFAKEFAKEFAKEFAKEFAKE0000"]

    code, out = run(capsys, "import", str(book), "--from", "ja", "--to", "uk")
    assert code == 0 and "3 segments" in out
    work_prefix = out.split()[1]

    reply = (
        '{"segments": [{"id": "s1", "translation": "Розділ 1. Початок"},'
        ' {"id": "s2", "translation": "Він засміявся."},'
        ' {"id": "s3", "translation": "Вона кивнула."}]}'
    )
    with respx.mock:
        respx.post(GEMINI).mock(
            return_value=httpx.Response(
                200, json={"choices": [{"message": {"content": reply}, "finish_reason": "stop"}]}
            )
        )
        code, out = run(capsys, "translate", work_prefix, "--no-summary")
    assert code == 0 and "job done" in out, out

    code, out = run(capsys, "status", work_prefix)
    assert "translated    3" in out

    target = tmp_path / "out.txt"
    run(capsys, "export", work_prefix, str(target), "--side-by-side")
    assert "彼は笑った。\nВін засміявся." in target.read_text(encoding="utf-8")


def test_unknown_work(cli_env, capsys):
    code, out = run(capsys, "status", "nope")
    assert code == 1 and "no single work" in out


def test_providers_listed(cli_env, capsys):
    _, out = run(capsys, "providers")
    assert "gemini" in out and "aistudio.google.com" in out
