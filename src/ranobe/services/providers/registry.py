"""Provider registry. Adding a provider = one class decorated with @register_provider."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from ranobe.services.providers.base import LLMProvider, ProviderInfo

_REGISTRY: dict[str, type] = {}


def register_provider[T](cls: type[T]) -> type[T]:
    info: ProviderInfo = cls.info  # type: ignore[attr-defined]
    _REGISTRY[info.id] = cls
    return cls


def provider_infos() -> list[ProviderInfo]:
    return [cls.info for cls in _REGISTRY.values()]  # type: ignore[attr-defined]


class ProviderRegistry:
    """Creates provider instances that share one HTTP client."""

    def __init__(self, client_factory: Callable[[], httpx.AsyncClient] | None = None):
        self._client = (client_factory or _default_client)()
        self._instances: dict[str, LLMProvider] = {}

    def get(self, provider_id: str) -> LLMProvider:
        if provider_id not in self._instances:
            cls = _REGISTRY.get(provider_id)
            if cls is None:
                raise KeyError(f"unknown provider: {provider_id}")
            self._instances[provider_id] = cls(self._client)
        return self._instances[provider_id]

    async def aclose(self) -> None:
        await self._client.aclose()


def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0))
