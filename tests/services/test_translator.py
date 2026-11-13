import asyncio
import json
from datetime import timedelta

import pytest

from ranobe.core.errors import ContentRefused, OutputTruncated, QuotaExhausted, RateLimited
from ranobe.core.models import (
    CensorshipLevel,
    JobState,
    Note,
    NoteType,
    ProviderAccount,
    SegmentKind,
    SegmentStatus,
    utcnow,
)
from ranobe.services import translator as translator_module
from ranobe.services.importers.base import ImportedBlock, ImportedBook, ImportedChapter
from ranobe.services.key_pool import KeyPool
from ranobe.services.library import import_book
from ranobe.services.providers import ChatResponse
from ranobe.services.secrets import MemorySecretStore
from ranobe.services.translator import AccountSwitched, ChunkDone, Translator, WaitingQuota


def segments_in(user: str) -> list[dict]:
    marker = "Segments to translate:\n"
    rest = user.split(marker, 1)[1] if marker in user else user.split("Segments:\n", 1)[1]
    return json.JSONDecoder().raw_decode(rest)[0]


def echo_reply(user: str, **extra) -> ChatResponse:
    segs = segments_in(user)
    body = {"segments": [{"id": s["id"], "translation": f"UK[{s['text']}]"} for s in segs]}
    body.update(extra)
    return ChatResponse(json.dumps(body, ensure_ascii=False), "stop", 100, 50)


class FakeProvider:
    def __init__(self, script):
        self.script = script

    async def chat(self, req, api_key):
        return self.script(req, api_key)


class FakeRegistry:
    def __init__(self):
        self.calls: list[tuple[str, str, str, str]] = []  # provider, key, system, user
        self.handlers = {}

    def on(self, provider_id, handler):
        self.handlers[provider_id] = handler

    def get(self, provider_id):
        def script(req, api_key):
            self.calls.append((provider_id, api_key, req.system, req.user))
            return self.handlers[provider_id](req, api_key)

        return FakeProvider(script)


@pytest.fixture
def env(repos):
    secrets = MemorySecretStore()
    registry = FakeRegistry()
    events = []

    def add_account(provider, label, priority):
        acc = ProviderAccount(
            provider_id=provider,
            label=label,
            model=f"{provider}-model",
            priority=priority,
            rpm=6000,
        )
        repos.accounts.save(acc)
        secrets.set(acc.secret_ref, f"key-{label}")
        return acc

    async def no_sleep(_):
        return None

    def make_translator():
        pool = KeyPool(repos.accounts, secrets, sleep=no_sleep)
        return Translator(repos, registry, pool, on_event=events.append, sleep=no_sleep)

    return repos, registry, add_account, make_translator, events


def make_work(repos, n_chapters=2, per_chapter=6, preset="fast", **settings):
    chapters = [
        ImportedChapter(
            title=f"第{c + 1}章",
            blocks=[ImportedBlock(SegmentKind.HEADING, f"第{c + 1}章")]
            + [
                ImportedBlock(SegmentKind.PARAGRAPH, f"文{c}-{i}。" + "あ" * 20)
                for i in range(per_chapter)
            ]
            + [ImportedBlock(SegmentKind.SEPARATOR, "＊＊＊")],
        )
        for c in range(n_chapters)
    ]
    work = import_book(repos, ImportedBook(title="テスト", chapters=chapters), "ja", "uk")
    work.settings.quality_preset = preset
    for k, v in settings.items():
        setattr(work.settings, k, v)
    repos.works.save(work)
    return work


def all_segments(repos, work):
    return [s for ch in repos.chapters.for_work(work.id) for s in repos.segments.for_chapter(ch.id)]


def small_chunks(monkeypatch, tokens=60):
    from ranobe.core import models

    monkeypatch.setitem(
        models.QUALITY_PRESETS,
        "fast",
        models.QualityPreset("fast", 0.3, tokens, 100, two_pass=False),
    )
    monkeypatch.setitem(
        models.QUALITY_PRESETS,
        "quality",
        models.QualityPreset("quality", 0.2, tokens, 100, two_pass=True),
    )


