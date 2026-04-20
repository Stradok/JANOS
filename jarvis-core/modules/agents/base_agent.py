# modules/agents/base_agent.py
"""
BaseAgent — The generic agent loop that all specialized agents inherit.
Implements the think → act → observe → decide cycle.
"""
import json
import re
import time
import requests
from datetime import datetime


class BaseAgent:
    """
    Base class for all JAN agents.
    Provides the agentic loop: think → act → observe → decide → repeat.
    Subclasses define their own tools, system prompt, and model.
    """

    OLLAMA_URL = "http://localhost:11434/api/chat"

    def __init__(self, name, tools=None, model="qwen2.5:7b-instruct",
                 max_steps=15, step_timeout=30):
        self.name = name
        self.tools = tools or {}          # name → module instance
        self.model = model
        self.max_steps = max_steps
        self.step_timeout = step_timeout
        self.screen_reader = None         # set by orchestrator
        self.dispatcher = None            # set by orchestrator (for agent-to-agent calls)
        self.memory = None                # set by orchestrator (for memory recall/save)
        self.learning_engine = None       # set by orchestrator (for RAG + skill learning)

    # ── Override in subclasses ─────────────────────────────────────

    def get_system_prompt(self, task):
        """Subclasses provide their own system prompt with available tools."""
        raise NotImplementedError

    def needs_observation(self, action):
        """Return True if this action needs a screenshot+OCR observation.
        Override in subclasses for smarter control."""
        if not action or action.get("type") == "done":
            return False
        tool_name = action.get("tool", "")
        # By default, observe after UI-interacting tools
        ui_tools = {"browser", "keyboard_mouse", "app_launcher", "spotify", "youtube"}
        return tool_name in ui_tools

    def on_error(self, step, action, error):
        """Called when a tool execution fails. Override for custom recovery."""
        return None  # default: let the LLM handle it via history

    # ── Tool Descriptions (auto-generated from tools dict) ─────────

    def _build_tool_descriptions(self):
        """Build a human-readable tool list for the system prompt."""
        lines = []
        for name, module in self.tools.items():
            doc = (module.__class__.__doc__ or "").strip().split("\n")[0]
            lines.append(f"  - {name}: {doc}")
        return "\n".join(lines)

    # ── LLM Communication ──────────────────────────────────────────

    def _call_llm(self, messages, temperature=0.4, max_tokens=1024, retries=2):
        """Send messages to Ollama and get a response. Retries on transient failures."""
        last_err = None
        for attempt in range(retries + 1):
            try:
                resp = requests.post(self.OLLAMA_URL, json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    }
                }, timeout=120)
                resp.raise_for_status()
                return resp.json()["message"]["content"], None
            except requests.ConnectionError:
                return None, "Ollama not running"
            except Exception as e:
                last_err = str(e)
                if attempt < retries:
                    time.sleep(1)
        return None, last_err

    def _parse_action(self, raw_text):
        """Parse the LLM's response into a structured action dict."""
        text = raw_text.strip()

        # Strip markdown code fences
        if "```" in text:
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
            if match:
                text = match.group(1).strip()

        # Try direct JSON parse
        try:
            return json.loads(text), None
        except json.JSONDecodeError:
            pass

        # Find outermost JSON object
        brace_depth = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == '{':
                if brace_depth == 0:
                    start = i
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0 and start != -1:
                    try:
                        return json.loads(text[start:i+1]), None
                    except json.JSONDecodeError:
                        break

        # Fix common JSON issues
        if start != -1:
            cleaned = text[start:text.rfind('}') + 1]
            cleaned = re.sub(r',\s*}', '}', cleaned)
            cleaned = re.sub(r',\s*]', ']', cleaned)
            try:
                return json.loads(cleaned), None
            except json.JSONDecodeError:
                pass

        # If all parsing fails, treat as a "respond" action
        return {
            "type": "done",
            "summary": raw_text.strip()[:500],
            "response": raw_text.strip()[:500]
        }, None

    # ── Tool Execution ─────────────────────────────────────────────

    def execute_tool(self, tool_name, tool_input):
        """Execute a tool (module) and return the result."""
        if tool_name not in self.tools:
            return {"error": f"Tool '{tool_name}' not available. Available: {list(self.tools.keys())}"}
        try:
            module = self.tools[tool_name]
            result = module.process(tool_input)
            return result
        except Exception as e:
            return {"error": f"Tool '{tool_name}' crashed: {str(e)}"}

    # ── Observation ────────────────────────────────────────────────

    def _observe(self, action, tool_result):
        """Observe the result of an action. Takes screenshot + OCR if needed."""
        observation = {"tool_result": tool_result}

        if self.screen_reader and self.needs_observation(action):
            time.sleep(0.5)  # let UI settle
            screen_state = self.screen_reader.observe(use_vision=False)
            observation["screen_text"] = screen_state.get("ocr_text", "")[:2000]
            observation["screenshot"] = screen_state.get("screenshot", "")
        return observation

    # ── The Agent Loop ─────────────────────────────────────────────

    def run(self, task, context=None):
        """
        Main entry point. Runs the think → act → observe → decide loop.
        
        Args:
            task: str — the user's request
            context: dict — optional context (conversation history, etc.)
        
        Returns:
            dict with status, response, steps taken, etc.
        """
        history = []
        system_prompt = self.get_system_prompt(task)

        messages = [{"role": "system", "content": system_prompt}]

        # Add context if provided
        if context and context.get("conversation_history"):
            for entry in context["conversation_history"][-10:]:
                messages.append(entry)

        # Recall relevant memories before starting
        memory_context = self._recall_memories(task)
        
        # Get RAG context and skill tips from learning engine
        rag_context = self._get_rag_context(task)
        skill_context = self._get_skill_context()
        
        # Build the initial user message with all context
        user_msg = task
        context_parts = []
        if memory_context:
            context_parts.append(f"[MEMORY — things I know about you and this topic]:\n{memory_context}")
        if rag_context:
            context_parts.append(f"[KNOWLEDGE — relevant info from my knowledge base]:\n{rag_context}")
        if skill_context:
            context_parts.append(f"{skill_context}")
        
        if context_parts:
            user_msg = task + "\n\n" + "\n\n".join(context_parts)
        
        messages.append({"role": "user", "content": user_msg})

        for step in range(self.max_steps):
            # 1. THINK — ask LLM what to do next
            print(f"[{self.name}] Step {step+1}/{self.max_steps} — thinking...")
            raw_response, llm_err = self._call_llm(messages)
            if llm_err:
                return {
                    "status": "error",
                    "agent": self.name,
                    "error": f"LLM error: {llm_err}",
                    "steps": history,
                    "response": f"I couldn't think about this: {llm_err}"
                }

            # 2. Parse the action
            action, parse_err = self._parse_action(raw_response)

            # 3. Check if agent says it's done
            if action.get("type") == "done":
                response = action.get("response", action.get("summary", "Task completed."))
                print(f"[{self.name}] Done after {len(history)} steps")
                self._save_step_to_memory(task, history, response)
                return {
                    "status": "ok",
                    "agent": self.name,
                    "response": response,
                    "steps": history,
                    "steps_taken": len(history),
                }

            # 4. Execute the tool action
            if action.get("type") == "tool":
                tool_name = action.get("tool", "")
                tool_input = action.get("input", {})
                print(f"[{self.name}] Step {step+1} — using tool: {tool_name}")

                tool_result = self.execute_tool(tool_name, tool_input)

                # Record skill outcome for learning
                self._record_skill_outcome(tool_name, tool_input, tool_result)

                # 5. Observe
                observation = self._observe(action, tool_result)

                # Record step
                step_record = {
                    "step": step + 1,
                    "thought": action.get("thought", ""),
                    "tool": tool_name,
                    "input": tool_input,
                    "result": self._truncate_result(tool_result),
                    "observation": observation.get("screen_text", "")[:500] if observation.get("screen_text") else "",
                }
                history.append(step_record)

                # Handle errors with optional recovery
                if isinstance(tool_result, dict) and tool_result.get("error"):
                    recovery = self.on_error(step, action, tool_result["error"])
                    if recovery:
                        # Subclass provided a recovery action
                        history.append({"step": step + 1, "recovery": recovery})

                # 6. Feed observation back to LLM for next decision
                obs_text = self._format_observation(step + 1, action, tool_result, observation)
                messages.append({"role": "assistant", "content": raw_response})
                messages.append({"role": "user", "content": obs_text})

            elif action.get("type") == "agent":
                # Agent-to-agent delegation
                if self.dispatcher:
                    sub_agent = action.get("agent", "")
                    sub_task = action.get("task", "")
                    sub_result = self.dispatcher.run_agent(sub_agent, sub_task, context)
                    step_record = {
                        "step": step + 1,
                        "thought": action.get("thought", ""),
                        "delegated_to": sub_agent,
                        "sub_task": sub_task,
                        "sub_result": self._truncate_result(sub_result),
                    }
                    history.append(step_record)
                    obs_text = f"[Step {step+1} Result] Agent '{sub_agent}' returned: {json.dumps(self._truncate_result(sub_result))}"
                    messages.append({"role": "assistant", "content": raw_response})
                    messages.append({"role": "user", "content": obs_text})
                else:
                    messages.append({"role": "assistant", "content": raw_response})
                    messages.append({"role": "user", "content": f"[Error] Agent delegation not available. Use your own tools instead."})

            elif action.get("type") == "respond":
                # Agent just wants to say something without a tool
                return {
                    "status": "ok",
                    "agent": self.name,
                    "response": action.get("response", action.get("message", str(action))),
                    "steps": history,
                    "steps_taken": len(history),
                }
            else:
                # Unknown action type — feed back error
                messages.append({"role": "assistant", "content": raw_response})
                messages.append({"role": "user", "content":
                    f"[Error] Unknown action type '{action.get('type')}'. "
                    f"Use: {{\"type\": \"tool\", \"tool\": \"name\", \"input\": {{...}}}} "
                    f"or {{\"type\": \"done\", \"response\": \"...\"}} "
                    f"or {{\"type\": \"agent\", \"agent\": \"name\", \"task\": \"...\"}}"
                })

        # Hit max steps
        last_response = history[-1].get("result", {}) if history else {}
        self._save_step_to_memory(task, history, "max_steps_reached")
        return {
            "status": "max_steps_reached",
            "agent": self.name,
            "response": f"I took {self.max_steps} steps but couldn't fully complete the task. Here's what I did so far.",
            "steps": history,
            "steps_taken": len(history),
        }

    # ── Helpers ────────────────────────────────────────────────────

    def _format_observation(self, step_num, action, tool_result, observation):
        """Format the observation as a message back to the LLM."""
        parts = [f"[Step {step_num} Result]"]

        # Tool result
        result_str = json.dumps(self._truncate_result(tool_result))
        parts.append(f"Tool output: {result_str}")

        # Screen observation
        screen_text = observation.get("screen_text", "")
        if screen_text:
            parts.append(f"Screen OCR: {screen_text[:1000]}")

        parts.append("What should I do next? If the task is complete, respond with {\"type\": \"done\", \"response\": \"summary of what was done\"}.")
        return "\n".join(parts)

    def _truncate_result(self, result, max_len=1500):
        """Truncate large results to keep context window manageable."""
        if isinstance(result, dict):
            truncated = {}
            for k, v in result.items():
                if isinstance(v, str) and len(v) > max_len:
                    truncated[k] = v[:max_len] + "...(truncated)"
                elif isinstance(v, list) and len(v) > 10:
                    truncated[k] = v[:10]
                else:
                    truncated[k] = v
            return truncated
        if isinstance(result, str) and len(result) > max_len:
            return result[:max_len] + "...(truncated)"
        return result

    # ── Memory Integration ─────────────────────────────────────────

    def _recall_memories(self, task):
        """Pull relevant memories before starting the agent loop."""
        if not self.memory:
            return ""
        
        parts = []
        try:
            # Search knowledge base for relevant info
            knowledge = self.memory.search_knowledge(task, limit=3)
            if knowledge.get("results"):
                for item in knowledge["results"]:
                    rel = item.get("relevance")
                    if rel is not None and rel < 0.3:
                        continue  # skip low relevance
                    parts.append(f"- {item.get('topic', '')}: {item.get('content', '')}")
        except Exception:
            pass
        
        try:
            # Check user preferences 
            prefs = self.memory.get_all_preferences()
            if prefs.get("preferences"):
                pref_str = ", ".join(f"{k}={v}" for k, v in list(prefs["preferences"].items())[:5])
                if pref_str:
                    parts.append(f"- User preferences: {pref_str}")
        except Exception:
            pass
        
        try:
            # Recent conversation context
            recent = self.memory.recall_conversations(query=task, limit=3)
            if recent.get("memories"):
                for m in recent["memories"]:
                    if m.get("relevance") is not None and m["relevance"] < 0.3:
                        continue
                    parts.append(f"- Past conversation ({m.get('role', '?')}): {m.get('content', '')[:200]}")
        except Exception:
            pass
        
        return "\n".join(parts) if parts else ""

    def _save_step_to_memory(self, task, steps, response):
        """Save agent run summary to memory after completion."""
        if not self.memory:
            return
        try:
            if steps:
                tools_used = [s.get("tool", s.get("delegated_to", "")) for s in steps if s.get("tool") or s.get("delegated_to")]
                summary = f"Task: {task[:200]} | Agent: {self.name} | Tools: {', '.join(tools_used)} | Steps: {len(steps)} | Result: {response[:200]}"
                self.memory.save_knowledge(
                    topic=f"agent_run_{self.name}",
                    content=summary,
                    source="agent_loop"
                )
        except Exception:
            pass

    # ── RAG + Skill Integration ────────────────────────────────────

    def _get_rag_context(self, task):
        """Pull relevant knowledge from RAG store."""
        if not self.learning_engine:
            return ""
        try:
            result = self.learning_engine.rag_search(task, n_results=3)
            items = result.get("results", [])
            if not items:
                return ""
            lines = []
            for item in items:
                if item.get("relevance", 0) < 0.3:
                    continue
                source = item.get("source", "")
                content = item.get("content", "")[:300]
                lines.append(f"- {content} (source: {source})")
            return "\n".join(lines) if lines else ""
        except Exception:
            return ""

    def _get_skill_context(self):
        """Get learned skill tips for this agent."""
        if not self.learning_engine:
            return ""
        try:
            return self.learning_engine._build_skill_context(self.name)
        except Exception:
            return ""

    def _record_skill_outcome(self, tool_name, tool_input, tool_result):
        """Record a tool call outcome for learning."""
        if not self.learning_engine:
            return
        try:
            action = tool_input.get("action", "") if isinstance(tool_input, dict) else ""
            is_error = isinstance(tool_result, dict) and tool_result.get("error")
            self.learning_engine.record_skill(
                agent=self.name,
                tool=tool_name,
                action=action,
                input_pattern=tool_input,
                outcome="error" if is_error else "success",
                error_msg=tool_result.get("error") if is_error else None
            )
        except Exception:
            pass
