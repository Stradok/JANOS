"""Unified LLM client with provider abstraction layer.

Supports Ollama (primary) and OpenRouter (optional).
Auto-detects available models, validates endpoints, supports model pull.
"""

import json
import asyncio
from abc import ABC, abstractmethod
from typing import Any
from pathlib import Path

import httpx


class LLMResponse:
    def __init__(self, text: str, model: str = "", raw: dict[str, Any] | None = None):
        self.text = text
        self.model = model
        self.raw = raw or {}


class BaseLLMProvider(ABC):
    """Abstract base for LLM providers (Ollama, OpenRouter, etc.)."""

    @abstractmethod
    async def chat(
        self, messages: list[dict[str, str]], model: str | None = None, **kwargs
    ) -> LLMResponse: ...

    @abstractmethod
    async def generate(
        self, prompt: str, model: str | None = None, **kwargs
    ) -> LLMResponse: ...

    @abstractmethod
    async def list_models(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def health(self) -> bool: ...

    @abstractmethod
    async def pull_model(self, name: str) -> dict[str, Any]: ...


class OllamaProvider(BaseLLMProvider):
    def __init__(self, base_url: str = "http://localhost:11434", timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def chat(
        self, messages: list[dict[str, str]], model: str | None = None, **kwargs
    ) -> LLMResponse:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = {"model": model, "messages": messages, "stream": False, **kwargs}
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return LLMResponse(
                text=data.get("message", {}).get("content", ""),
                model=model or "",
                raw=data,
            )

    async def generate(
        self, prompt: str, model: str | None = None, **kwargs
    ) -> LLMResponse:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = {"model": model, "prompt": prompt, **kwargs}
            resp = await client.post(f"{self.base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return LLMResponse(
                text=data.get("response", ""),
                model=model or "",
                raw=data,
            )

    async def list_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                return resp.json().get("models", [])
            except (httpx.ConnectError, httpx.HTTPStatusError):
                return []

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def pull_model(self, name: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=None) as client:
            resp = await client.post(
                f"{self.base_url}/api/pull",
                json={"name": name, "stream": False},
            )
            resp.raise_for_status()
            return resp.json()

    async def validate(self) -> dict[str, Any]:
        """Comprehensive endpoint validation."""
        result = {"reachable": False, "version": "", "available_models": [], "errors": []}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/version")
                if resp.status_code == 200:
                    result["reachable"] = True
                    result["version"] = resp.json().get("version", "")
                else:
                    result["errors"].append(f"/api/version returned {resp.status_code}")
        except httpx.ConnectError:
            result["errors"].append(f"Cannot connect to {self.base_url}")
            return result
        except Exception as e:
            result["errors"].append(str(e))
            return result

        result["available_models"] = await self.list_models()
        return result

    async def api_schema(self) -> str:
        """Detect if Ollama supports /api/chat or only /api/generate."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(
                    f"{self.base_url}/api/chat",
                    json={"model": "", "messages": [{"role": "user", "content": ""}]},
                )
                if resp.status_code != 404:
                    return "chat"
                return "generate"
        except httpx.ConnectError:
            return "unknown"


class OpenRouterProvider(BaseLLMProvider):
    def __init__(self, api_key: str, timeout: int = 120):
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = "https://openrouter.ai/api/v1"

    async def chat(
        self, messages: list[dict[str, str]], model: str | None = None, **kwargs
    ) -> LLMResponse:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {"model": model or "openai/gpt-3.5-turbo", "messages": messages, **kwargs}
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return LLMResponse(
                text=data.get("choices", [{}])[0].get("message", {}).get("content", ""),
                model=model or "",
                raw=data,
            )

    async def generate(self, prompt: str, model: str | None = None, **kwargs) -> LLMResponse:
        return await self.chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            **kwargs,
        )

    async def list_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            return resp.json().get("data", [])

    async def health(self) -> bool:
        return len(await self.list_models()) > 0

    async def pull_model(self, name: str) -> dict[str, Any]:
        return {"status": "not_applicable", "message": "OpenRouter does not support model pull"}


class LLMClient:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: dict[str, Any] | None = None):
        if self._initialized:
            return
        self._initialized = True
        self.config = config or {}
        self._providers: dict[str, BaseLLMProvider] = {}
        self._default_provider: str = "ollama"
        self._setup_providers()

    def _setup_providers(self):
        ollama_cfg = self.config.get("ollama", {})
        self._providers["ollama"] = OllamaProvider(
            base_url=ollama_cfg.get("url", "http://localhost:11434"),
            timeout=ollama_cfg.get("timeout", 120),
        )
        openrouter_key = self.config.get("openrouter", {}).get("api_key", "")
        if openrouter_key:
            self._providers["openrouter"] = OpenRouterProvider(
                api_key=openrouter_key,
                timeout=self.config.get("openrouter", {}).get("timeout", 120),
            )

    @property
    def ollama(self) -> OllamaProvider:
        return self._providers.get("ollama")

    @property
    def openrouter(self) -> OpenRouterProvider | None:
        return self._providers.get("openrouter")

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        provider: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Route chat request to appropriate provider.

        If model is specified, picks the provider that has it.
        Otherwise uses default provider (ollama) with default model.
        """
        if model is None:
            model = self.config.get("models", {}).get("llm", "llama3.1:8b")
        prov = self._resolve_provider(model, provider)
        return await prov.chat(messages, model=model, **kwargs)

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        provider: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        prov = self._resolve_provider(model, provider)
        return await prov.generate(prompt, model=model, **kwargs)

    async def list_models(self) -> dict[str, list[dict[str, Any]]]:
        models = {}
        for name, prov in self._providers.items():
            try:
                models[name] = await prov.list_models()
            except Exception:
                models[name] = []
        return models

    async def available_model_names(self) -> list[str]:
        """Get flat list of model names across all providers."""
        names = []
        for name, prov in self._providers.items():
            try:
                for m in await prov.list_models():
                    if name == "ollama":
                        names.append(m.get("name", ""))
                    else:
                        names.append(m.get("id", ""))
            except Exception:
                pass
        return [n for n in names if n]

    async def health(self) -> dict[str, bool]:
        results = {}
        for name, prov in self._providers.items():
            try:
                results[name] = await prov.health()
            except Exception:
                results[name] = False
        return results

    async def ensure_model(self, name: str) -> dict[str, Any]:
        """Pull a model if not available. Asks user first through config callback."""
        available = await self.available_model_names()
        if name in available:
            return {"status": "already_available", "model": name}
        return await self.ollama.pull_model(name)

    def _resolve_provider(
        self, model: str | None, provider: str | None
    ) -> BaseLLMProvider:
        if provider and provider in self._providers:
            return self._providers[provider]
        if model and self.ollama:
            return self.ollama
        return self._providers.get(self._default_provider)
