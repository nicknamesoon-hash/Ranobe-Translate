"""Base class for providers with an OpenAI-compatible /chat/completions endpoint.

Uses httpx directly instead of the OpenAI SDK: the call is one POST, and we need the raw
error body to tell a per-minute limit from an exhausted daily quota.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, ClassVar

import httpx

from ranobe.core.errors import (
    AuthFailed,
    ContentRefused,
    OutputTruncated,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    Transient,
)
from ranobe.core.models import utcnow
from ranobe.core.redact import redact
from ranobe.services.providers.base import ChatRequest, ChatResponse, ProviderInfo, header

_QUOTA_WORDS = ("per day", "perday", "daily", "insufficient_quota", "quota exceeded for quota")


class OpenAICompatProvider:
    info: ClassVar[ProviderInfo]
    base_url: ClassVar[str]

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    # --- hooks for subclasses ---

    def extra_headers(self) -> dict[str, str]:
        return {}

    def quota_reset_at(self, body: Any) -> datetime:
        """When an exhausted quota is expected back. Unknown: try again in an hour."""
        return utcnow() + timedelta(hours=1)

    # --- API ---

    async def chat(self, req: ChatRequest, api_key: str) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": req.model,
            "temperature": req.temperature,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
        }
        if req.json_mode and self.info.supports_json_mode:
            payload["response_format"] = {"type": "json_object"}
        if req.max_output_tokens:
            payload["max_tokens"] = req.max_output_tokens
        try:
            resp = await self.client.post(
                self.base_url.rstrip("/") + "/chat/completions",
                json=payload,
                headers=self._headers(api_key),
            )
        except httpx.TimeoutException as e:
            raise Transient(f"{self.info.id}: timeout") from e
        except httpx.TransportError as e:
            raise Transient(f"{self.info.id}: network error: {redact(str(e), [api_key])}") from e
        if resp.status_code != 200:
            raise self.classify_error(resp.status_code, resp.text, resp.headers, api_key)
        return self._parse(resp.json())

    async def list_models(self, api_key: str) -> list[str]:
        resp = await self.client.get(
            self.base_url.rstrip("/") + "/models", headers=self._headers(api_key)
        )
        if resp.status_code != 200:
            raise self.classify_error(resp.status_code, resp.text, resp.headers, api_key)
        return sorted(m["id"] for m in resp.json().get("data", []))

    # --- helpers ---

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", **self.extra_headers()}

    def _parse(self, data: dict) -> ChatResponse:
        usage = data.get("usage") or {}
        choices = data.get("choices") or []
        if not choices:
            raise ContentRefused(f"{self.info.id}: no choices in response (blocked?)")
        choice = choices[0]
        finish = choice.get("finish_reason")
        text = ((choice.get("message") or {}).get("content") or "").strip()
        if finish in ("content_filter", "safety", "prohibited_content"):
            raise ContentRefused(f"{self.info.id}: blocked by content filter ({finish})")
        if finish == "length":
            raise OutputTruncated(f"{self.info.id}: output hit the token limit")
        if not text:
            raise ContentRefused(f"{self.info.id}: empty response")
        return ChatResponse(
            text=text,
            finish_reason=finish,
            input_tokens=usage.get("prompt_tokens") or 0,
            output_tokens=usage.get("completion_tokens") or 0,
        )

    def classify_error(
        self, status: int, body_text: str, headers: Mapping[str, str], api_key: str = ""
    ) -> ProviderError:
        body = _json_or_text(body_text)
        message = redact(_error_message(body) or body_text[:300], [api_key])
        where = f"{self.info.id} HTTP {status}: {message}"
        lowered = body_text.lower()
        if status in (401, 403) or (status == 400 and "api key" in lowered):
            return AuthFailed(where)
        if status == 404 and "model" in lowered:
            return AuthFailed(where)  # wrong model name: account is misconfigured
        if status == 402 or (status == 429 and any(w in lowered for w in _QUOTA_WORDS)):
            return QuotaExhausted(where, reset_at=self.quota_reset_at(body))
        if status == 429:
            return RateLimited(where, retry_after=_retry_after(headers, body))
        if status in (408, 409) or status >= 500:
            return Transient(where)
        if status == 400 and any(w in lowered for w in ("safety", "blocked", "policy")):
            return ContentRefused(where)
        return ProviderError(where)


def _json_or_text(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def _error_message(body: Any) -> str | None:
    if isinstance(body, list) and body:
        body = body[0]
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            return err.get("message")
        if isinstance(err, str):
            return err
    return None


def _retry_after(headers: Mapping[str, str], body: Any) -> float | None:
    value = header(headers, "retry-after")
    if value:
        try:
            return float(value)
        except ValueError:
            pass
    # Google puts it in error.details[].retryDelay, e.g. "37s"
    if isinstance(body, list) and body:
        body = body[0]
    if isinstance(body, dict):
        for detail in (body.get("error") or {}).get("details") or []:
            delay = detail.get("retryDelay") if isinstance(detail, dict) else None
            if isinstance(delay, str) and delay.endswith("s"):
                try:
                    return float(delay[:-1])
                except ValueError:
                    pass
    return None
