"""LLM provider interface and registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    name: str  # product name, not translated
    default_model: str
    key_url: str
    free_tier: bool
    supports_json_mode: bool = True


@dataclass
class ChatRequest:
    model: str
    system: str
    user: str
    temperature: float = 0.3
    json_mode: bool = True
    max_output_tokens: int | None = None


@dataclass
class ChatResponse:
    text: str
    finish_reason: str | None
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(Protocol):
    info: ClassVar[ProviderInfo]

    async def chat(self, req: ChatRequest, api_key: str) -> ChatResponse:
        """Raises a classified ProviderError subclass on failure."""
        ...

    async def list_models(self, api_key: str) -> list[str]: ...


def header(headers: Mapping[str, str], name: str) -> str | None:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None
