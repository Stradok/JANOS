"""Single source of configuration for JANOS.

Text-only, local-only, one model. Values can be overridden by janos.yaml
sitting next to this package, or by JANOS_* environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _env(key: str, default: Any) -> Any:
    """Read JANOS_<KEY>, coercing to the type of `default`."""
    raw = os.environ.get(f"JANOS_{key.upper()}")
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    return raw


@dataclass
class Config:
    # --- LLM: exactly one model for the whole system ---
    model: str = "qwen2.5:7b-instruct"
    ollama_url: str = "http://localhost:11434"
    timeout: int = 180
    num_ctx: int = 8192
    # Low temperature: this system depends on the model emitting valid,
    # decisive JSON far more than it depends on creative variety.
    temperature: float = 0.15

    # --- Supervisor behaviour ---
    max_steps: int = 8          # plan steps the supervisor will run
    max_heal_attempts: int = 2  # self-heal retries after a failed verification
    agent_max_turns: int = 6    # tool-loop turns inside a single agent
    min_pass_score: float = 0.6 # verification score needed to accept a result

    # --- Memory / learning ---
    memory_dir: Path = field(default_factory=lambda: ROOT / "memory")
    recall_k: int = 4           # episodes injected as context
    lesson_k: int = 4           # lessons injected as context
    learn: bool = True          # distil lessons from episodes

    # --- Tools ---
    allow_shell: bool = True
    shell_timeout: int = 30
    workspace: Path = field(default_factory=lambda: ROOT / "workspace")

    # Brave Search API key. Never read from janos.yaml (which gets committed):
    # set BRAVE_API_KEY / JANOS_BRAVE_API_KEY, or put it in jarvis-core/.brave_key.
    brave_api_key: str = ""

    def __post_init__(self) -> None:
        for f in ("model", "ollama_url"):
            setattr(self, f, _env(f, getattr(self, f)))
        for f in ("timeout", "num_ctx", "max_steps", "max_heal_attempts",
                  "agent_max_turns", "recall_k", "lesson_k", "shell_timeout"):
            setattr(self, f, _env(f, getattr(self, f)))
        for f in ("temperature", "min_pass_score"):
            setattr(self, f, _env(f, getattr(self, f)))
        for f in ("learn", "allow_shell"):
            setattr(self, f, _env(f, getattr(self, f)))

        key = os.environ.get("JANOS_BRAVE_API_KEY") or os.environ.get("BRAVE_API_KEY") or ""
        if not key and (ROOT / ".brave_key").exists():
            try:
                key = (ROOT / ".brave_key").read_text().strip()
            except OSError:
                key = ""
        self.brave_api_key = key

        self.memory_dir = Path(_env("memory_dir", self.memory_dir))
        self.workspace = Path(_env("workspace", self.workspace))
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        return self.memory_dir / "janos.db"

    @classmethod
    def load(cls) -> Config:
        """Load janos.yaml if present, else defaults. Env always wins."""
        cfg_file = ROOT / "janos.yaml"
        data: dict[str, Any] = {}
        if cfg_file.exists():
            try:
                import yaml

                data = yaml.safe_load(cfg_file.read_text()) or {}
            except Exception:
                data = {}
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["memory_dir"] = str(self.memory_dir)
        d["workspace"] = str(self.workspace)
        d["brave_api_key"] = "set" if self.brave_api_key else ""
        return d
