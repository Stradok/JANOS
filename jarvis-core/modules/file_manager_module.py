# modules/file_manager_module.py
import os
import sys
import subprocess
import shutil
import glob as glob_module
from pathlib import Path
from .base import ModuleBase


class FileManagerModule(ModuleBase):
    """Browse, search, create, move, copy, delete files and folders."""

    def __init__(self):
        super().__init__("file_manager")

    def _list_dir(self, path, show_hidden=False):
        try:
            p = Path(path)
            if not p.exists():
                return {"error": f"Path does not exist: {path}"}
            if not p.is_dir():
                return {"error": f"Not a directory: {path}"}
            items = []
            for item in sorted(p.iterdir()):
                if not show_hidden and item.name.startswith("."):
                    continue
                items.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                })
            return {"status": "ok", "path": str(p.resolve()), "items": items, "count": len(items)}
        except PermissionError:
            return {"error": f"Permission denied: {path}"}
        except Exception as e:
            return {"error": str(e)}

    def _read_file(self, path, max_chars=5000):
        try:
            p = Path(path)
            if not p.exists():
                return {"error": f"File not found: {path}"}
            if not p.is_file():
                return {"error": f"Not a file: {path}"}
            size = p.stat().st_size
            if size > 1_000_000:
                return {"error": f"File too large ({size} bytes). Max ~1MB for text read."}
            content = p.read_text(encoding="utf-8", errors="replace")
            truncated = len(content) > max_chars
            return {
                "status": "ok",
                "path": str(p.resolve()),
                "size": size,
                "content": content[:max_chars],
                "truncated": truncated,
            }
        except Exception as e:
            return {"error": str(e)}

    def _create_file(self, path, content=""):
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"status": "ok", "message": f"Created {path}"}
        except Exception as e:
            return {"error": str(e)}

    def _create_dir(self, path):
        try:
            p = Path(path)
            p.mkdir(parents=True, exist_ok=True)
            return {"status": "ok", "message": f"Created directory {path}"}
        except Exception as e:
            return {"error": str(e)}

    def _move(self, src, dst):
        try:
            shutil.move(src, dst)
            return {"status": "ok", "message": f"Moved {src} → {dst}"}
        except Exception as e:
            return {"error": str(e)}

    def _copy(self, src, dst):
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            return {"status": "ok", "message": f"Copied {src} → {dst}"}
        except Exception as e:
            return {"error": str(e)}

    def _delete(self, path, confirm=False):
        if not confirm:
            return {"status": "waiting_confirmation", "message": f"Are you sure you want to delete '{path}'? Send again with confirm=true"}
        try:
            p = Path(path)
            if not p.exists():
                return {"error": f"Path not found: {path}"}
            if p.is_dir():
                shutil.rmtree(path)
            else:
                p.unlink()
            return {"status": "ok", "message": f"Deleted {path}"}
        except Exception as e:
            return {"error": str(e)}

    def _search(self, directory, pattern, max_results=20):
        try:
            results = []
            search_pattern = os.path.join(directory, "**", pattern)
            for match in glob_module.iglob(search_pattern, recursive=True):
                results.append(match)
                if len(results) >= max_results:
                    break
            return {"status": "ok", "pattern": pattern, "directory": directory, "results": results, "count": len(results)}
        except Exception as e:
            return {"error": str(e)}

    def _info(self, path):
        try:
            p = Path(path)
            if not p.exists():
                return {"error": f"Path not found: {path}"}
            stat = p.stat()
            return {
                "status": "ok",
                "path": str(p.resolve()),
                "name": p.name,
                "type": "dir" if p.is_dir() else "file",
                "size": stat.st_size,
                "extension": p.suffix,
                "parent": str(p.parent),
            }
        except Exception as e:
            return {"error": str(e)}

    def _run(self, command, timeout=30):
        """Execute a shell command."""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout
            )
            return {
                "status": "ok",
                "returncode": result.returncode,
                "stdout": result.stdout[-1000:],
                "stderr": result.stderr[-500:],
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out ({timeout}s)"}
        except Exception as e:
            return {"error": f"Run error: {e}"}

    def _run_python(self, code, timeout=30):
        """Execute a Python code snippet inline."""
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=timeout
            )
            return {
                "status": "ok",
                "returncode": result.returncode,
                "stdout": result.stdout[-1000:],
                "stderr": result.stderr[-500:],
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Python execution timed out ({timeout}s)"}
        except Exception as e:
            return {"error": f"Python exec error: {e}"}

    def process(self, input_data):
        action = input_data.get("action", "list")
        path = input_data.get("path", ".")
        dst = input_data.get("destination", "")
        content = input_data.get("content", "")
        pattern = input_data.get("pattern", "*")
        confirm = input_data.get("confirm", False)

        if action == "list":
            return self._list_dir(path, input_data.get("show_hidden", False))
        elif action == "read":
            return self._read_file(path, input_data.get("max_chars", 5000))
        elif action == "create_file":
            return self._create_file(path, content)
        elif action == "create_dir":
            return self._create_dir(path)
        elif action == "move":
            return self._move(path, dst)
        elif action == "copy":
            return self._copy(path, dst)
        elif action == "delete":
            return self._delete(path, confirm)
        elif action == "search":
            return self._search(path, pattern, input_data.get("max_results", 20))
        elif action == "info":
            return self._info(path)
        elif action == "run":
            return self._run(
                input_data.get("command", ""),
                timeout=input_data.get("timeout", 30)
            )
        elif action == "run_python":
            return self._run_python(
                input_data.get("code", ""),
                timeout=input_data.get("timeout", 30)
            )
        else:
            return {"error": f"Unknown action: {action}. Use: list, read, create_file, create_dir, move, copy, delete, search, info, run, run_python"}
