import os
from pathlib import Path

from tools.base import BaseTool


class FileTool(BaseTool):
    name = "file"
    description = "Read/write/list files. Params: action (read|write|list|delete), path (str), content (str, for write)"

    async def execute(self, action: str = "list", path: str = ".", content: str = "", **kwargs) -> str:
        p = Path(path).expanduser().resolve()
        if action == "list":
            if p.is_dir():
                items = os.listdir(p)
                return "\n".join(items[:50])
            return f"Not a directory: {path}"
        elif action == "read":
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="replace")[:5000]
            return f"File not found: {path}"
        elif action == "write":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"Written to {path}"
        elif action == "delete":
            if p.exists():
                p.unlink()
                return f"Deleted {path}"
            return f"Not found: {path}"
        return f"Unknown action: {action}"