async def test_full_translation_commits_everything(env, monkeypatch):
    small_chunks(monkeypatch)
    repos, registry, add, make, events = env
    add("gemini", "g1", 10)
    registry.on(
        "gemini",
        lambda req, key: echo_reply(
            req.user,
            notes=[
                {
                    "segment": "s1",
                    "type": "cultural",
                    "anchor": "UK",
                    "source_fragment": "文",
                    "text": "Примітка.",
                }
            ],
            disputes=[
                {
                    "segment": "s1",
                    "source_fragment": "文",
                    "issue": "?",
                    "recommended": 1,
                    "options": [{"text": "A", "rationale": "a"}, {"text": "B", "rationale": "b"}],
                }
            ],
            glossary_suggestions=[{"source": "文", "target": "текст", "kind": "term"}],
        ),
    )
    work = make_work(repos, with_summary=False)
    t = make()
    job = await t.run(t.create_job(work).id)

    assert job.state is JobState.DONE
    segs = all_segments(repos, work)
    assert all(s.status is SegmentStatus.TRANSLATED for s in segs)
    assert [s.translation for s in segs if s.kind is SegmentKind.SEPARATOR] == ["＊＊＊", "＊＊＊"]
    para = next(s for s in segs if s.kind is SegmentKind.PARAGRAPH)
    assert para.translation == f"UK[{para.source}]" and para.translated_by == "gemini/gemini-model"
    assert repos.notes.for_segment(segs[0].id)[0].text == "Примітка."
    # Every chunk explains 文 again; only the first occurrence in the work is kept.
    assert len(repos.notes.for_work(work.id)) == 1
    assert repos.disputes.unresolved_count(work.id) == job.stats.chunks_done
    assert [e.target for e in repos.glossary.for_work(work.id)] == ["текст"]
    assert job.stats.chunks_done > 2 and job.stats.input_tokens == 100 * job.stats.requests
    assert repos.works.get(work.id).translation_status.value == "done"
    assert isinstance(events[-1], translator_module.JobFinished)
    done = [e for e in events if isinstance(e, ChunkDone)]
    assert done[-1].translated == done[-1].total == len(segs)


async def test_rate_limit_switches_provider_and_keeps_context(env, monkeypatch):
    small_chunks(monkeypatch)
    repos, registry, add, make, events = env
    add("gemini", "g1", 10)
    add("groq", "q1", 20)
    state = {"gemini_calls": 0}

    def gemini(req, key):
        state["gemini_calls"] += 1
        if state["gemini_calls"] == 1:
            raise RateLimited("429", retry_after=3600)
        return echo_reply(req.user)

    registry.on("gemini", gemini)
    registry.on("groq", lambda req, key: echo_reply(req.user))
    work = make_work(repos, n_chapters=1, with_summary=False)
    t = make()
    job = await t.run(t.create_job(work).id)

    assert job.state is JobState.DONE
    failed, retried = registry.calls[0], registry.calls[1]
    assert failed[0] == "gemini" and retried[0] == "groq" and retried[1] == "key-q1"
    assert failed[2:] == retried[2:]  # identical system+user: context lives in the DB
    assert any(isinstance(e, AccountSwitched) for e in events)
    assert {s.translated_by for s in all_segments(repos, work) if s.translated_by} == {
        "groq/groq-model"
    }  # gemini stays on cooldown for an hour


async def test_cancel_then_resume_translates_each_segment_once(env, monkeypatch):
    small_chunks(monkeypatch)
    repos, registry, add, make, _ = env
    add("gemini", "g1", 10)
    state = {"n": 0}

    def flaky(req, key):
        state["n"] += 1
        if state["n"] == 3:
            raise asyncio.CancelledError  # app closed in the middle of a request
        return echo_reply(req.user)

    registry.on("gemini", flaky)
    work = make_work(repos, with_summary=False)
    t = make()
    job = t.create_job(work)
    with pytest.raises(asyncio.CancelledError):
        await t.run(job.id)
    paused = repos.jobs.get(job.id)
    assert paused.state is JobState.PAUSED
    assert paused.last_translation_tail  # context survived the crash

    registry.on("gemini", lambda req, key: echo_reply(req.user))
    resumed = await make().run(job.id)
    assert resumed.state is JobState.DONE
    sent = [s["text"] for (_, _, _, user) in registry.calls for s in segments_in(user)]
    cancelled_chunk = segments_in(registry.calls[2][3])
    for text in {
        s.source for s in all_segments(repos, work) if s.kind is not SegmentKind.SEPARATOR
    }:
        expected = 2 if text in {s["text"] for s in cancelled_chunk} else 1
        assert sent.count(text) == expected
    # the resumed request carries the tail of the last committed chunk
    assert paused.last_translation_tail.splitlines()[-1] in registry.calls[3][3]


