"""Classified provider errors. The orchestrator decides what to do by error type only."""

from __future__ import annotations

from datetime import datetime


class ProviderError(Exception):
    """Base class. Messages must never contain API keys."""


class RateLimited(ProviderError):
    """Short-term limit (RPM/TPM). The key cools down for `retry_after` seconds."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class QuotaExhausted(ProviderError):
    """Daily/monthly quota is used up. The key is unusable until `reset_at`."""

    def __init__(self, message: str, reset_at: datetime | None = None):
        super().__init__(message)
        self.reset_at = reset_at


class AuthFailed(ProviderError):
    """Invalid or revoked key. The account is disabled until the user fixes it."""


class ContentRefused(ProviderError):
    """The model refused or its safety filter blocked the content."""


class InvalidOutput(ProviderError):
    """Response is not valid JSON or does not match the expected schema."""


class OutputTruncated(InvalidOutput):
    """The model hit its output token limit (finish_reason == "length")."""


class Transient(ProviderError):
    """Network error, timeout or 5xx. Retry on the same key after a backoff."""


class AllAccountsUnavailable(Exception):
    """Every account in the chain is cooling down, exhausted or disabled."""

    def __init__(self, resume_at: datetime | None):
        super().__init__(f"all accounts unavailable until {resume_at}")
        self.resume_at = resume_at
