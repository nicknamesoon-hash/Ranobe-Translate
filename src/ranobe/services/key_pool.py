"""Pool of provider accounts with rate limiting, cooldowns and rotation across providers.

The pool only decides *which account* serves the next request. Translation context never
lives here, so switching accounts (or providers) mid-book loses nothing.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ranobe.core.errors import (
    AllAccountsUnavailable,
    AuthFailed,
    ProviderError,
    QuotaExhausted,
    RateLimited,
)
from ranobe.core.models import ProviderAccount, utcnow
from ranobe.services.secrets.base import SecretStore
from ranobe.storage.repositories import AccountRepo

log = logging.getLogger(__name__)

DEFAULT_COOLDOWN = 60.0  # seconds, when a 429 has no Retry-After
MAX_SHORT_WAIT = 120.0  # wait in place if the soonest account is back within this time


@dataclass
class Lease:
    account: ProviderAccount
    api_key: str = field(repr=False)

    @property
    def provider_id(self) -> str:
        return self.account.provider_id

    @property
    def model(self) -> str:
        return self.account.model

    @property
    def label(self) -> str:
        return f"{self.account.provider_id}/{self.account.model}"


class KeyPool:
    def __init__(
        self,
        accounts: AccountRepo,
        secrets: SecretStore,
        clock: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.accounts = accounts
        self.secrets = secrets
        self.clock = clock
        self.sleep = sleep
        self._next_slot: dict[str, datetime] = {}  # per-account RPM limiter

    def chain(self, account_ids: list[str] | None = None) -> list[ProviderAccount]:
        """Accounts in try order: the explicit chain, or all enabled accounts by priority."""
        all_accounts = {a.id: a for a in self.accounts.list()}
        if account_ids:
            ordered = [all_accounts[i] for i in account_ids if i in all_accounts]
        else:
            ordered = sorted(all_accounts.values(), key=lambda a: (a.priority, a.label))
        return [a for a in ordered if a.enabled]

    async def acquire(self, account_ids: list[str] | None = None) -> Lease:
        while True:
            now = self.clock()
            candidates: list[tuple[float, ProviderAccount, str]] = []
            blocked_until: list[datetime] = []
            for acc in self.chain(account_ids):
                until = max(
                    (t for t in (acc.cooldown_until, acc.exhausted_until) if t), default=None
                )
                if until and until > now:
                    blocked_until.append(until)
                    continue
                key = self.secrets.get(acc.secret_ref)
                if not key:
                    continue
                slot = self._next_slot.get(acc.id, now)
                candidates.append((max(0.0, (slot - now).total_seconds()), acc, key))
            if candidates:
                # Prefer an account that is free right now, in chain order; otherwise the
                # one whose rate-limit slot opens first.
                wait, acc, key = min(candidates, key=lambda c: c[0])
                ready = [c for c in candidates if c[0] == 0]
                if ready:
                    wait, acc, key = ready[0]
                if wait > 0:
                    await self.sleep(wait)
                self._next_slot[acc.id] = self.clock() + timedelta(seconds=60.0 / acc.rpm)
                return Lease(acc, key)
            if not blocked_until:
                raise AllAccountsUnavailable(None)
            soonest = min(blocked_until)
            delay = (soonest - now).total_seconds()
            if delay > MAX_SHORT_WAIT:
                raise AllAccountsUnavailable(soonest)
            await self.sleep(delay)

    def report_success(self, lease: Lease) -> None:
        acc = lease.account
        if acc.last_error or acc.cooldown_until or acc.exhausted_until:
            acc.last_error = acc.cooldown_until = acc.exhausted_until = None
            self.accounts.save(acc)

    def report_error(self, lease: Lease, err: ProviderError) -> None:
        acc = lease.account
        now = self.clock()
        acc.last_error = str(err)[:500]
        if isinstance(err, RateLimited):
            acc.cooldown_until = now + timedelta(seconds=err.retry_after or DEFAULT_COOLDOWN)
        elif isinstance(err, QuotaExhausted):
            acc.exhausted_until = err.reset_at or now + timedelta(hours=1)
        elif isinstance(err, AuthFailed):
            acc.enabled = False
        log.info("account %s: %s", lease.label, type(err).__name__)
        self.accounts.save(acc)
