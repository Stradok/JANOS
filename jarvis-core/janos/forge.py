"""Self-extension: JANOS writing its own tools.

When the system hits something it has no tool for, it can author one. The
generated module is validated before it is ever imported into the running
process:

  1. it must parse, and expose DESCRIPTION, PARAMS and an async run()
  2. an AST scan rejects the genuinely dangerous constructs
  3. it is smoke-tested in a separate interpreter with a timeout
  4. only then is it written to janos/generated/ and registered live

Anything that fails a stage is discarded with the reason fed back to the
model, which gets a bounded number of attempts to repair it.

Generated tools persist across restarts and are reloaded at startup.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from janos import sandbox
from janos.config import Config
from janos.llm import LLM, LLMError
from janos.tools import Tool, Toolbox

GENERATED = Path(__file__).resolve().parent / "generated"

# Code is requested as plain fenced text, never as a JSON string field.
# A grammar-constrained JSON value has to escape every newline and quote in the
# source, and a 7B model reliably returns an empty string when asked to do that.
TEMPLATE = '''```python
"""One-line summary of what this tool does."""

NAME = "currency_convert"
DESCRIPTION = "What the tool does, phrased for another agent to read."
PARAMS = {"amount": "float=1", "from_currency": "str='USD'", "to_currency": "str='EUR'"}


async def run(amount: float = 1, from_currency: str = "USD", to_currency: str = "EUR") -> str:
    """Return a string. Never raise — describe failures in the return value."""
    import httpx
    try:
        # follow_redirects=True is required: httpx does NOT follow them by default
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            r = await c.get("https://api.example.com/rate")
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return f"Lookup failed: {e}"
    return f"{amount} {from_currency} = ... {to_currency}"
```'''

# Constructs that are never acceptable in generated code. Networking, file IO
# and subprocesses are deliberately allowed: those are what tools are for.
_BANNED_CALLS = {
    "eval", "exec", "compile", "__import__", "breakpoint", "globals", "locals",
    "setattr", "delattr", "vars",
}
_BANNED_MODULES = {"ctypes", "pickle", "marshal", "shelve", "dill", "cffi"}
_BANNED_ATTRS = {"rmtree", "remove", "unlink", "rmdir", "removedirs", "truncate",
                 "chmod", "chown", "kill", "killpg", "_exit", "fork", "setuid",
                 # Writing from a generated tool resolves against the CWD.
                 "write_text", "write_bytes", "writelines"}


@dataclass
class ForgeResult:
    ok: bool
    name: str = ""
    reason: str = ""
    path: str = ""
    smoke_output: str = ""


def _scan(code: str) -> tuple[bool, str]:
    """Static checks. Returns (ok, reason)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"syntax error line {e.lineno}: {e.msg}"

    has_run = has_desc = has_params = False
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run":
            has_run = True
            if any(a.arg for a in node.args.args) and len(node.args.defaults) < len(node.args.args):
                return False, "every parameter of run() needs a default value"
        elif isinstance(node, ast.FunctionDef) and node.name == "run":
            return False, "run() must be declared `async def`"
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "DESCRIPTION":
                    has_desc = True
                elif isinstance(t, ast.Name) and t.id == "PARAMS":
                    has_params = True

    if not has_run:
        return False, "no `async def run(...)` at module level"
    if not has_desc:
        return False, "missing module-level DESCRIPTION string"
    if not has_params:
        return False, "missing module-level PARAMS dict"

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _BANNED_CALLS:
                return False, f"forbidden call: {node.func.id}()"
            # A generated tool writing a file resolves the path against the
            # process CWD, not the workspace, so it silently litters the repo.
            # Tools return content; write_file persists it.
            if node.func.id == "open":
                mode = ""
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)
                if any(m in mode for m in ("w", "a", "x", "+")):
                    return False, ("this tool must not write files — return the content "
                                   "as a string instead, the assistant has write_file")
        if isinstance(node, ast.Attribute) and node.attr in _BANNED_ATTRS:
            return False, f"forbidden attribute: .{node.attr}"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.search(r"(google|bing)\.[a-z.]+/search", node.value, re.I):
                return False, ("google and bing block scraping and return consent pages; "
                               "use a real JSON API instead")
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in _BANNED_MODULES:
                    return False, f"forbidden import: {a.name}"
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in _BANNED_MODULES:
                return False, f"forbidden import: {node.module}"
    return True, ""


