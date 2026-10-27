"""Tool-calling modules ("playbooks"): capabilities made only of tool calls.

JANOS has two kinds of self-written module:

  skill      a Python file (janos/generated/*.py) written by forge.py. Used when
             the capability needs new code: a new API, parsing, computation.
  playbook   a JSON file (janos/playbooks/*.json) written here. No code at all:
             an ordered list of calls to tools that already exist, with the
             output of one step feeding the next. Used when the capability is
             a workflow over existing tools ("search, fetch the top hit, save").

A playbook registers in the toolbox exactly like any other tool, so agents call
it by name. Because it contains no code it needs no sandbox, only validation:
every step must name a real tool, every {{placeholder}} must resolve, and it may
not reach the dangerous tools (shell, run_python, the builders) that would let a
model-written recipe do more than compose safe ones.

Format:
    {"name": "news_digest",
     "description": "Search a topic and summarise the top page.",
     "params": {"topic": "str=AI"},
     "steps": [{"tool": "web_search", "args": {"query": "{{topic}} news"}},
               {"tool": "web_fetch",  "args": {"url": "{{step1.url}}"}}],
     "output": "{{step2}}"}

Placeholders: {{param}}, {{stepN}} (whole output of step N), {{stepN.url}}
(first URL found in it), {{stepN.line}} (first non-empty line).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from janos.config import Config
from janos.forge import _looks_like_failure, _urls_in
from janos.llm import LLM, LLMError
from janos.tools import Tool, Toolbox

PLAYBOOKS = Path(__file__).resolve().parent / "playbooks"

# A recipe may compose tools, but not obtain code execution or build more modules.
FORBIDDEN_STEP_TOOLS = {"shell", "run_python", "create_tool", "create_playbook", "write_file", "desktop", "computer"}

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][\w]*)(?:\.(url|line))?\s*\}\}")
MAX_STEPS = 6

PLAYBOOK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "params": {"type": "object", "additionalProperties": {"type": "string"}},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"tool": {"type": "string"},
                               "args": {"type": "object",
                                        "additionalProperties": {"type": "string"}}},
                "required": ["tool", "args"],
            },
        },
        "output": {"type": "string"},
    },
    "required": ["name", "description", "params", "steps"],
}


EXAMPLE = json.dumps({
    "name": "topic_page",
    "description": "Search the web for a topic and return the text of the top result page.",
    "params": {"topic": "str=Python asyncio", "chars": "int=2000"},
    "steps": [
        {"tool": "web_search", "args": {"query": "{{topic}}", "max_results": "3"}},
        {"tool": "web_fetch", "args": {"url": "{{step1.url}}", "max_chars": "{{chars}}"}},
    ],
    "output": "{{step2}}",
}, indent=1)


@dataclass
class PlaybookResult:
    ok: bool
    name: str = ""
    reason: str = ""
    path: str = ""
    smoke_output: str = ""


def _default_of(spec: str) -> str | None:
    """'str=AI' -> 'AI'; 'int=5' -> '5'; 'str' -> None (no default)."""
    if "=" not in spec:
        return None
    return spec.split("=", 1)[1].strip().strip("'\"")


def validate(pb: dict[str, Any], toolbox: Toolbox, own_name: str = "") -> tuple[bool, str]:
    """Static checks. Returns (ok, reason)."""
    name = pb.get("name", "")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", name):
        return False, "name must be snake_case, 3-41 characters"
    if not str(pb.get("description", "")).strip():
        return False, "description is required"
    params = pb.get("params")
    if not isinstance(params, dict):
        return False, "params must be an object"
    for k, v in params.items():
        if _default_of(str(v)) is None:
            return False, (f"param {k!r} needs a default (write e.g. \"str=AI\") so the "
                           f"playbook can be run with no arguments")
    steps = pb.get("steps")
    if not isinstance(steps, list) or not (1 <= len(steps) <= MAX_STEPS):
        return False, f"steps must be a list of 1-{MAX_STEPS} tool calls"

    for i, step in enumerate(steps, 1):
        tool = step.get("tool", "")
        if tool in FORBIDDEN_STEP_TOOLS:
            return False, f"step {i}: tool {tool!r} is not allowed in a playbook"
        t = toolbox.get(tool)
        if t is None:
            return False, f"step {i}: no such tool {tool!r}. Tools: {', '.join(toolbox.names())}"
        if getattr(t, "is_playbook", False) or tool == own_name:
            return False, f"step {i}: playbooks may not call other playbooks"
        args = step.get("args", {})
        for k in args:
            if k not in t.params:
                return False, f"step {i}: {tool} has no parameter {k!r} (has: {', '.join(t.params)})"
        for k, text in args.items():
            text = str(text)
            if re.fullmatch(r"\s*(str|int|float|bool)\s*(=.*)?", text):
                return False, (f"step {i}: arg {k!r} is {text!r}, a type spec, not a value. "
                               f"Give the real value, e.g. \"3\".")
            leftover = _PLACEHOLDER.sub("", text)
            if "{{" in leftover or "}}" in leftover:
                return False, (f"step {i}: arg {k!r} has an invalid placeholder in {text!r}. "
                               f"Only {{{{param}}}}, {{{{stepN}}}}, {{{{stepN.url}}}} and "
                               f"{{{{stepN.line}}}} exist — no indexing or other fields.")
            for ref, _ in _PLACEHOLDER.findall(str(text)):
                ok, why = _ref_ok(ref, params, i)
                if not ok:
                    return False, f"step {i}: {why}"
    for ref, _ in _PLACEHOLDER.findall(str(pb.get("output", ""))):
        ok, why = _ref_ok(ref, params, len(steps) + 1)
        if not ok:
            return False, f"output: {why}"
    return True, ""


def _ref_ok(ref: str, params: dict, before_step: int) -> tuple[bool, str]:
    m = re.fullmatch(r"step(\d+)", ref)
    if m:
        n = int(m.group(1))
        if n >= before_step:
            return False, f"{{{{{ref}}}}} refers to a step that has not run yet"
        return True, ""
    if ref in params:
        return True, ""
    return False, f"{{{{{ref}}}}} is neither a param ({', '.join(params) or 'none'}) nor stepN"


def _render(template: str, values: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        ref, field = m.group(1), m.group(2)
        val = values.get(ref, "")
        if field == "url":
            found = _urls_in(val)
            return found[0].rstrip(".,);") if found else ""
        if field == "line":
            return next((l.strip() for l in val.splitlines() if l.strip()), "")
        return val
    return _PLACEHOLDER.sub(sub, str(template))


def _normalise(pb: dict[str, Any]) -> None:
    """Repair the placeholder forms a small model reliably invents.

    `{{step1[0].snippet.url}}` and `{{step1.results.link}}` mean "the URL in step
    1", and `{{step1.text}}` means the step's output. Rewriting them is more
    dependable than asking the model to stop, which it does not.
    """
    def fix(text: Any) -> Any:
        if not isinstance(text, str):
            return text
        text = re.sub(r"\{\{\s*step(\d+)[^}]*?(?:url|link|href)[^}]*\}\}", r"{{step\1.url}}", text, flags=re.I)
        text = re.sub(r"\{\{\s*step(\d+)(?!\s*(?:\.url|\.line)?\s*\}\})[^}]*\}\}", r"{{step\1}}", text)
        return text

    for step in pb.get("steps", []) if isinstance(pb.get("steps"), list) else []:
        if isinstance(step, dict) and isinstance(step.get("args"), dict):
            step["args"] = {k: fix(v) for k, v in step["args"].items()}
    if "output" in pb:
        pb["output"] = fix(pb["output"])


class PlaybookForge:
    """Writes, validates, and registers tool-calling modules."""

    def __init__(self, config: Config, llm: LLM, toolbox: Toolbox, memory: Any = None):
        self.config = config
        self.llm = llm
        self.toolbox = toolbox
        self.memory = memory
        PLAYBOOKS.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ loading

    def names(self) -> list[str]:
        return sorted(p.stem for p in PLAYBOOKS.glob("*.json"))

    def load_all(self) -> list[str]:
        """Register every saved playbook whose steps still validate."""
        loaded = []
        for path in sorted(PLAYBOOKS.glob("*.json")):
            try:
                pb = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            ok, _ = validate(pb, self.toolbox, own_name=pb.get("name", ""))
            if ok:
                self._register(pb)
                loaded.append(pb["name"])
        return loaded

    def _register(self, pb: dict[str, Any]) -> None:
        async def run(**kwargs: Any) -> str:
            return await self.execute(pb, kwargs)

        tool = Tool(
            name=pb["name"],
            description=pb["description"] + " [playbook]",
            params={k: str(v) for k, v in pb["params"].items()},
            run=run,
            danger=False,
            untrusted=True,
        )
        tool.is_playbook = True  # type: ignore[attr-defined]
        self.toolbox.add(tool)

    # ---------------------------------------------------------- execution

    async def execute(self, pb: dict[str, Any], given: dict[str, Any]) -> str:
        values: dict[str, str] = {}
        for k, spec in pb["params"].items():
            v = given.get(k)
            values[k] = str(v) if v not in (None, "") else (_default_of(str(spec)) or "")

        for i, step in enumerate(pb["steps"], 1):
            args = {k: _render(v, values) for k, v in step.get("args", {}).items()}
            for k, raw in step.get("args", {}).items():
                if not args[k].strip() and _PLACEHOLDER.search(str(raw)):
                    return (f"Playbook {pb['name']} failed at step {i}: {raw!r} rendered empty "
                            f"(params: { {p: values.get(p) for p in pb['params']} })")
            args = self._coerce(step["tool"], args)
            res = await self.toolbox.run(step["tool"], args)
            if not res.ok or _looks_like_failure(res.output):
                return f"Playbook {pb['name']} failed at step {i} ({step['tool']}): {res.output[:300]}"
            values[f"step{i}"] = res.output

        template = pb.get("output") or f"{{{{step{len(pb['steps'])}}}}}"
        return _render(template, values)

    def _coerce(self, tool_name: str, args: dict[str, str]) -> dict[str, Any]:
        """Playbook values are text; turn them into the types the tool declares."""
        tool = self.toolbox.get(tool_name)
        out: dict[str, Any] = dict(args)
        for k, v in args.items():
            kind = (tool.params.get(k, "") if tool else "").strip().lower()
            try:
                if kind.startswith("int"):
                    out[k] = int(float(v))
                elif kind.startswith("float"):
                    out[k] = float(v)
                elif kind.startswith("bool"):
                    out[k] = v.strip().lower() in ("1", "true", "yes")
            except ValueError:
                out[k] = v  # let the tool report the bad value
        return out

    # ------------------------------------------------------------ authoring

    async def create(self, purpose: str, name_hint: str = "", attempts: int = 3) -> PlaybookResult:
        usable = "\n".join(
            f"- {t.signature()}" for n in self.toolbox.names()
            if n not in FORBIDDEN_STEP_TOOLS and not getattr(t := self.toolbox.get(n), "is_playbook", False)
        )
        existing = ", ".join(self.names()) or "none"
        feedback = ""

        for _ in range(attempts):
            prompt = (
                f"Design a playbook: a fixed sequence of calls to EXISTING tools, no code.\n\n"
                f"WHAT IT MUST DO: {purpose}\n"
                f"{f'SUGGESTED NAME: {name_hint}' if name_hint else ''}\n"
                f"Existing playbooks (do not duplicate): {existing}\n\n"
                f"TOOLS YOU MAY CALL (only these, only their listed parameters):\n{usable}\n\n"
                f"Rules:\n"
                f"- 1 to {MAX_STEPS} steps. Each step: {{\"tool\": ..., \"args\": {{param: text}}}}.\n"
                f"- params maps name to 'type=default', e.g. {{\"topic\": \"str=AI\"}}. EVERY param needs a default.\n"
                f"- In arg text use {{{{topic}}}} for a param, {{{{step1}}}} for the whole output of "
                f"step 1, {{{{step1.url}}}} for the first URL in it, {{{{step1.line}}}} for its first line.\n"
                f"- A step may only reference EARLIER steps.\n"
                f"- `output` is a template for the final result; omit it to return the last step.\n"
                f"- name is snake_case.\n"
                f"- Tool outputs are PLAIN TEXT, not JSON: never index into them.\n\n"
                f"WORKED EXAMPLE (copy this style exactly):\n{EXAMPLE}{feedback}"
            )
            try:
                pb = await self.llm.chat_json(
                    [{"role": "system", "content":
                      "You compose workflows out of existing tools. You output only the JSON object."},
                     {"role": "user", "content": prompt}],
                    PLAYBOOK_SCHEMA, temperature=0.2,
                )
            except LLMError as e:
                return PlaybookResult(False, reason=f"model failed: {e}")

            pb["name"] = re.sub(r"\W+", "_", str(pb.get("name") or name_hint)).strip("_").lower()
            _normalise(pb)
            ok, reason = validate(pb, self.toolbox, own_name=pb["name"])
            if ok and pb["name"] in self.toolbox.names() and pb["name"] not in self.names():
                ok, reason = False, f"name {pb['name']!r} is taken by a built-in tool"
            if not ok:
                feedback = f"\nYour previous attempt was rejected: {reason}. Fix it."
                continue

            out = await self.execute(pb, {})
            if out.startswith(f"Playbook {pb['name']} failed") or not out.strip():
                feedback = f"\nYour previous attempt failed when run with defaults: {out[:300]}. Fix it."
                continue

            path = PLAYBOOKS / f"{pb['name']}.json"
            path.write_text(json.dumps(pb, indent=2), encoding="utf-8")
            self._register(pb)
            if self.memory is not None:
                try:
                    self.memory.add_lesson(
                        f"A playbook `{pb['name']}` exists: {pb['description'][:160]}",
                        task_type="tooling", source="forge")
                except Exception:
                    pass
            return PlaybookResult(True, name=pb["name"], path=str(path), smoke_output=out[:400])

        return PlaybookResult(False, reason=f"gave up after {attempts} attempts. {feedback.strip()}")