async def test_all_quota_exhausted_pauses_job(env, monkeypatch):
    small_chunks(monkeypatch)
    repos, registry, add, make, events = env
    add("gemini", "g1", 10)
    add("groq", "q1", 20)
    reset = utcnow() + timedelta(hours=6)

    def exhausted(req, key):
        raise QuotaExhausted("daily", reset_at=reset)

    registry.on("gemini", exhausted)
    registry.on("groq", exhausted)
    work = make_work(repos, n_chapters=1)
    t = make()
    job = await t.run(t.create_job(work).id)
    assert job.state is JobState.WAITING_QUOTA
    assert abs((job.resume_after - reset).total_seconds()) < 1
    assert any(isinstance(e, WaitingQuota) for e in events)
    assert all(
        s.status is SegmentStatus.PENDING
        for s in all_segments(repos, work)
        if s.kind is not SegmentKind.SEPARATOR
    )


async def test_invalid_json_is_retried_with_feedback(env, monkeypatch):
    small_chunks(monkeypatch)
    repos, registry, add, make, _ = env
    add("gemini", "g1", 10)
    state = {"n": 0}

    def sometimes_bad(req, key):
        state["n"] += 1
        if state["n"] == 1:
            return ChatResponse("Sure! Here is the translation: ...", "stop")
        return echo_reply(req.user)

    registry.on("gemini", sometimes_bad)
    work = make_work(repos, n_chapters=1, with_summary=False)
    t = make()
    assert (await t.run(t.create_job(work).id)).state is JobState.DONE
    assert "previous reply was rejected" in registry.calls[1][3]


async def test_truncated_output_splits_chunk(env, monkeypatch):
    small_chunks(monkeypatch, tokens=500)
    repos, registry, add, make, _ = env
    add("gemini", "g1", 10)

    def limited(req, key):
        if len(segments_in(req.user)) > 2:
            raise OutputTruncated("length")
        return echo_reply(req.user)

    registry.on("gemini", limited)
    work = make_work(repos, n_chapters=1, per_chapter=6, with_summary=False)
    t = make()
    assert (await t.run(t.create_job(work).id)).state is JobState.DONE
    assert all(s.translation for s in all_segments(repos, work))


async def test_refused_segment_tries_other_provider_then_flags(env, monkeypatch):
    small_chunks(monkeypatch, tokens=1)  # one segment per chunk
    repos, registry, add, make, _ = env
    add("gemini", "g1", 10)
    add("groq", "q1", 20)

    def picky(req, key):
        if "文0-1" in req.user:
            raise ContentRefused("blocked")
        return echo_reply(req.user)

    registry.on("gemini", picky)
    registry.on("groq", picky)
    work = make_work(repos, n_chapters=1, per_chapter=3, with_summary=False)
    t = make()
    job = await t.run(t.create_job(work).id)
    assert job.state is JobState.DONE
    flagged = [s for s in all_segments(repos, work) if s.status is SegmentStatus.NEEDS_REVIEW]
    assert len(flagged) == 1 and flagged[0].review_reason == "refused"
    refused_calls = [c[0] for c in registry.calls if "文0-1" in c[3]]
    assert refused_calls == ["gemini", "groq"]


async def test_two_pass_edit_replaces_draft(env, monkeypatch):
    small_chunks(monkeypatch)
    repos, registry, add, make, _ = env
    add("gemini", "g1", 10)

    def handler(req, key):
        if req.system.startswith("You are a literary editor"):
            segs = segments_in(req.user)
            body = {
                "segments": [{"id": s["id"], "translation": s["draft"] + " (ред.)"} for s in segs],
                "changes": ["polish"],
            }
            return ChatResponse(json.dumps(body, ensure_ascii=False), "stop")
        return echo_reply(req.user)

    registry.on("gemini", handler)
    work = make_work(repos, n_chapters=1, preset="quality", with_summary=False)
    t = make()
    await t.run(t.create_job(work).id)
    para = next(s for s in all_segments(repos, work) if s.kind is SegmentKind.PARAGRAPH)
    assert para.translation.endswith("(ред.)")


