"""Text-only tools that actually execute.

Each tool declares a JSON-schema-ish parameter spec that is rendered into the
agent prompt, and every call is funnelled through Toolbox.run(), which
normalises results and never raises into the agent loop — a tool failure is a
string the agent can read and react to, which is what makes self-healing work.

No optional imports: everything here uses the standard library plus httpx and
psutil, both already present.
"""

from __future__ import annotations

import ast
import asyncio
import html
import io
import ipaddress
import json
import operator
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

from janos import sandbox
from janos.config import Config

MAX_OUT = 4000  # tool results are truncated before they reach the context


def _yahoo_results(page: str, limit: int) -> list[dict]:
    """Parse Yahoo web results (Bing-backed, and served to plain HTTP clients)."""
    from urllib.parse import unquote
    out: list[dict] = []
    for block in page.split('<div class="dd algo')[1:]:
        m = re.search(r'href="https://r\.search\.yahoo\.com/[^"]*?/RU=([^/"]+)/RK', block)
        t = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        if not m or not t:
            continue
        sn = re.search(r'class="compText[^"]*"[^>]*>\s*<p[^>]*>(.*?)</p>', block, re.S)
        strip = lambda x: html.unescape(re.sub(r"<[^>]+>", "", x)).strip()
        out.append({"title": strip(t.group(1)), "url": unquote(m.group(1)),
                    "snippet": strip(sn.group(1)) if sn else ""})
        if len(out) >= limit:
            break
    return out


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, str]
    run: Callable[..., Awaitable[str]]
    danger: bool = False

    def signature(self) -> str:
        args = ", ".join(f"{k}: {v}" for k, v in self.params.items()) or "no arguments"
        return f"{self.name}({args}) — {self.description}"


@dataclass
class ToolResult:
    tool: str
    args: dict[str, Any]
    output: str
    ok: bool
    ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": self.args, "ok": self.ok,
                "output": self.output[:800], "ms": self.ms}


# --------------------------------------------------------------------- HTML

class _TextExtractor(HTMLParser):
    """Collapse an HTML page into readable text."""

    _SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._SKIP:
            self._depth += 1
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._depth:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._depth and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        out = " ".join(self.parts)
        out = re.sub(r"[ \t]+", " ", out)
        return re.sub(r"\n\s*\n+", "\n\n", out).strip()


class _DDGParser(HTMLParser):
    """Pull (title, url, snippet) triples out of DuckDuckGo's HTML endpoint."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._mode: str | None = None
        self._buf: list[str] = []
        self._href = ""

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        a = dict(attrs)
        cls = a.get("class", "") or ""
        if tag == "a" and "result__a" in cls:
            self._mode, self._buf, self._href = "title", [], a.get("href", "") or ""
        elif "result__snippet" in cls:
            self._mode, self._buf = "snippet", []

    def handle_endtag(self, tag: str) -> None:
        if self._mode == "title" and tag == "a":
            self.results.append(
                {"title": " ".join(self._buf).strip(),
                 "url": _unwrap_ddg(self._href), "snippet": ""}
            )
            self._mode = None
        elif self._mode == "snippet" and tag in ("a", "div", "td"):
            if self.results and not self.results[-1]["snippet"]:
                self.results[-1]["snippet"] = " ".join(self._buf).strip()
            self._mode = None

    def handle_data(self, data: str) -> None:
        if self._mode and data.strip():
            self._buf.append(data.strip())


def _unwrap_ddg(href: str) -> str:
    """DuckDuckGo wraps results as /l/?uddg=<encoded>; recover the real URL."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    try:
        q = parse_qs(urlparse(href).query)
        if "uddg" in q:
            return q["uddg"][0]
    except Exception:
        pass
    return href


# ------------------------------------------------------------- safe compute

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS: dict[str, Any] = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "len": len, "int": int, "float": float, "pow": pow,
}


