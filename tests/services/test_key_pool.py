from datetime import UTC, datetime, timedelta

import pytest

from ranobe.core.errors import AllAccountsUnavailable, AuthFailed, QuotaExhausted, RateLimited
from ranobe.core.models import ProviderAccount
from ranobe.services.key_pool import KeyPool
from ranobe.services.secrets import MemorySecretStore


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds: float):
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def setup(repos):
    secrets = MemorySecretStore()
    clock = FakeClock()

    def add(provider, label, priority, rpm=60.0, key=True):
        acc = ProviderAccount(
            provider_id=provider, label=label, model="m", priority=priority, rpm=rpm
        )
        repos.accounts.save(acc)
        if key:
            secrets.set(acc.secret_ref, f"key-{label}")
        return acc

    pool = KeyPool(repos.accounts, secrets, clock=clock, sleep=clock.sleep)
    return pool, add, clock


async def test_priority_order_and_key(setup):
    pool, add, _ = setup
    add("groq", "b", 20)
    add("gemini", "a", 10)
    lease = await pool.acquire()
    assert lease.account.label == "a" and lease.api_key == "key-a"
    assert "key-a" not in repr(lease)


async def test_rotates_across_providers_on_rate_limit(setup):
    pool, add, _ = setup
    add("gemini", "g1", 10)
    add("groq", "q1", 20)
    lease = await pool.acquire()
    pool.report_error(lease, RateLimited("429", retry_after=30))
    nxt = await pool.acquire()
    assert nxt.account.label == "q1"


async def test_rpm_limit_prefers_free_account_without_waiting(setup):
    pool, add, clock = setup
    add("gemini", "g1", 10, rpm=6)  # one request per 10 s
    add("gemini", "g2", 20, rpm=6)
    assert (await pool.acquire()).account.label == "g1"
    assert (await pool.acquire()).account.label == "g2"
    assert clock.slept == []
    third = await pool.acquire()  # both busy: waits for the earliest slot
    assert third.account.label == "g1" and clock.slept == [10.0]


async def test_short_cooldown_waits_in_place(setup):
    pool, add, clock = setup
    add("gemini", "g1", 10)
    lease = await pool.acquire()
    pool.report_error(lease, RateLimited("429", retry_after=30))
    again = await pool.acquire()
    assert again.account.label == "g1" and clock.slept == [30.0]


async def test_all_exhausted_raises_with_resume_time(setup):
    pool, add, clock = setup
    add("gemini", "g1", 10)
    add("groq", "q1", 20)
    reset = clock.now + timedelta(hours=5)
    for _ in range(2):
        lease = await pool.acquire()
        pool.report_error(lease, QuotaExhausted("day", reset_at=reset))
    with pytest.raises(AllAccountsUnavailable) as info:
        await pool.acquire()
    assert info.value.resume_at == reset


async def test_auth_failure_disables_account(setup, repos):
    pool, add, _ = setup
    acc = add("gemini", "g1", 10)
    add("groq", "q1", 20)
    pool.report_error(await pool.acquire(), AuthFailed("401"))
    assert not next(a for a in repos.accounts.list() if a.id == acc.id).enabled
    assert (await pool.acquire()).account.label == "q1"


async def test_success_clears_error_state(setup, repos):
    pool, add, clock = setup
    add("gemini", "g1", 10)
    lease = await pool.acquire()
    pool.report_error(lease, RateLimited("429", retry_after=1))
    clock.now += timedelta(seconds=5)
    lease = await pool.acquire()
    pool.report_success(lease)
    saved = repos.accounts.list()[0]
    assert saved.cooldown_until is None and saved.last_error is None


async def test_account_without_key_is_skipped(setup):
    pool, add, _ = setup
    add("gemini", "nokey", 10, key=False)
    add("groq", "q1", 20)
    assert (await pool.acquire()).account.label == "q1"


async def test_explicit_chain_order(setup):
    pool, add, _ = setup
    a = add("gemini", "a", 10)
    b = add("groq", "b", 20)
    assert (await pool.acquire([b.id, a.id])).account.label == "b"


async def test_no_accounts(setup):
    pool, _, _ = setup
    with pytest.raises(AllAccountsUnavailable) as info:
        await pool.acquire()
    assert info.value.resume_at is None