def _parse_params(code: str) -> dict[str, str]:
    """Read the PARAMS literal without importing the module."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "PARAMS":
                    try:
                        val = ast.literal_eval(node.value)
                        if isinstance(val, dict):
                            return {str(k): str(v) for k, v in val.items()}
                    except (ValueError, SyntaxError):
                        return {}
    return {}


def _parse_name(code: str) -> str:
    """Read the module-level NAME constant without importing."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "NAME":
                    try:
                        v = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        return ""
                    v = re.sub(r"\W", "_", str(v)).strip("_").lower()
                    return v if v.isidentifier() else ""
    return ""


def _parse_description(code: str) -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "DESCRIPTION":
                    try:
                        v = ast.literal_eval(node.value)
                        return str(v)
                    except (ValueError, SyntaxError):
                        return ""
    return ""


class ToolForge:
    """Writes, validates and registers new tools at runtime."""

    def __init__(self, config: Config, llm: LLM, toolbox: Toolbox, memory: Any = None):
        self.config = config
        self.llm = llm
        self.toolbox = toolbox
        self.memory = memory
        GENERATED.mkdir(parents=True, exist_ok=True)
        (GENERATED / "__init__.py").touch(exist_ok=True)

    # ------------------------------------------------------------ loading

    def load_all(self) -> list[str]:
        """Register every previously generated tool. Called at startup."""
        loaded: list[str] = []
        for path in sorted(GENERATED.glob("*.py")):
            if path.name == "__init__.py":
                continue
            name = path.stem
            try:
                code = path.read_text(encoding="utf-8")
            except OSError:
                continue
            ok, reason = _scan(code)
            if not ok:
                continue  # a tool that no longer validates is simply not loaded
            if self._register(name, code, path):
                loaded.append(name)
        return loaded

    def _register(self, name: str, code: str, path: Path) -> bool:
        try:
            spec = importlib.util.spec_from_file_location(f"janos.generated.{name}", path)
            if spec is None or spec.loader is None:
                return False
            module = importlib.util.module_from_spec(spec)
            sys.modules[f"janos.generated.{name}"] = module
            spec.loader.exec_module(module)
            fn = getattr(module, "run", None)
            if fn is None or not asyncio.iscoroutinefunction(fn):
                return False
        except Exception:
            return False

        self.toolbox.add(Tool(
            name=name,
            description=(_parse_description(code) or f"generated tool {name}") + " [self-written]",
            params=_parse_params(code) or {},
            run=fn,
            danger=True,
        ))
        return True

    def generated_names(self) -> list[str]:
        return sorted(p.stem for p in GENERATED.glob("*.py") if p.name != "__init__.py")

    # ------------------------------------------------------------ authoring

    async def create(self, purpose: str, name_hint: str = "", attempts: int = 3) -> ForgeResult:
        """Write a new tool for `purpose`, validate it, and register it live."""
        existing = ", ".join(self.toolbox.names())
        feedback = ""

        # Look the problem up first. Left to its own recall the model picks
        # plausible-sounding endpoints that are dead, then fails the smoke test
        # repeatedly; a search grounds it in something that currently exists.
        research = await self._research(purpose)

        for attempt in range(1, attempts + 1):
            prompt = f"""Write a new Python tool module for this assistant.

WHAT IT MUST DO: {purpose}
{f'SUGGESTED NAME: {name_hint}' if name_hint else ''}

Tools that already exist (do not duplicate these): {existing}
{research}
Follow this shape exactly:

{TEMPLATE}

HARD REQUIREMENTS:
- module-level NAME (lowercase identifier), DESCRIPTION (str), and PARAMS
  (dict mapping each run() keyword to a short type hint)
- exactly one `async def run(...)`, whose keywords match PARAMS
- EVERY parameter has a default, so run() is callable with no arguments at all
- returns a STRING; on failure return a string describing the failure
- never raises, never calls input(), never loops forever
- imports go inside run(). Allowed: httpx, json, re, pathlib, datetime, math,
  asyncio, subprocess and the standard library. Use httpx for HTTP, and ALWAYS
  pass follow_redirects=True — httpx does not follow redirects on its own and
  the request will fail with a 30x otherwise.
- forbidden: eval, exec, compile, __import__, ctypes, pickle, and any call that
  deletes files or kills processes
- do NOT write, create or delete any file. Return the content as a string —
  the assistant already has a write_file tool for persisting it
- do NOT scrape google.com or bing.com; they return consent pages to
  non-browser clients. Use a real JSON API
- if you return text taken from a web page, pass it through
  html.unescape() first so entities like &amp; do not leak into the answer
- use only public APIs that need no API key
{feedback}
Output ONLY the module inside one ```python fence. No explanation."""

            try:
                raw = await self.llm.chat(
                    [{"role": "system", "content":
                      "You write small, robust, self-contained Python tool modules. "
                      "You output only code in a single fenced block."},
                     {"role": "user", "content": prompt}],
                    temperature=0.2,
                )
            except LLMError as e:
                return ForgeResult(False, reason=f"model failed: {e}")

            code = _strip_fence(raw)
            name = _parse_name(code) or re.sub(r"\W", "_", name_hint or "").strip("_").lower()
            if not name or not name.isidentifier() or name in ("run", "test"):
                name = f"tool_{abs(hash(purpose)) % 10000}"

            if name in self.toolbox.names() and name not in self.generated_names():
                feedback = f"\nThe name {name!r} is taken by a built-in tool. Choose another."
                continue

            ok, reason = _scan(code)
            if not ok:
                feedback = f"\nYour previous attempt was rejected: {reason}. Fix it."
                continue

            smoke_ok, smoke_out = await self._smoke_test(name, code)
            if not smoke_ok:
                feedback = (f"\nYour previous attempt FAILED its smoke test:\n{smoke_out[:400]}\n"
                            f"Fix it so run() succeeds when called with no arguments.")
                if re.search(r"Name or service not known|nodename nor servname|"
                             r"getaddrinfo|NameResolutionError", smoke_out, re.I):
                    feedback += ("\nThat hostname does not exist — you invented it. Use a URL "
                                 "copied verbatim from the WEB RESEARCH above, and nothing else.")
                elif re.search(r"Connection reset|ConnectTimeout|ConnectError", smoke_out, re.I):
                    feedback += ("\nThat host is unreachable. Pick a DIFFERENT provider entirely; "
                                 "do not retry the same domain.")
                elif re.search(r"Redirect response|30[178] |TooManyRedirects", smoke_out, re.I):
                    feedback += ("\nThat was a redirect. Pass follow_redirects=True to "
                                 "httpx.AsyncClient — it does not follow redirects by default.")
                elif re.search(r"KeyError|IndexError|TypeError", smoke_out, re.I):
                    feedback += ("\nThe response shape was not what you assumed. Parse defensively "
                                 "with .get() and return whatever you did receive.")
                continue

            path = GENERATED / f"{name}.py"
            path.write_text(code, encoding="utf-8")
            if not self._register(name, code, path):
                path.unlink(missing_ok=True)
                feedback = "\nThe module could not be imported. Simplify it."
                continue

            if self.memory is not None:
                try:
                    self.memory.add_lesson(
                        f"A self-written tool `{name}` exists: {_parse_description(code)[:160]}",
                        task_type="tooling", source="forge",
                    )
                except Exception:
                    pass

            return ForgeResult(True, name=name, path=str(path), smoke_output=smoke_out[:400])

        return ForgeResult(False, reason=f"gave up after {attempts} attempts. {feedback.strip()}")

    async def _research(self, purpose: str) -> str:
        """Find endpoints that actually respond right now.

        Search alone returns documentation pages, and the model then invents an
        endpoint out of the prose. So those pages are fetched, candidate URLs
        are pulled from them, and each is probed — only URLs that really answer
        are offered to the model.
        """
        if self.toolbox.get("web_search") is None:
            return ""
        try:
            found = await self.toolbox.run(
                "web_search",
                {"query": f"{purpose} free public API no key JSON endpoint example",
                 "max_results": 4},
            )
        except Exception:
            return ""
        if not found.ok or not found.output.strip():
            return ""

        candidates: list[str] = []
        for page in _urls_in(found.output)[:2]:
            try:
                body = await self.toolbox.run("web_fetch", {"url": page, "max_chars": 6000})
            except Exception:
                continue
            if body.ok:
                candidates.extend(_urls_in(body.output))

        endpoints: list[str] = []
        for u in candidates:
            u = u.rstrip(".,);'\"")
            if len(endpoints) >= 10:
                break
            if re.search(r"/(api|v\d)(/|$)|//api\.", u) and not u.endswith(
                    (".png", ".jpg", ".jpeg", ".svg", ".css", ".js")):
                if u not in endpoints:
                    endpoints.append(u)

        block = f"\nWEB RESEARCH:\n{found.output[:1200]}\n"
        working = await self._probe(endpoints)
        if working:
            block += ("\nENDPOINTS VERIFIED TO RESPOND RIGHT NOW — use one of these EXACTLY as "
                      "written and do not alter the hostname:\n"
                      + "\n".join(f"  {u}\n     returns: {s}" for u, s in working) + "\n")
        return block

    async def _probe(self, urls: list[str]) -> list[tuple[str, str]]:
        """Return those URLs that answer with JSON, and a snippet of what they sent."""
        if not urls:
            return []
        import httpx

        async def one(url: str) -> tuple[str, str] | None:
            try:
                async with httpx.AsyncClient(timeout=8, follow_redirects=True) as c:
                    r = await c.get(url, headers={"User-Agent": "Mozilla/5.0",
                                                  "Accept": "application/json"})
                if r.status_code != 200:
                    return None
                if "json" not in r.headers.get("content-type", "").lower():
                    return None
                return url, r.text[:150].replace("\n", " ")
            except Exception:
                return None

        results = await asyncio.gather(*(one(u) for u in urls), return_exceptions=True)
        return [r for r in results if isinstance(r, tuple)][:4]

    async def _smoke_test(self, name: str, code: str) -> tuple[bool, str]:
        """Import and call run() in a separate interpreter, with a timeout."""
        tmp = GENERATED / f"_candidate_{name}.py"
        tmp.write_text(code, encoding="utf-8")
        driver = (
            "import asyncio, importlib.util, sys\n"
            f"spec = importlib.util.spec_from_file_location('cand', {str(tmp)!r})\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "assert isinstance(m.DESCRIPTION, str) and m.DESCRIPTION.strip()\n"
            "assert isinstance(m.PARAMS, dict)\n"
            "r = asyncio.run(m.run())\n"
            "assert isinstance(r, str), f'run() returned {type(r).__name__}, expected str'\n"
            "print(r[:400])\n"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *sandbox.prefix(self.config, "isolated", network=True, extra_ro=(GENERATED,)),
                sys.executable, "-c", driver,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=45)
        except asyncio.TimeoutError:
            proc.kill()
            return False, "run() did not finish within 45s"
        except Exception as e:
            return False, f"could not execute: {e}"
        finally:
            tmp.unlink(missing_ok=True)

        text = out.decode("utf-8", "replace").strip()
        if proc.returncode != 0:
            return False, text

        # Returning a string is not enough — a tool whose chosen endpoint is
        # dead would pass that bar forever. The default call must produce a
        # real result, so failure-shaped output is rejected and fed back.
        if _looks_like_failure(text):
            return False, f"run() returned a failure message: {text[:200]}"
        if not text.strip():
            return False, "run() returned an empty string"
        return True, text


def _strip_fence(code: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", code, re.DOTALL)
    return (m.group(1) if m else code).strip()


_FAILURE_SHAPED = re.compile(
    r"^\s*(?:"
    # "Lookup failed:", "Request error -" — the failure word must be followed by
    # a separator, so prose like "the failure rate is 3%" is not caught.
    r"(?:\w+\s+){0,3}?(?:failed|failure|error|exception)\s*[:\-–]"
    r"|traceback\b"
    r"|(?:could not|unable to|not available|no data\b)"
    r")",
    re.IGNORECASE,
)


def _looks_like_failure(text: str) -> bool:
    """True when a tool's own output says it did not work."""
    return bool(_FAILURE_SHAPED.match(text or ""))


_URL = re.compile(r"https?://[^\s<>\"'\]\)]+")


def _urls_in(text: str) -> list[str]:
    """Distinct URLs in order of appearance."""
    return list(dict.fromkeys(_URL.findall(text or "")))