async def test_plot_summary_updates(env, monkeypatch):
    small_chunks(monkeypatch)
    monkeypatch.setattr(translator_module, "SUMMARY_EVERY_CHUNKS", 2)
    repos, registry, add, make, _ = env
    add("gemini", "g1", 10)

    def handler(req, key):
        if "running plot summary" in req.system:
            return ChatResponse("Короткий зміст.", "stop")
        return echo_reply(req.user)

    registry.on("gemini", handler)
    work = make_work(repos, n_chapters=1)
    t = make()
    job = await t.run(t.create_job(work).id)
    assert job.plot_summary == "Короткий зміст."
    later = [c for c in registry.calls if "Story so far" in c[3]]
    assert later and "Короткий зміст." in later[0][3]


async def test_refusal_text_flags_segment(env, monkeypatch):
    small_chunks(monkeypatch, tokens=1)
    repos, registry, add, make, _ = env
    add("gemini", "g1", 10)

    def handler(req, key):
        segs = segments_in(req.user)
        body = {
            "segments": [
                {"id": s["id"], "translation": "I'm sorry, but I can't help with that."}
                for s in segs
            ]
        }
        return ChatResponse(json.dumps(body), "stop")

    registry.on("gemini", handler)
    work = make_work(repos, n_chapters=1, per_chapter=1, with_summary=False)
    t = make()
    await t.run(t.create_job(work).id)
    reasons = {
        s.review_reason for s in all_segments(repos, work) if s.kind is SegmentKind.PARAGRAPH
    }
    assert reasons == {"refusal"}


async def test_retranslate_segment_with_other_content_level(env, monkeypatch):
    small_chunks(monkeypatch)
    repos, registry, add, make, _ = env
    add("gemini", "g1", 10)
    level = {"family": False}

    def handler(req, key):
        family = "Content level: FAMILY" in req.system
        level["family"] |= family
        segs = segments_in(req.user)
        body = {
            "segments": [
                {"id": s["id"], "translation": ("FAM" if family else "UK") + f"[{s['text']}]",
                 "censored": family}
                for s in segs
            ],
            "notes": [{"segment": "s1", "type": "term", "anchor": "UK",
                       "source_fragment": s["text"], "text": "Модель."} for s in segs[:1]],
            "disputes": [{"segment": "s1", "source_fragment": "文", "issue": "?", "recommended": 0,
                          "options": [{"text": "A", "rationale": ""}, {"text": "B", "rationale": ""}]}],
        }  # fmt: skip
        return ChatResponse(json.dumps(body, ensure_ascii=False), "stop")

    registry.on("gemini", handler)
    work = make_work(repos, n_chapters=1, per_chapter=3, with_summary=False)
    t = make()
    await t.run(t.create_job(work).id)
    paras = [s for s in all_segments(repos, work) if s.kind is SegmentKind.PARAGRAPH]
    target, before = paras[1], paras[0]
    user_note = Note(segment_id=target.id, type=NoteType.TERM, anchor="x", source_fragment="",
                     text="Моя.", origin="user")  # fmt: skip
    repos.notes.add(user_note)
    calls_before = len(registry.calls)

    seg = await t.retranslate_segment(target.id, CensorshipLevel.FAMILY)

    assert seg.translation.startswith("FAM[") and seg.censored
    assert repos.segments.get(target.id).machine_translation == seg.translation
    assert repos.works.get(work.id).settings.censorship is CensorshipLevel.ORIGINAL
    [(_, _, _, user)] = registry.calls[calls_before:]
    assert "do NOT translate it again" in user and before.source in user
    texts = sorted(n.text for n in repos.notes.for_segment(target.id))
    assert texts == ["Модель.", "Моя."]
    assert len(repos.disputes.for_segment(target.id)) == 1


async def test_retranslate_refused_segment_is_flagged(env, monkeypatch):
    small_chunks(monkeypatch)
    repos, registry, add, make, _ = env
    add("gemini", "g1", 10)
    registry.on("gemini", lambda req, key: echo_reply(req.user))
    work = make_work(repos, n_chapters=1, per_chapter=1, with_summary=False)
    t = make()
    await t.run(t.create_job(work).id)
    para = next(s for s in all_segments(repos, work) if s.kind is SegmentKind.PARAGRAPH)

    def refuse(req, key):
        raise ContentRefused("blocked")

    registry.on("gemini", refuse)
    seg = await t.retranslate_segment(para.id, CensorshipLevel.ORIGINAL)
    assert seg.status is SegmentStatus.NEEDS_REVIEW and seg.review_reason == "refused"
    assert repos.segments.get(para.id).translation == f"UK[{para.source}]"
