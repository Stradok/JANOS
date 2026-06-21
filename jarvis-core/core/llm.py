import json
from typing import Any
import requests

from core.config import Config


class LLMResponse:
    def __init__(self, text: str, raw: dict[str, Any] | None = None):
        self.text = text
        self.raw = raw or {}


class LLMBackend:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        cfg = self.config.ollama
        self.base_url = cfg["url"].rstrip("/")
        self.default_model = cfg["model"]
        self.timeout = cfg["timeout"]

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        stream: bool = False,
        **kwargs,
    ) -> LLMResponse:
        model = model or self.default_model
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            **kwargs,
        }
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            text=data.get("message", {}).get("content", ""),
            raw=data,
        )

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        model = model or self.default_model
        payload = {
            "model": model,
            "prompt": prompt,
            **kwargs,
        }
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(text=data.get("response", ""), raw=data)

    def list_models(self) -> list[dict[str, Any]]:
        resp = requests.get(f"{self.base_url}/api/tags", timeout=30)
        resp.raise_for_status()
        return resp.json().get("models", [])

    def health(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except requests.ConnectionError:
            return False


class LLM(LLMBackend):
    pass
