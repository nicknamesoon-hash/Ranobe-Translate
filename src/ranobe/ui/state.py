"""Application state between the services and the screens. No Flet here.

Screens read state from AppState and call its methods; AppState notifies subscribers by
topic, and the shell re-renders what changed. Long operations (translation, key checks)
are coroutines that the UI runs as background tasks, so the window never freezes.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID

from ranobe import i18n
from ranobe.core.models import JobState, ProviderAccount, SegmentStatus, Work
from ranobe.services.importers import ImportedBook
from ranobe.services.key_pool import KeyPool
from ranobe.services.library import import_book, import_file
from ranobe.services.providers import ProviderRegistry, provider_infos
from ranobe.services.secrets import FernetStore, SecretStore
from ranobe.services.translator import (
    AccountSwitched,
    ChunkDone,
    Event,
    JobFinished,
    Translator,
    WaitingQuota,
)
from ranobe.storage.repositories import Repositories
from ranobe.storage.settings import AppSettings

Listener = Callable[[str], None]


class Topic:
    WORKS = "works"
    ACCOUNTS = "accounts"
    SETTINGS = "settings"
    PROGRESS = "progress"


@dataclass
class WorkSummary:
    work: Work
    done: int
    total: int
    needs_review: int

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0


@dataclass
class Progress:
    """What the translate screen shows while a job runs."""

    work_id: UUID
    state: JobState = JobState.RUNNING
    done: int = 0
    total: int = 0
    needs_review: int = 0
    account: str = ""
    preview: str = ""
    resume_at: datetime | None = None
    error: str | None = None
    switches: list[str] = field(default_factory=list)  # recent account switches, newest last
    started: float = field(default_factory=time.monotonic)
    done_at_start: int | None = None

    def eta_seconds(self, now: float | None = None) -> float | None:
        """Remaining time from the speed of this run; None until there is a speed."""
        if self.done_at_start is None or self.done <= self.done_at_start:
            return None
        elapsed = (now if now is not None else time.monotonic()) - self.started
        speed = (self.done - self.done_at_start) / elapsed if elapsed > 0 else 0
        return (self.total - self.done) / speed if speed else None


@dataclass
class KeyCheck:
    account_id: str
    ok: bool
    detail: str


class AppState:
    def __init__(
        self,
        repos: Repositories,
        settings: AppSettings,
        settings_path: Path,
        secrets: SecretStore,
        registry: ProviderRegistry | None = None,
    ):
        self.repos = repos
        self.settings = settings
        self.settings_path = settings_path
        self.secrets = secrets
        self.registry = registry or ProviderRegistry()
        self.progress: Progress | None = None
        self.key_checks: dict[str, KeyCheck] = {}
        self._task: asyncio.Task | None = None
        self._listeners: list[Listener] = []
        i18n.set_locale(settings.ui_locale)

    # --- subscriptions ---

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def notify(self, topic: str) -> None:
        for listener in list(self._listeners):
            listener(topic)

    # --- master password (only for the encrypted-file store) ---

    @property
    def needs_master_password(self) -> bool:
        return isinstance(self.secrets, FernetStore) and not self.secrets.unlocked

    @property
    def master_password_is_new(self) -> bool:
        return isinstance(self.secrets, FernetStore) and not self.secrets.initialized

    def unlock(self, password: str, remember: bool) -> None:
        """Raises WrongPassword."""
        if isinstance(self.secrets, FernetStore):
            self.secrets.unlock(password, remember=remember)
            self.notify(Topic.ACCOUNTS)

    # --- settings ---

    def update_settings(self, **changes: object) -> None:
        for name, value in changes.items():
            if not hasattr(self.settings, name):
                raise AttributeError(name)
            setattr(self.settings, name, value)
        self.settings.save(self.settings_path)
        if "ui_locale" in changes:
            i18n.set_locale(self.settings.ui_locale)
        self.notify(Topic.SETTINGS)

    # --- library ---

    def works(self, query: str = "") -> list[WorkSummary]:
        needle = query.strip().casefold()
        result = []
        for w in self.repos.works.list():
            haystack = " ".join(filter(None, [w.title, w.original_title, w.author])).casefold()
            if needle and needle not in haystack:
                continue
            ids = [c.id for c in self.repos.chapters.for_work(w.id)]
            counts = self.repos.segments.count_by_status(ids)
            total = sum(counts.values())
            done = total - counts[SegmentStatus.PENDING]
            result.append(WorkSummary(w, done, total, counts[SegmentStatus.NEEDS_REVIEW]))
        return result

    def import_path(self, path: Path, source_lang: str, target_lang: str) -> Work:
        """Raises ImportFailed / UnsupportedFormat / OSError."""
        work = import_file(self.repos, path, source_lang, target_lang)
        self.notify(Topic.WORKS)
        return work

    def import_book(self, book: ImportedBook, source_lang: str, target_lang: str) -> Work:
        work = import_book(self.repos, book, source_lang, target_lang)
        self.notify(Topic.WORKS)
        return work

    # --- accounts ---

    def accounts(self) -> list[ProviderAccount]:
        return self.repos.accounts.list()

    def add_account(
        self, provider_id: str, label: str, key: str, model: str = "", rpm: float = 5.0,
        priority: int = 100,
    ) -> ProviderAccount:  # fmt: skip
        infos = {p.id: p for p in provider_infos()}
        if provider_id not in infos:
            raise ValueError(f"unknown provider {provider_id}")
        if not key.strip() or not label.strip():
            raise ValueError("label and key are required")
        account = ProviderAccount(
            provider_id=provider_id,
            label=label.strip(),
            model=model.strip() or infos[provider_id].default_model,
            rpm=rpm,
            priority=priority,
        )
        self.secrets.set(account.secret_ref, key.strip())
        self.repos.accounts.save(account)
        self.notify(Topic.ACCOUNTS)
        return account

    def remove_account(self, account_id: str) -> None:
        account = next((a for a in self.accounts() if a.id == account_id), None)
        if account:
            self.secrets.delete(account.secret_ref)
            self.repos.accounts.delete(account.id)
            self.key_checks.pop(account.id, None)
            self.notify(Topic.ACCOUNTS)

    def set_account_enabled(self, account_id: str, enabled: bool) -> None:
        for a in self.accounts():
            if a.id == account_id:
                a.enabled = enabled
                if enabled:
                    a.cooldown_until = a.exhausted_until = None
                self.repos.accounts.save(a)
        self.notify(Topic.ACCOUNTS)

    async def check_keys(self) -> None:
        """Ask every provider for its model list with the stored key."""
        for a in self.accounts():
            key = self.secrets.get(a.secret_ref)
            if not key:
                self.key_checks[a.id] = KeyCheck(a.id, False, "no_key")
            else:
                try:
                    models = await self.registry.get(a.provider_id).list_models(key)
                    ok = a.model in models
                    self.key_checks[a.id] = KeyCheck(a.id, ok, "ok" if ok else "model_missing")
                except Exception as e:  # any failure is shown next to the account
                    self.key_checks[a.id] = KeyCheck(a.id, False, type(e).__name__)
            self.notify(Topic.ACCOUNTS)

    # --- translation ---

    @property
    def translating(self) -> bool:
        return self._task is not None and not self._task.done()

    async def translate(self, work_id: UUID, chapter_ids: list[UUID] | None = None) -> None:
        """Run (or resume) translation of a work until done, paused or out of quota."""
        work = self.repos.works.get(work_id)
        if work is None:
            raise KeyError(work_id)
        pool = KeyPool(self.repos.accounts, self.secrets)
        translator = Translator(self.repos, self.registry, pool, on_event=self._on_event)
        job = self.repos.jobs.latest_for_work(work.id)
        if job is None or job.state is JobState.DONE or chapter_ids:
            job = translator.create_job(work, chapter_ids)
        done, total, flagged = translator.progress(job)
        self.progress = Progress(work.id, done=done, total=total, needs_review=flagged)
        self.progress.done_at_start = done
        self.notify(Topic.PROGRESS)
        self._task = asyncio.current_task()
        try:
            await translator.run(job.id)
        except asyncio.CancelledError:
            self.progress.state = JobState.PAUSED
            self.notify(Topic.PROGRESS)
        finally:
            self._task = None
            self.notify(Topic.WORKS)

    def stop(self) -> None:
        """Pause the running translation; it resumes from the first untranslated segment."""
        if self._task is not None:
            self._task.cancel()

    def _on_event(self, event: Event) -> None:
        p = self.progress
        if p is None:
            return
        if isinstance(event, ChunkDone):
            p.done, p.total, p.needs_review = event.translated, event.total, event.needs_review
            p.account, p.preview = event.account, event.preview
        elif isinstance(event, AccountSwitched):
            p.switches = [*p.switches[-4:], f"{event.account}: {event.reason}"]
        elif isinstance(event, WaitingQuota):
            p.state, p.resume_at = JobState.WAITING_QUOTA, event.resume_at
        elif isinstance(event, JobFinished):
            p.state, p.error = event.state, event.error
        self.notify(Topic.PROGRESS)

    async def aclose(self) -> None:
        self.stop()
        await self.registry.aclose()
