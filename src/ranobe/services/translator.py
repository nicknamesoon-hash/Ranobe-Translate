"""Translation job runner.

One loop: take the next pending segments, build the prompt from stored state, call a model
through the key pool, validate the reply and commit everything for the chunk in ONE
transaction. A crash or cancel at any point leaves unfinished segments pending, so `run()`
can be called again to resume exactly where it stopped.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from ranobe.core.chunker import take_chunk
from ranobe.core.errors import (
    AllAccountsUnavailable,
    AuthFailed,
    ContentRefused,
    InvalidOutput,
    OutputTruncated,
    ProviderError,
    QuotaExhausted,
    RateLimited,
)
from ranobe.core.llm_schema import TranslationResult, parse_translation
from ranobe.core.models import (
    CensorshipLevel,
    Dispute,
    DisputeOption,
    GlossaryEntry,
    JobState,
    Note,
    Segment,
    SegmentKind,
    SegmentStatus,
    TranslationJob,
    TranslationStatus,
    Work,
)
from ranobe.core.notes import first_occurrences, note_key
from ranobe.core.prompts.builder import (
    PromptChunk,
    build_edit_prompt,
    build_summary_prompt,
    build_translation_prompt,
)
from ranobe.core.refusal import review_reason
from ranobe.services.key_pool import KeyPool, Lease
from ranobe.services.providers import ChatRequest, ChatResponse, ProviderRegistry
from ranobe.storage.repositories import Repositories

log = logging.getLogger(__name__)

MAX_TRANSIENT_FAILURES = 4
SUMMARY_EVERY_CHUNKS = 8


# --- events for the UI / CLI -------------------------------------------------------------


@dataclass
class ChunkDone:
    translated: int
    total: int
    needs_review: int
    account: str
    preview: str


@dataclass
class AccountSwitched:
    account: str
    reason: str


@dataclass
class WaitingQuota:
    resume_at: datetime | None


@dataclass
class JobFinished:
    state: JobState
    error: str | None = None


Event = ChunkDone | AccountSwitched | WaitingQuota | JobFinished


class _ChunkUnresolvable(Exception):
    """A single segment could not be translated; it is flagged for manual review."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Translator:
    def __init__(
        self,
        repos: Repositories,
        providers: ProviderRegistry,
        pool: KeyPool,
        on_event: Callable[[Event], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.repos = repos
        self.providers = providers
        self.pool = pool
        self.on_event = on_event or (lambda e: None)
        self.sleep = sleep

    # --- public API ---

    def create_job(self, work: Work, chapter_ids: list[UUID] | None = None) -> TranslationJob:
        ids = chapter_ids or [c.id for c in self.repos.chapters.for_work(work.id)]
        job = TranslationJob(work_id=work.id, chapter_ids=ids)
        self.repos.jobs.save(job)
        return job

    async def run(self, job_id: UUID) -> TranslationJob:
        job = self.repos.jobs.get(job_id)
        work = self.repos.works.get(job.work_id) if job else None
        if job is None or work is None:
            raise KeyError(f"job {job_id} not found")
        job.state, job.resume_after, job.last_error = JobState.RUNNING, None, None
        self.repos.jobs.save(job)
        work.translation_status = TranslationStatus.IN_PROGRESS
        self.repos.works.save(work)
        summary_buffer: list[str] = []
        started = time.monotonic()
        try:
            while True:
                pending = self.repos.segments.pending(job.chapter_ids)
                pending = self._complete_separators(pending)
                if not pending:
                    job.state = JobState.DONE
                    work.translation_status = TranslationStatus.DONE
                    break
                chunk = PromptChunk(take_chunk(pending, work.settings.preset.chunk_tokens))
                done_chunk = await self._process_chunk(work, job, chunk)
                summary_buffer.extend(s.translation or "" for s in done_chunk.segments)
                if work.settings.with_summary and job.chunks_since_summary >= SUMMARY_EVERY_CHUNKS:
                    await self._update_summary(work, job, "\n".join(summary_buffer))
                    summary_buffer.clear()
        except AllAccountsUnavailable as e:
            job.state, job.resume_after = JobState.WAITING_QUOTA, e.resume_at
            work.translation_status = TranslationStatus.PAUSED
            self.on_event(WaitingQuota(e.resume_at))
        except asyncio.CancelledError:
            job.state = JobState.PAUSED
            work.translation_status = TranslationStatus.PAUSED
            raise
        except ProviderError as e:
            job.state, job.last_error = JobState.FAILED, str(e)
            work.translation_status = TranslationStatus.PAUSED
        finally:
            job.stats.seconds += time.monotonic() - started
            self.repos.jobs.save(job)
            self.repos.works.save(work)
            self.on_event(JobFinished(job.state, job.last_error))
        return job

    def progress(self, job: TranslationJob) -> tuple[int, int, int]:
        """(finished, total, needs_review) segments of the job."""
        counts = self.repos.segments.count_by_status(job.chapter_ids)
        total = sum(counts.values())
        return total - counts[SegmentStatus.PENDING], total, counts[SegmentStatus.NEEDS_REVIEW]

    async def retranslate_segment(
        self, segment_id: UUID, censorship: CensorshipLevel | None = None
    ) -> Segment:
        """Translate one segment again, optionally with another content level.

        The work's own settings stay unchanged. The previous paragraph and the latest plot
        summary are given as context. The segment's model notes and unresolved disputes are
        replaced by the new reply; user notes and resolved disputes are kept.
        """
        segment = self.repos.segments.get(segment_id)
        work_id = self.repos.segments.work_id_of(segment_id)
        work = self.repos.works.get(work_id) if work_id else None
        if segment is None or work is None:
            raise KeyError(f"segment {segment_id} not found")
        if censorship is not None:
            work.settings = replace(work.settings, censorship=censorship)
        context = self._context_job(work, segment)
        chunk = PromptChunk([segment])
        glossary = self.repos.glossary.for_work(work.id)
        try:
            result, lease = await self._translate(work, context, chunk, glossary)
        except _ChunkUnresolvable as e:
            self._flag(segment, e.reason)
            return segment
        if work.settings.preset.two_pass:
            result = await self._edit_pass(work, context, chunk, glossary, result)
        with self.repos.db.transaction():
            self.repos.notes.delete_model_notes(segment.id)
            self.repos.disputes.delete_unresolved(segment.id)
            self._store_result(work, chunk, result, lease)
        return segment

    def _context_job(self, work: Work, segment: Segment) -> TranslationJob:
        """An unsaved job that only carries context for a one-off request."""
        latest = self.repos.jobs.latest_for_work(work.id)
        context = TranslationJob(work_id=work.id, chapter_ids=[segment.chapter_id])
        context.plot_summary = latest.plot_summary if latest else ""
        previous = self.repos.segments.previous(segment)
        if previous and previous.translation:
            tail = work.settings.preset.tail_chars
            context.last_source_tail = previous.source[-tail:]
            context.last_translation_tail = previous.translation[-tail:]
        return context

    # --- chunk processing ---

    def _complete_separators(self, pending: list[Segment]) -> list[Segment]:
        """Scene separators need no model: copy them and drop them from the queue."""
        rest = []
        for seg in pending:
            if seg.kind is SegmentKind.SEPARATOR:
                seg.translation = seg.machine_translation = seg.source
                seg.status = SegmentStatus.TRANSLATED
                self.repos.segments.save(seg)
            else:
                rest.append(seg)
        return rest

    async def _process_chunk(
        self, work: Work, job: TranslationJob, chunk: PromptChunk
    ) -> PromptChunk:
        """Translate the chunk, or a smaller front part of it. Returns what was committed."""
        glossary = self.repos.glossary.for_work(work.id)
        try:
            result, lease = await self._translate(work, job, chunk, glossary)
        except _ChunkUnresolvable as e:
            self._flag(chunk.segments[0], e.reason)
            return PromptChunk(chunk.segments[:1])
        except _SplitNeeded as split:
            return await self._process_chunk(work, job, split.part)
        if work.settings.preset.two_pass:
            result = await self._edit_pass(work, job, chunk, glossary, result)
        self._commit(work, job, chunk, result, lease)
        return chunk

    async def _translate(
        self, work: Work, job: TranslationJob, chunk: PromptChunk, glossary: list[GlossaryEntry]
    ) -> tuple[TranslationResult, Lease]:
        system, user = build_translation_prompt(work, job, chunk, glossary)
        ids = list(chunk.ids)
        feedback = ""
        refused_by: set[str] = set()
        for attempt in range(3):
            try:
                resp, lease = await self._call(work, job, system, user + feedback, refused_by)
                return parse_translation(resp.text, ids), lease
            except OutputTruncated as e:
                self._split_or_give_up(chunk, "truncated", e)
            except ContentRefused as e:
                # Another provider may have different content rules; isolate the segment first.
                if len(chunk.segments) > 1:
                    raise _SplitNeeded(chunk) from e
                refused_by.add(e.provider_id)
                chain = self.pool.chain(work.settings.account_chain or None)
                if not any(a.provider_id not in refused_by for a in chain):
                    raise _ChunkUnresolvable("refused") from e
            except InvalidOutput as e:
                if attempt == 0:
                    feedback = (
                        f"\n\nYour previous reply was rejected: {e}. Reply again with ONE valid "
                        f"JSON object containing every segment id exactly once."
                    )
                    continue
                self._split_or_give_up(chunk, "invalid_output", e)
        raise _ChunkUnresolvable("refused" if refused_by else "invalid_output")

    def _split_or_give_up(self, chunk: PromptChunk, reason: str, cause: Exception) -> None:
        if len(chunk.segments) > 1:
            raise _SplitNeeded(chunk) from cause
        raise _ChunkUnresolvable(reason) from cause

    async def _call(
        self,
        work: Work,
        job: TranslationJob,
        system: str,
        user: str,
        exclude_providers: set[str] | None = None,
        json_mode: bool = True,
    ) -> tuple[ChatResponse, Lease]:
        """One request with account rotation. Rate/quota/auth errors switch the account and
        retry the SAME request; transient errors back off and retry."""
        failures = 0
        while True:
            lease = await self.pool.acquire(
                work.settings.account_chain or None, frozenset(exclude_providers or ())
            )
            req = ChatRequest(
                model=lease.model,
                system=system,
                user=user,
                temperature=work.settings.preset.temperature,
                json_mode=json_mode,
            )
            try:
                resp = await self.providers.get(lease.provider_id).chat(req, lease.api_key)
            except (RateLimited, QuotaExhausted, AuthFailed) as e:
                self.pool.report_error(lease, e)
                self.on_event(AccountSwitched(lease.label, type(e).__name__))
                continue
            except ContentRefused as e:
                e.provider_id = lease.provider_id
                job.stats.requests += 1
                raise
            except InvalidOutput:
                job.stats.requests += 1
                raise
            except ProviderError as e:  # Transient and unclassified errors
                failures += 1
                log.warning("request failed on %s: %s", lease.label, e)
                if failures >= MAX_TRANSIENT_FAILURES:
                    raise
                await self.sleep(min(30.0, 2.0**failures))
                continue
            self.pool.report_success(lease)
            job.stats.requests += 1
            job.stats.input_tokens += resp.input_tokens
            job.stats.output_tokens += resp.output_tokens
            return resp, lease

    async def _edit_pass(
        self,
        work: Work,
        job: TranslationJob,
        chunk: PromptChunk,
        glossary: list[GlossaryEntry],
        draft: TranslationResult,
    ) -> TranslationResult:
        """Second pass. Any failure keeps the first-pass draft: editing is an improvement,
        never a reason to lose a translation."""
        for local_id, seg in zip(chunk.ids, chunk.segments, strict=True):
            seg.translation = draft.segments[local_id].translation
        system, user = build_edit_prompt(work, chunk, glossary)
        try:
            resp, _ = await self._call(work, job, system, user)
            edited = parse_translation(resp.text, list(chunk.ids))
        except (InvalidOutput, ContentRefused) as e:
            log.info("edit pass skipped: %s", e)
            return draft
        for local_id, seg_result in edited.segments.items():
            draft.segments[local_id].translation = seg_result.translation
            # Softened by either pass means softened: the flag is never cleared by the editor.
            draft.segments[local_id].censored |= seg_result.censored
        draft.changes = edited.changes
        return draft

    async def _update_summary(self, work: Work, job: TranslationJob, recent: str) -> None:
        system, user = build_summary_prompt(work, job.plot_summary, recent)
        try:
            resp, _ = await self._call(work, job, system, user, json_mode=False)
        except (InvalidOutput, ContentRefused) as e:
            log.info("summary update skipped: %s", e)
            return
        job.plot_summary = resp.text.strip()
        job.chunks_since_summary = 0
        self.repos.jobs.save(job)

    # --- persistence ---

    def _flag(self, seg: Segment, reason: str) -> None:
        seg.status, seg.review_reason = SegmentStatus.NEEDS_REVIEW, reason
        self.repos.segments.save(seg)

    def _commit(
        self,
        work: Work,
        job: TranslationJob,
        chunk: PromptChunk,
        result: TranslationResult,
        lease: Lease,
    ) -> None:
        with self.repos.db.transaction():
            needs_review = self._store_result(work, chunk, result, lease)
            tail = work.settings.preset.tail_chars
            job.last_source_tail = chunk.source_text[-tail:]
            job.last_translation_tail = "\n".join(s.translation or "" for s in chunk.segments)[
                -tail:
            ]
            job.chunks_since_summary += 1
            job.stats.chunks_done += 1
            self.repos.jobs.save(job)
        done, total, flagged = self.progress(job)
        self.on_event(
            ChunkDone(
                done, total, flagged, lease.label, (chunk.segments[0].translation or "")[:200]
            )
        )
        if needs_review:
            log.info("%d segment(s) flagged for review", needs_review)

    def _store_result(
        self, work: Work, chunk: PromptChunk, result: TranslationResult, lease: Lease
    ) -> int:
        """Write translations, notes, disputes and glossary suggestions of one reply.
        Must run inside a transaction. Returns how many segments need review."""
        by_local = dict(zip(chunk.ids, chunk.segments, strict=True))
        needs_review = 0
        for local_id, seg in by_local.items():
            seg_result = result.segments[local_id]
            seg.translation = seg.machine_translation = seg_result.translation
            seg.censored = seg_result.censored
            seg.translated_by = lease.label
            reason = review_reason(
                seg.source, seg_result.translation, work.source_lang, work.target_lang
            )
            seg.status = SegmentStatus.NEEDS_REVIEW if reason else SegmentStatus.TRANSLATED
            seg.review_reason = reason
            needs_review += bool(reason)
            self.repos.segments.save(seg)
        # A thing is explained once per work: drop notes the work already has.
        seen = {note_key(n.source_fragment, n.anchor) for n in self.repos.notes.for_work(work.id)}
        fresh = [n for n in result.notes if n.first_occurrence]
        for n in first_occurrences(fresh, lambda n: note_key(n.source_fragment, n.anchor), seen):
            self.repos.notes.add(
                Note(
                    segment_id=by_local[n.segment].id,
                    type=n.type,
                    anchor=n.anchor,
                    source_fragment=n.source_fragment,
                    text=n.text,
                    first_occurrence=n.first_occurrence,
                )
            )
        for d in result.disputes:
            self.repos.disputes.add(
                Dispute(
                    segment_id=by_local[d.segment].id,
                    source_fragment=d.source_fragment,
                    issue=d.issue,
                    options=[DisputeOption(t, r) for t, r in d.options],
                    recommended=d.recommended,
                    add_to_glossary=d.add_to_glossary,
                )
            )
        for g in result.glossary_suggestions:
            self.repos.glossary.add_if_missing(
                GlossaryEntry(
                    source=g.source,
                    target=g.target,
                    kind=g.kind,
                    work_id=work.id,
                    origin="llm_suggestion",
                    review="pending",
                )
            )
        return needs_review


class _SplitNeeded(Exception):
    """Retry with the front half of the chunk (the rest stays pending for the next round)."""

    def __init__(self, chunk: PromptChunk):
        super().__init__("split")
        half = max(1, len(chunk.segments) // 2)
        self.part = PromptChunk(chunk.segments[:half])
