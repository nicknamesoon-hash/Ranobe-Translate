"""Built-in providers. Default model names change often: the user can override them per
account, and `list_models` shows what the key can use."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, ClassVar

from ranobe.core.models import utcnow
from ranobe.services.providers.base import ProviderInfo
from ranobe.services.providers.openai_compat import OpenAICompatProvider
from ranobe.services.providers.registry import register_provider


@register_provider
class GeminiProvider(OpenAICompatProvider):
    info: ClassVar[ProviderInfo] = ProviderInfo(
        id="gemini",
        name="Google Gemini",
        default_model="gemini-2.5-flash",
        key_url="https://aistudio.google.com/apikey",
        free_tier=True,
    )
    base_url: ClassVar[str] = "https://generativelanguage.googleapis.com/v1beta/openai"

    def quota_reset_at(self, body: Any) -> datetime:
        # Daily quotas reset at midnight Pacific time. 08:00 UTC is midnight PST and 1 a.m.
        # PDT, so it is never too early; no tz database needed (Windows lacks one).
        now = utcnow()
        reset = now.replace(hour=8, minute=0, second=0, microsecond=0)
        return reset if reset > now else reset + timedelta(days=1)


@register_provider
class GroqProvider(OpenAICompatProvider):
    info: ClassVar[ProviderInfo] = ProviderInfo(
        id="groq",
        name="Groq",
        default_model="llama-3.3-70b-versatile",
        key_url="https://console.groq.com/keys",
        free_tier=True,
    )
    base_url: ClassVar[str] = "https://api.groq.com/openai/v1"


@register_provider
class MistralProvider(OpenAICompatProvider):
    info: ClassVar[ProviderInfo] = ProviderInfo(
        id="mistral",
        name="Mistral",
        default_model="mistral-small-latest",
        key_url="https://console.mistral.ai/api-keys",
        free_tier=True,
    )
    base_url: ClassVar[str] = "https://api.mistral.ai/v1"


@register_provider
class OpenRouterProvider(OpenAICompatProvider):
    info: ClassVar[ProviderInfo] = ProviderInfo(
        id="openrouter",
        name="OpenRouter",
        default_model="deepseek/deepseek-chat-v3-0324:free",
        key_url="https://openrouter.ai/keys",
        free_tier=True,
        supports_json_mode=False,  # depends on the routed model; the prompt asks for JSON
    )
    base_url: ClassVar[str] = "https://openrouter.ai/api/v1"

    def extra_headers(self) -> dict[str, str]:
        return {"X-Title": "Ranobe Translator"}


@register_provider
class DeepSeekProvider(OpenAICompatProvider):
    info: ClassVar[ProviderInfo] = ProviderInfo(
        id="deepseek",
        name="DeepSeek",
        default_model="deepseek-chat",
        key_url="https://platform.deepseek.com/api_keys",
        free_tier=False,
    )
    base_url: ClassVar[str] = "https://api.deepseek.com/v1"
