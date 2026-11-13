import asyncio
import json

import pytest

from ranobe import i18n
from ranobe.core.models import JobState, SegmentKind
from ranobe.services.importers.base import ImportedBlock, ImportedBook, ImportedChapter
from ranobe.services.providers import ChatResponse
from ranobe.services.secrets import FernetStore, MemorySecretStore, WrongPassword
from ranobe.storage.settings import AppSettings
from ranobe.ui.state import AppState, Progress, Topic


class FakeProvider:
    def __init__(self, handler):
        self.handler = handler

    async def chat(self, req, api_key):
        return await self.handler(req)

    async def list_models(self, api_key):
        if api_key == "bad":
            raise RuntimeError("401")
        return ["gemini-2.5-flash"]


class FakeRegistry:
    def __init__(self):
        self.gate: asyncio.Event | None = None

    async def reply(self, req):
        if self.gate is not None:
            await self.gate.wait()
        marker = "Segments to translate:\n"
        segs = json.JSONDecoder().raw_decode(req.user.split(marker, 1)[1])[0]
        body = {"segments": [{"id": s["id"], "translation": f"UK[{s['text']}]"} for s in segs]}
        return ChatResponse(json.dumps(body, ensure_ascii=False), "stop", 10, 5)

    def get(self, provider_id):
        return FakeProvider(self.reply)

    async def aclose(self):
        pass


@pytest.fixture
def state(repos, tmp_path):
    s = AppState(
        repos, AppSettings(), tmp_path / "settings.json", MemorySecretStore(), FakeRegistry()
    )
    yield s
    i18n.set_locale("uk")


def _book(n=3):
    blocks = [ImportedBlock(SegmentKind.PARAGRAPH, f"文{i}。" + "あ" * 30) for i in range(n)]
    return ImportedBook("テスト", [ImportedChapter("第1章", blocks)], author="作者")


def test_notifications_and_settings_persist(state, tmp_path):
    topics = []
    state.subscribe(topics.append)
    state.update_settings(ui_locale="en", theme="dark")
    assert i18n.get_locale() == "en" and topics == [Topic.SETTINGS]
    saved = AppSettings.load(tmp_path / "settings.json")
    assert (saved.ui_locale, saved.theme) == ("en", "dark")
    with pytest.raises(AttributeError):
        state.update_settings(nope=1)


def test_library_search_and_progress(state):
    state.import_book(_book(), "ja", "uk")
    other = state.import_book(ImportedBook("Другий", [ImportedChapter("1", [])]), "en", "uk")
    assert {s.work.title for s in state.works()} == {"テスト", "Другий"}
    [found] = state.works("作者")
    assert (found.done, found.total, found.fraction) == (0, 3, 0.0)
    assert state.works("друг")[0].work.id == other.id


def test_accounts(state):
    acc = state.add_account("gemini", " main ", " key-1 ", rpm=6000)
    assert acc.model == "gemini-2.5-flash" and acc.label == "main"
    assert state.secrets.get(acc.secret_ref) == "key-1"
    with pytest.raises(ValueError):
        state.add_account("nope", "x", "k")
    with pytest.raises(ValueError):
        state.add_account("groq", "x", "  ")
    state.set_account_enabled(acc.id, False)
    assert not state.accounts()[0].enabled
    state.remove_account(acc.id)
    assert state.accounts() == [] and state.secrets.get(acc.secret_ref) is None


async def test_check_keys(state):
    good = state.add_account("gemini", "good", "key")
    bad = state.add_account("gemini", "bad", "bad")
    other_model = state.add_account("gemini", "m", "key", model="other")
    await state.check_keys()
    assert state.key_checks[good.id].ok
    assert state.key_checks[bad.id].detail == "RuntimeError"
    assert state.key_checks[other_model.id].detail == "model_missing"


async def test_translate_reports_progress(state):
    state.add_account("gemini", "main", "key", rpm=6000)
    work = state.import_book(_book(), "ja", "uk")
    topics = []
    state.subscribe(topics.append)
    await state.translate(work.id)
    p = state.progress
    assert p.state is JobState.DONE and p.done == p.total == 3
    assert p.account == "gemini/gemini-2.5-flash" and p.preview.startswith("UK[")
    assert Topic.PROGRESS in topics and topics[-1] == Topic.WORKS
    assert state.works()[0].done == 3


async def test_stop_pauses_and_resume_continues(state):
    state.add_account("gemini", "main", "key", rpm=6000)
    work = state.import_book(_book(), "ja", "uk")
    state.registry.gate = asyncio.Event()  # hold the first request
    task = asyncio.create_task(state.translate(work.id))
    while not state.translating:
        await asyncio.sleep(0)
    state.stop()
    await task
    assert state.progress.state is JobState.PAUSED and not state.translating
    state.registry.gate = None
    await state.translate(work.id)
    assert state.progress.state is JobState.DONE and state.progress.done == 3


async def test_no_accounts_means_waiting(state):
    work = state.import_book(_book(), "ja", "uk")
    await state.translate(work.id)
    assert state.progress.state is JobState.WAITING_QUOTA


def test_eta():
    p = Progress(work_id=None, done=10, total=110)
    p.done_at_start, p.started = 0, 0.0
    assert p.eta_seconds(now=20.0) == pytest.approx(200.0)
    p.done = 0
    assert p.eta_seconds(now=20.0) is None


def test_master_password_flow(repos, tmp_path):
    store = FernetStore(tmp_path / "secrets", scrypt_n=2**4)
    s = AppState(repos, AppSettings(), tmp_path / "s.json", store, FakeRegistry())
    assert s.needs_master_password and s.master_password_is_new
    s.unlock("secret", remember=False)
    assert not s.needs_master_password
    store.lock()
    with pytest.raises(WrongPassword):
        s.unlock("wrong", remember=False)
