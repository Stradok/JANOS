import os
import yaml
from pathlib import Path
from typing import Any


class Config:
    _instance = None

    def __new__(cls, path: str | None = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, path: str | None = None):
        if self._initialized:
            return
        self._initialized = True
        self.base = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = path or str(self.base / "config.yaml")
        with open(path) as f:
            self.data: dict[str, Any] = yaml.safe_load(f)

    @property
    def ollama(self) -> dict[str, Any]:
        return {
            "url": self.data.get("ollama", {}).get("url", "http://localhost:11434"),
            "model": self.data.get("ollama", {}).get("model", "llama3.1:8b"),
            "timeout": self.data.get("ollama", {}).get("timeout", 120),
        }

    @property
    def models(self) -> dict[str, Any]:
        return self.data.get("models", {})

    @property
    def router_model(self) -> str:
        return self.models.get("router", "gemma4:12b")

    @property
    def coder_model(self) -> str:
        return self.models.get("coder", "pleasecech/qwen3.6-plus:latest")

    @property
    def features(self) -> dict[str, bool]:
        return self.data.get("features", {})

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        val = self.data
        for k in keys:
            val = val.get(k)
            if val is None:
                return default
        return val