def _safe_eval(node: ast.AST) -> Any:
    """Evaluate an arithmetic AST. Never touches eval()/exec()."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise ValueError(f"unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, (ast.Tuple, ast.List)):
        return [_safe_eval(e) for e in node.elts]
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError("only abs/round/min/max/sum/len/int/float/pow allowed")
        return _FUNCS[node.func.id](*[_safe_eval(a) for a in node.args])
    if isinstance(node, ast.Compare):
        left = _safe_eval(node.left)
        for op, comp in zip(node.ops, node.comparators):
            right = _safe_eval(comp)
            ok = {
                ast.Eq: left == right, ast.NotEq: left != right,
                ast.Lt: left < right, ast.LtE: left <= right,
                ast.Gt: left > right, ast.GtE: left >= right,
            }.get(type(op))
            if ok is None:
                raise ValueError("unsupported comparison")
            if not ok:
                return False
            left = right
        return True
    raise ValueError(f"unsupported expression element: {type(node).__name__}")


# Commands that can wreck the machine or the session. The agent is autonomous;
# it is not permitted to be autonomously destructive.
_SHELL_DENY = re.compile(
    r"(\brm\s+(-\w*\s+)*-\w*[rf]\w*\s+/(?!home/\w+/[\w./-]+)"
    r"|\bmkfs\b|\bdd\s+[^|]*of=/dev/"
    r"|>\s*/dev/[sh]d|\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b"
    r"|\bchmod\s+-R\s+000\b|:\(\)\s*\{.*\|.*&\s*\}\s*;"
    r"|\buserdel\b|\bpasswd\b|\bvisudo\b)",
    re.IGNORECASE,
)


class Toolbox:
    def __init__(self, config: Config, memory: Any = None):
        self.config = config
        self.memory = memory
        self._tools: dict[str, Tool] = {}
        self._register_all()

    # ------------------------------------------------------------- registry

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def describe(self, only: list[str] | None = None) -> str:
        names = only or list(self._tools)
        return "\n".join(f"- {self._tools[n].signature()}" for n in names if n in self._tools)

    async def run(self, name: str, args: dict[str, Any] | None = None) -> ToolResult:
        """Execute a tool. Errors are returned, never raised."""
        args = args or {}
        tool = self._tools.get(name)
        if tool is None:
            near = ", ".join(sorted(self._tools)[:12])
            return ToolResult(name, args, f"No such tool '{name}'. Available: {near}", False)

        started = datetime.now()
        try:
            clean = {k: v for k, v in args.items() if k in tool.params}
            out = await tool.run(**clean)
            ok = True
        except TypeError as e:
            out, ok = f"Bad arguments for {name}({', '.join(tool.params)}): {e}", False
        except Exception as e:
            out, ok = f"{type(e).__name__}: {e}", False

        ms = int((datetime.now() - started).total_seconds() * 1000)
        text = out if isinstance(out, str) else json.dumps(out, default=str)
        if len(text) > MAX_OUT:
            text = text[:MAX_OUT] + f"\n… [truncated, {len(text)} chars total]"
        if self.memory is not None:
            try:
                self.memory.record_tool(name, ok)
            except Exception:
                pass
        return ToolResult(name, args, text, ok, ms)

    # ------------------------------------------------------- tool functions

    def _resolve(self, path: str) -> Path:
        """Relative paths land in the workspace; absolute paths are honoured."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else (self.config.workspace / p)

    def _register_all(self) -> None:
        cfg = self.config

        # ---- knowledge -------------------------------------------------
        async def web_search(query: str = "", max_results: int = 5) -> str:
            if not query.strip():
                return "Error: query is required."
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            lines: list[str] = []
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                    # Instant-answer API first: cheap, structured, often enough.
                    try:
                        r = await c.get(
                            "https://api.duckduckgo.com/",
                            params={"q": query, "format": "json", "no_html": 1},
                            headers=headers,
                        )
                        d = r.json()
                        if d.get("AbstractText"):
                            lines.append(f"Summary: {d['AbstractText']}")
                            if d.get("AbstractURL"):
                                lines.append(f"Source: {d['AbstractURL']}")
                        for t in (d.get("RelatedTopics") or [])[:4]:
                            if isinstance(t, dict) and t.get("Text"):
                                lines.append(f"- {t['Text']}")
                    except Exception:
                        pass

                    hits: list[dict] = []

                    # Brave Search API: the primary provider when a key is configured.
                    if cfg.brave_api_key:
                        try:
                            r = await c.get(
                                "https://api.search.brave.com/res/v1/web/search",
                                params={"q": query, "count": max(1, min(max_results, 10))},
                                headers={"Accept": "application/json",
                                         "X-Subscription-Token": cfg.brave_api_key},
                            )
                            if r.status_code == 200:
                                for it in r.json().get("web", {}).get("results", []):
                                    hits.append({
                                        "title": html.unescape(re.sub(r"<[^>]+>", "", it.get("title", ""))),
                                        "url": it.get("url", ""),
                                        "snippet": html.unescape(re.sub(r"<[^>]+>", "", it.get("description", ""))),
                                    })
                            elif r.status_code in (401, 403, 422):
                                lines.append("(Brave key rejected — check BRAVE_API_KEY)")
                            elif r.status_code == 429:
                                lines.append("(Brave quota exhausted — using fallback search)")
                        except httpx.HTTPError:
                            pass

                    # Yahoo (Bing-backed): works from plain HTTP when Google/DDG/Bing challenge us.
                    if not hits:
                        try:
                            r = await c.get("https://search.yahoo.com/search",
                                            params={"p": query, "ei": "UTF-8"}, headers=headers)
                            if r.status_code == 200:
                                hits = _yahoo_results(r.text, max(1, min(max_results, 10)))
                        except httpx.HTTPError:
                            pass

                    try:
                        if hits:
                            raise httpx.HTTPError("already have results")
                        r = await c.post(
                            "https://html.duckduckgo.com/html/",
                            data={"q": query}, headers=headers,
                        )
                        # DuckDuckGo answers 202 with a bot challenge page instead of results.
                        if r.status_code == 200:
                            p = _DDGParser()
                            p.feed(r.text)
                            hits = [h for h in p.results if h["title"]][: max(1, min(max_results, 10))]
                    except httpx.HTTPError:
                        pass

                    if not hits:
                        # Keyless fallback: Wikipedia full-text search.
                        try:
                            r = await c.get(
                                "https://en.wikipedia.org/w/api.php",
                                params={"action": "query", "list": "search", "srsearch": query,
                                        "srlimit": max(1, min(max_results, 10)), "format": "json"},
                                headers={"User-Agent": "JANOS/2.0 (local assistant; "
                                                       "https://github.com/Stradok/JANOS)"},
                            )
                            for it in r.json().get("query", {}).get("search", []):
                                title = it["title"]
                                hits.append({
                                    "title": title,
                                    "url": "https://en.wikipedia.org/wiki/" + quote_plus(title.replace(" ", "_"), safe="_"),
                                    "snippet": html.unescape(re.sub(r"<[^>]+>", "", it.get("snippet", ""))),
                                })
                        except Exception:
                            pass
                    if hits:
                        lines.append(f"\nResults for {query!r}:")
                        for i, h in enumerate(hits, 1):
                            lines.append(f"{i}. {h['title']}\n   {h['url']}\n   {h['snippet'][:280]}")
            except httpx.HTTPError as e:
                return f"Search failed (network): {e}. There may be no internet access."
            return "\n".join(lines) if lines else f"No results for {query!r}."

        async def web_fetch(url: str = "", max_chars: int = 3000) -> str:
            if not url.strip():
                return "Error: url is required."
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            try:
                async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
                    # Wikimedia rejects browser-impersonating agents and asks bots to identify.
                    ua = ("JANOS/2.0 (local assistant; https://github.com/Stradok/JANOS)"
                          if "wikipedia.org" in url or "wikimedia.org" in url
                          else "Mozilla/5.0 (X11; Linux x86_64)")
                    r = await c.get(url, headers={"User-Agent": ua})
                    r.raise_for_status()
                    ctype = r.headers.get("content-type", "")
                    if "html" not in ctype and "text" not in ctype and "json" not in ctype:
                        return f"Unsupported content-type {ctype!r} at {url}"
                    body = r.text
            except httpx.HTTPError as e:
                return f"Fetch failed: {e}"
            if "html" in r.headers.get("content-type", ""):
                p = _TextExtractor()
                p.feed(body)
                body = p.text()
            body = html.unescape(body)
            return f"[{url}]\n{body[:max(500, max_chars)]}"

        def _bad_ip(ip: Any) -> bool:
            return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                    or ip.is_multicast or ip.is_unspecified or not ip.is_global)

        async def _resolve_public(host: str) -> tuple[str, str]:
            """Resolve once. Returns (first_ip, '') if EVERY address is public, else ('', reason)."""
            try:
                infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
            except (OSError, UnicodeError) as e:
                return "", f"cannot resolve {host!r}: {e}"
            ips = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
            for ip in ips:
                if _bad_ip(ip):
                    return "", f"{host} resolves to internal address {ip}"
            return (str(ips[0]), "") if ips else ("", f"{host!r} has no address")

        async def browser_fetch(url: str = "", max_chars: int = 3000, wait_ms: int = 1500) -> str:
            if not url.strip():
                return "Error: url is required."
            url = url.strip()
            if "://" not in url:
                url = "https://" + url
            u = urlparse(url)
            if u.scheme not in ("http", "https") or not u.hostname:
                return "Error: only http/https URLs are supported."
            try:
                port = u.port
            except ValueError:
                return "Refused: invalid port."
            if port not in (None, 80, 443):
                return f"Refused: non-standard port {port} is not allowed."
            host = u.hostname
            pinned_ip, why = await _resolve_public(host)
            if why:
                return f"Refused: internal or unresolvable target ({why})."
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                return "Browser fetch unavailable: Playwright not installed."

            async def gate(route):
                req = route.request
                ru = urlparse(req.url)
                try:
                    ok = (ru.scheme in ("http", "https") and ru.hostname
                          and ru.port in (None, 80, 443)
                          and req.resource_type not in ("media", "font"))
                except ValueError:
                    ok = False
                if ok and ru.hostname != host:
                    # Not the pinned host: re-validate by resolved IP on every request (no cache).
                    # ponytail: Chromium re-resolves these itself, so a rebinding race remains for third-party hosts.
                    ok = not (await _resolve_public(ru.hostname))[1]
                if ok:
                    await route.continue_()
                else:
                    await route.abort()

            async def run() -> str:
                # Chromium sandbox stays ON (no --no-sandbox). Host is pinned to the validated IP.
                args = ["--disable-dev-shm-usage", "--disable-gpu"]
                if host != pinned_ip:  # IP literals need no pin
                    args.append(f"--host-resolver-rules=MAP {host} {pinned_ip},EXCLUDE localhost")
                async with async_playwright() as pw:
                    try:
                        browser = await pw.chromium.launch(headless=True, args=args)
                    except Exception as e:
                        if "sandbox" in str(e).lower():
                            return "Browser fetch unavailable: Chromium sandbox could not start"
                        raise
                    try:
                        ctx = await browser.new_context(
                            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
                            java_script_enabled=True, service_workers="block", accept_downloads=False)
                        page = await ctx.new_page()
                        await page.route("**/*", gate)
                        await page.route_web_socket("**/*", lambda ws: ws.close())
                        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                        await page.wait_for_timeout(min(max(wait_ms, 0), 5000))
                        return await page.evaluate("document.body ? document.body.innerText : ''")
                    finally:
                        await browser.close()

            try:
                text = await asyncio.wait_for(run(), timeout=20)
            except Exception as e:
                return f"Browser fetch failed: {type(e).__name__}: {str(e)[:200]}"
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                return f"[{url}]\n(page rendered but has no text)"
            n = max(500, max_chars)
            note = f"\n… [truncated, {len(text)} chars total]" if len(text) > n else ""
            return f"[{url}]\n{text[:n]}{note}"

        # ---- files -----------------------------------------------------
        async def read_file(path: str = "", max_chars: int = 4000) -> str:
            p = self._resolve(path)
            if not p.exists():
                return f"Not found: {p}"
            if p.is_dir():
                return f"{p} is a directory — use list_dir."
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                return f"Cannot read {p}: {e}"
            return f"[{p}]\n{text[:max_chars]}"

        async def write_file(path: str = "", content: str = "", append: bool = False) -> str:
            p = self._resolve(path)
            # Keep writes inside the workspace or the user's own home. Models
            # cheerfully try /root and /etc, then burn turns on the resulting
            # permission errors.
            home = Path.home().resolve()
            ws = cfg.workspace.resolve()
            try:
                target = p.resolve()
            except OSError:
                target = p
            if not (target.is_relative_to(ws) or target.is_relative_to(home)):
                return (f"Refused: {target} is outside the workspace and your home "
                        f"directory. Use a bare filename to write into {ws}.")
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a" if append else "w", encoding="utf-8") as fh:
                    fh.write(content)
            except OSError as e:
                return f"Cannot write {p}: {e}"
            return f"{'Appended to' if append else 'Wrote'} {p} ({len(content)} chars)"

        async def list_dir(path: str = ".") -> str:
            p = self._resolve(path)
            if not p.is_dir():
                return f"Not a directory: {p}"
            rows = []
            for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:100]:
                try:
                    size = f"{item.stat().st_size:>9,}" if item.is_file() else "      dir"
                except OSError:
                    size = "        ?"
                rows.append(f"{size}  {item.name}")
            return f"[{p}]\n" + ("\n".join(rows) or "(empty)")

        # ---- compute ---------------------------------------------------
        async def calculate(expression: str = "") -> str:
            if not expression.strip():
                return "Error: expression is required."
            try:
                tree = ast.parse(expression, mode="eval")
                value = _safe_eval(tree)
                # 12 significant digits hides binary float noise (0.18*340 is
                # 61.199999999999996) without changing any real result.
                if isinstance(value, float):
                    value = float(f"{value:.12g}")
                    value = int(value) if value.is_integer() and abs(value) < 1e15 else value
                return f"{expression} = {value}"
            except SyntaxError as e:
                return f"Cannot parse {expression!r}: {e.msg}"
            except Exception as e:
                return f"Math error: {e}"

        async def run_python(code: str = "", timeout: int = 20) -> str:
            """Run a snippet in a fresh interpreter. Use print() to return data."""
            if not code.strip():
                return "Error: code is required."
            try:
                proc = await asyncio.create_subprocess_exec(
                    *sandbox.prefix(cfg, "isolated"), sys.executable, "-c", textwrap.dedent(code),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    cwd=str(cfg.workspace),
                )
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=min(timeout, 60))
            except asyncio.TimeoutError:
                proc.kill()
                return f"Python snippet exceeded {timeout}s and was killed."
            except Exception as e:
                return f"Could not run python: {e}"
            text = out.decode("utf-8", "replace").strip()
            return text or f"(no output, exit code {proc.returncode})"

        async def shell(command: str = "", timeout: int = 0) -> str:
            if not cfg.allow_shell:
                return "Shell is disabled in config (allow_shell: false)."
            if not command.strip():
                return "Error: command is required."
            if _SHELL_DENY.search(command):
                return ("Refused: this command is destructive (disk, power, or account "
                        "modification). Choose a non-destructive alternative.")
            # There is no terminal to type a password into, so an interactive
            # sudo would hang until the timeout. Fail it immediately and say so,
            # otherwise the agent retries sudo variants until it runs out of turns.
            uses_sudo = bool(re.search(r"(^|[|;&]\s*)sudo\b", command))
            if uses_sudo:
                command = re.sub(r"(^|[|;&]\s*)sudo\b", r"\1sudo -n", command)
            limit = timeout or cfg.shell_timeout
            try:
                # Models reach for bash-isms (echo -e, [[ ]], pipefail);
                # /bin/sh would emit them literally instead of running them.
                proc = await asyncio.create_subprocess_exec(
                    *sandbox.prefix(cfg, "observe"), shutil.which("bash") or "/bin/sh", "-c", command,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    cwd=str(cfg.workspace),
                )
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=limit)
            except asyncio.TimeoutError:
                proc.kill()
                return f"Command exceeded {limit}s and was killed: {command}"
            except Exception as e:
                return f"Shell error: {e}"
            text = out.decode("utf-8", "replace").strip()
            code = proc.returncode
            if uses_sudo and code != 0:
                return (f"$ {command}\n(exit {code})\n{text}\n\n"
                        "sudo cannot be used here — there is no terminal for a password. "
                        "Do not retry with sudo; find an answer that does not need root.")
            head = f"$ {command}\n(exit {code})\n"
            return head + (text or "(no output)")

        # ---- environment ------------------------------------------------
        async def now(fmt: str = "") -> str:
            local = datetime.now().astimezone()
            if fmt:
                try:
                    return local.strftime(fmt)
                except Exception:
                    pass
            return (f"{local.strftime('%A %d %B %Y, %H:%M:%S %Z')} "
                    f"(UTC {datetime.now(timezone.utc).strftime('%H:%M')})")

        async def system_info(what: str = "all") -> str:
            lines = [f"OS: {platform.system()} {platform.release()} ({platform.machine()})",
                     f"Python: {platform.python_version()}"]
            try:
                import psutil

                if what in ("all", "cpu"):
                    lines.append(f"CPU: {psutil.cpu_count(logical=False)}C/"
                                 f"{psutil.cpu_count()}T at {psutil.cpu_percent(interval=0.1)}% load")
                # Percentages are derived from the very figures printed beside
                # them. psutil's own .percent uses a different denominator
                # (it excludes root-reserved blocks on disks), which would make
                # this line contradict itself and mislead the model.
                if what in ("all", "memory"):
                    m = psutil.virtual_memory()
                    used, total = m.used / 2**30, m.total / 2**30
                    lines.append(
                        f"RAM: {used:.1f} GiB used of {total:.1f} GiB total "
                        f"= {used/total*100:.1f}%; {m.available/2**30:.1f} GiB available"
                    )
                if what in ("all", "disk"):
                    d = psutil.disk_usage("/")
                    used, total = d.used / 2**30, d.total / 2**30
                    lines.append(
                        f"Disk /: {used:.1f} GiB used of {total:.1f} GiB total "
                        f"= {used/total*100:.1f}%; {d.free/2**30:.1f} GiB free"
                    )
            except ImportError:
                total, used, free = shutil.disk_usage("/")
                lines.append(f"Disk /: {used/2**30:.0f}/{total/2**30:.0f} GiB")
            if what in ("all", "gpu"):
                exe = shutil.which("nvidia-smi")
                if exe:
                    try:
                        p = subprocess.run(
                            [exe, "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                             "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, timeout=8,
                        )
                        if p.returncode == 0 and p.stdout.strip():
                            for row in p.stdout.strip().splitlines():
                                # Derived values are computed here on purpose: the
                                # model must never be left to divide these itself.
                                cols = [c.strip() for c in row.split(",")]
                                if len(cols) == 4:
                                    name, used, total, util = cols
                                    pct = (float(used) / float(total) * 100) if float(total) else 0.0
                                    lines.append(
                                        f"GPU: {name} — VRAM {used} MiB used of {total} MiB total "
                                        f"= {pct:.1f}% of VRAM in use; core utilisation {util}%"
                                    )
                                else:
                                    lines.append(f"GPU: {row}")
                    except (OSError, ValueError, ZeroDivisionError, subprocess.SubprocessError):
                        pass
            return "\n".join(lines)

        async def recall_memory(query: str = "", limit: int = 4) -> str:
            if self.memory is None:
                return "Memory is not available."
            hits = self.memory.recall(query, k=max(1, min(limit, 10)))
            if not hits:
                return f"Nothing remembered about {query!r}."
            out = []
            for h in hits:
                out.append(f"[{h['ts'][:10]} score={h['score']:.2f}] {h['task']}\n"
                           f"  -> {(h['answer'] or '')[:300]}")
            return "\n".join(out)

        async def save_note(title: str = "", body: str = "") -> str:
            if not (title.strip() or body.strip()):
                return "Error: title or body required."
            if self.memory is not None:
                self.memory.add_lesson(f"{title}: {body}"[:500], task_type="note", source="user")
            notes = cfg.workspace / "notes.md"
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(notes, "a", encoding="utf-8") as fh:
                fh.write(f"\n## {title or 'Note'} — {stamp}\n{body}\n")
            return f"Saved note {title!r} to {notes}"

        spec: list[tuple] = [
            ("web_search", "Search the web for current information.",
             {"query": "str", "max_results": "int=5"}, web_search, False),
            ("web_fetch", "Download a URL and return its readable text.",
             {"url": "str", "max_chars": "int=3000"}, web_fetch, False),
            ("browser_fetch", "Fetch a URL in a real browser so JavaScript runs, then return the page text. Use only when web_fetch returns little or the site needs JavaScript.",
             {"url": "str", "max_chars": "int=3000", "wait_ms": "int=1500"}, browser_fetch, False),
            ("read_file", "Read a text file from disk.",
             {"path": "str", "max_chars": "int=4000"}, read_file, False),
            ("write_file", "Write or append text to a file.",
             {"path": "str", "content": "str", "append": "bool=false"}, write_file, True),
            ("list_dir", "List the contents of a directory.",
             {"path": "str='.'"}, list_dir, False),
            ("calculate", "Evaluate an arithmetic expression exactly.",
             {"expression": "str"}, calculate, False),
            ("run_python", "Run a short Python script and capture its stdout. Sandboxed: no network, only the workspace is visible.",
             {"code": "str", "timeout": "int=20"}, run_python, True),
            ("shell", "Run a shell command on this Linux machine. Sandboxed: processes, disks and GPU are visible; only the workspace is writable; home folder hidden; no network (use web_search / web_fetch).",
             {"command": "str", "timeout": "int"}, shell, True),
            ("now", "Get the current local date and time.",
             {"fmt": "str (optional strftime)"}, now, False),
            ("system_info", "Report CPU, RAM, disk and GPU status.",
             {"what": "str: all|cpu|memory|disk|gpu"}, system_info, False),
            ("recall_memory", "Search past conversations and results.",
             {"query": "str", "limit": "int=4"}, recall_memory, False),
            ("save_note", "Persist a note for later recall.",
             {"title": "str", "body": "str"}, save_note, False),
        ]
        for name, desc, params, fn, danger in spec:
            self.add(Tool(name=name, description=desc, params=params, run=fn, danger=danger))
