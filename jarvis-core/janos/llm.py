"""Ollama client.

Two entry points matter:
  chat()      -> free text
  chat_json() -> a dict validated against a JSON schema

chat_json drives every control decision in the system (routing, planning,
tool calls, verification), so it leans on Ollama's structured-output support
and then still re-checks the payload itself. A model that returns malformed
JSON must never be able to wedge the supervisor.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from janos.config import Config


class LLMError(RuntimeError):
    pass


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    repairs: int = 0

    def add(self, data: dict[str, Any], elapsed: float) -> None:
        self.calls += 1
        self.prompt_tokens += int(data.get("prompt_eval_count") or 0)
        self.output_tokens += int(data.get("eval_count") or 0)
        self.seconds += elapsed

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "seconds": round(self.seconds, 2),
            "json_repairs": self.repairs,
        }


Message = dict[str, str]


@dataclass
class LLM:
    config: Config
    usage: Usage = field(default_factory=Usage)

    # ---------------------------------------------------------------- health

    async def available_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.config.ollama_url}/api/tags")
                r.raise_for_status()
                return [m.get("model") or m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            return []

    async def health(self) -> dict[str, Any]:
        models = await self.available_models()
        want = self.config.model
        # Ollama reports "qwen2.5:7b-instruct"; accept a bare-name match too.
        ready = any(m == want or m.split(":")[0] == want.split(":")[0] for m in models)
        return {
            "reachable": bool(models) or await self._ping(),
            "model": want,
            "model_ready": ready,
            "models_installed": models,
        }

    async def _ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                return (await c.get(f"{self.config.ollama_url}/api/version")).status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------ chat

    async def chat(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        fmt: Any | None = None,
        max_tokens: int | None = None,
    ) -> str:
        options: dict[str, Any] = {
            "temperature": self.config.temperature if temperature is None else temperature,
            "num_ctx": self.config.num_ctx,
        }
        if max_tokens:
            options["num_predict"] = max_tokens

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        if fmt is not None:
            payload["format"] = fmt

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as c:
                r = await c.post(f"{self.config.ollama_url}/api/chat", json=payload)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            raise LLMError(f"Ollama returned {e.response.status_code}: {body}") from e
        except httpx.ConnectError as e:
            raise LLMError(
                f"Cannot reach Ollama at {self.config.ollama_url}. Is `ollama serve` running?"
            ) from e
        except httpx.TimeoutException as e:
            raise LLMError(f"Ollama timed out after {self.config.timeout}s") from e

        self.usage.add(data, time.perf_counter() - started)
        return (data.get("message") or {}).get("content", "") or ""

    async def chat_json(
        self,
        messages: list[Message],
        schema: dict[str, Any],
        *,
        temperature: float | None = None,
        retries: int = 2,
    ) -> dict[str, Any]:
        """Chat constrained to `schema`. Always returns a dict.

        Ollama enforces the schema server-side, but a model can still emit
        prose around the object or stop mid-token, so every response is
        re-parsed here and retried with the parse error fed back.
        """
        convo = list(messages)
        last_err = ""

        for attempt in range(retries + 1):
            raw = await self.chat(convo, temperature=temperature, fmt=schema)
            parsed, err = _extract_json(raw)
            if parsed is not None:
                return parsed

            last_err = err
            self.usage.repairs += 1
            if attempt == retries:
                break
            convo = list(messages) + [
                {"role": "assistant", "content": raw[:600]},
                {
                    "role": "user",
                    "content": (
                        f"That was not valid JSON ({err}). Reply with ONE JSON object "
                        f"matching this schema and nothing else:\n{json.dumps(schema)}"
                    ),
                },
            ]

        raise LLMError(f"Model did not produce valid JSON after {retries + 1} attempts: {last_err}")


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> tuple[dict[str, Any] | None, str]:
    """Best-effort recovery of one JSON object from model output."""
    if not text or not text.strip():
        return None, "empty response"

    candidates: list[str] = [text.strip()]

    fenced = _FENCE.search(text)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())

    # Widest brace span — survives leading prose and trailing chatter.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    err = "no JSON object found"
    for cand in candidates:
        try:
            val = json.loads(cand)
        except json.JSONDecodeError as e:
            err = str(e)
            continue
        if isinstance(val, dict):
            return val, ""
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val[0], ""
        err = f"expected object, got {type(val).__name__}"

    return None, err
