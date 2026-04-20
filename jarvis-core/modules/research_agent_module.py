# modules/research_agent_module.py
"""
Web Research Agent — JAN's ability to learn from the internet.
When JAN doesn't know something, it can:
1. Search DuckDuckGo for quick answers
2. Open ChatGPT in a browser and ask like a human
3. Open Google Gemini in a browser and ask like a human
4. Read and extract answers from web pages
5. Save learned knowledge to long-term memory
"""
import json
import time
import requests
from .base import ModuleBase

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class ResearchAgentModule(ModuleBase):
    """JAN's internet research brain — searches, reads, and learns like a human."""

    OLLAMA_URL = "http://localhost:11434/api/chat"

    # Research strategies in priority order
    STRATEGIES = ["duckduckgo", "chatgpt", "gemini"]

    def __init__(self):
        super().__init__("research_agent")
        self.memory = None  # will be wired from __init__.py
        self._browser = None
        self._pw = None

    def _get_browser(self, headless=True):
        """Get or create a headless browser for research."""
        if not PLAYWRIGHT_AVAILABLE:
            return None, "Playwright not installed. Run: pip install playwright && playwright install chromium"
        try:
            if self._browser is None or not self._browser.is_connected():
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(headless=headless)
            return self._browser, None
        except Exception as e:
            return None, str(e)

    def _close_browser(self):
        """Clean up browser resources."""
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._pw = None

    # ========================
    # Strategy 1: DuckDuckGo
    # ========================
    def _search_duckduckgo(self, query, max_results=5):
        """Quick web search via DuckDuckGo HTML lite."""
        browser, err = self._get_browser(headless=True)
        if err:
            return None, err
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()
            page.goto(f"https://html.duckduckgo.com/html/?q={query}",
                      wait_until="domcontentloaded", timeout=20000)

            results = page.evaluate("""(maxResults) => {
                const items = document.querySelectorAll('.result');
                const results = [];
                for (let i = 0; i < Math.min(items.length, maxResults); i++) {
                    const item = items[i];
                    const titleEl = item.querySelector('.result__a');
                    const snippetEl = item.querySelector('.result__snippet');
                    if (titleEl) {
                        results.push({
                            title: titleEl.innerText.trim(),
                            url: titleEl.href,
                            snippet: snippetEl ? snippetEl.innerText.trim() : ''
                        });
                    }
                }
                return results;
            }""", max_results)

            # Read top result page for more context
            top_page_content = ""
            if results:
                try:
                    page.goto(results[0]["url"], wait_until="domcontentloaded", timeout=15000)
                    top_page_content = page.inner_text("body")[:3000]
                except Exception:
                    pass

            context.close()
            return {
                "results": results,
                "top_page_content": top_page_content
            }, None
        except Exception as e:
            return None, str(e)

    # ========================
    # Strategy 2: ChatGPT
    # ========================
    def _ask_chatgpt(self, question):
        """Open ChatGPT in browser and ask a question like a human."""
        browser, err = self._get_browser(headless=False)
        if err:
            return None, err
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto("https://chatgpt.com", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Find the message input and type
            typed = False
            selectors = [
                "#prompt-textarea",
                "textarea[placeholder*='Message']",
                "textarea",
                "[contenteditable='true']",
            ]
            for sel in selectors:
                try:
                    el = page.locator(sel).first
                    if el and el.is_visible(timeout=3000):
                        el.click()
                        el.fill(question)
                        typed = True
                        break
                except Exception:
                    continue

            if not typed:
                context.close()
                return None, "Could not find ChatGPT input field"

            # Press Enter to send
            page.keyboard.press("Enter")

            # Wait for response to generate (watch for the stop button to appear then disappear)
            time.sleep(5)
            # Wait up to 60 seconds for response
            for _ in range(30):
                try:
                    # Check if response is still generating
                    stop_btn = page.locator("button[aria-label='Stop generating']").first
                    if stop_btn and stop_btn.is_visible(timeout=1000):
                        time.sleep(2)
                        continue
                except Exception:
                    pass
                break

            time.sleep(2)

            # Extract the last assistant message
            response_text = page.evaluate("""() => {
                const messages = document.querySelectorAll('[data-message-author-role="assistant"]');
                if (messages.length > 0) {
                    return messages[messages.length - 1].innerText.trim();
                }
                // fallback: try to find response blocks
                const blocks = document.querySelectorAll('.markdown, .prose, [class*="response"]');
                if (blocks.length > 0) {
                    return blocks[blocks.length - 1].innerText.trim();
                }
                return '';
            }""")

            context.close()

            if response_text:
                return {"source": "chatgpt", "answer": response_text[:5000]}, None
            return None, "ChatGPT did not produce a response"
        except Exception as e:
            return None, f"ChatGPT error: {str(e)}"

    # ========================
    # Strategy 3: Google Gemini
    # ========================
    def _ask_gemini(self, question):
        """Open Google Gemini in browser and ask a question."""
        browser, err = self._get_browser(headless=False)
        if err:
            return None, err
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto("https://gemini.google.com", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Find input and type question
            typed = False
            selectors = [
                ".ql-editor",
                "[contenteditable='true']",
                "textarea",
                "rich-textarea .ql-editor",
            ]
            for sel in selectors:
                try:
                    el = page.locator(sel).first
                    if el and el.is_visible(timeout=3000):
                        el.click()
                        el.fill(question) if sel == "textarea" else el.type(question, delay=30)
                        typed = True
                        break
                except Exception:
                    continue

            if not typed:
                context.close()
                return None, "Could not find Gemini input field"

            # Send message
            page.keyboard.press("Enter")

            # Wait for response
            time.sleep(8)
            for _ in range(25):
                try:
                    # Check if still generating
                    loading = page.locator("[class*='loading'], [class*='pending'], .thinking-indicator").first
                    if loading and loading.is_visible(timeout=1000):
                        time.sleep(2)
                        continue
                except Exception:
                    pass
                break

            time.sleep(2)

            # Extract response
            response_text = page.evaluate("""() => {
                const responses = document.querySelectorAll('.model-response-text, .response-content, [class*="message-content"]');
                if (responses.length > 0) {
                    return responses[responses.length - 1].innerText.trim();
                }
                // broader fallback
                const markdown = document.querySelectorAll('.markdown-main-panel, .response-container');
                if (markdown.length > 0) {
                    return markdown[markdown.length - 1].innerText.trim();
                }
                return '';
            }""")

            context.close()

            if response_text:
                return {"source": "gemini", "answer": response_text[:5000]}, None
            return None, "Gemini did not produce a response"
        except Exception as e:
            return None, f"Gemini error: {str(e)}"

    # ========================
    # LLM Summary
    # ========================
    def _summarize_research(self, question, raw_data):
        """Use local LLM to distill research into a clean answer."""
        context_text = f"Question: {question}\n\n"

        if isinstance(raw_data, dict):
            if "results" in raw_data:
                context_text += "Web search results:\n"
                for i, r in enumerate(raw_data["results"][:5], 1):
                    context_text += f"  {i}. {r['title']}: {r['snippet']}\n"
                if raw_data.get("top_page_content"):
                    context_text += f"\nTop result content:\n{raw_data['top_page_content'][:2000]}\n"
            if "answer" in raw_data:
                context_text += f"\nAI answer from {raw_data.get('source', 'web')}:\n{raw_data['answer'][:3000]}\n"

        try:
            resp = requests.post(self.OLLAMA_URL, json={
                "model": "llama3.1:8b",
                "messages": [
                    {"role": "system", "content": "You are JAN's research assistant. Distill the research data into a clear, concise, accurate answer. Include key facts. Keep it under 300 words."},
                    {"role": "user", "content": context_text}
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 512}
            }, timeout=120)
            return resp.json()["message"]["content"]
        except Exception:
            # return raw data if LLM fails
            if isinstance(raw_data, dict) and "answer" in raw_data:
                return raw_data["answer"][:1000]
            return str(raw_data)[:1000]

    # ========================
    # Main Research Pipeline
    # ========================
    def research(self, question, strategy="auto", save_to_memory=True):
        """
        Research a question using the internet.
        strategy: 'auto' (try all), 'duckduckgo', 'chatgpt', 'gemini'
        """
        results = {
            "question": question,
            "strategy_used": None,
            "answer": None,
            "raw_source": None,
            "saved_to_memory": False,
            "errors": []
        }

        strategies = self.STRATEGIES if strategy == "auto" else [strategy]

        for strat in strategies:
            raw_data, err = None, None

            if strat == "duckduckgo":
                raw_data, err = self._search_duckduckgo(question)
            elif strat == "chatgpt":
                raw_data, err = self._ask_chatgpt(question)
            elif strat == "gemini":
                raw_data, err = self._ask_gemini(question)

            if err:
                results["errors"].append(f"{strat}: {err}")
                continue

            if raw_data:
                # Got data — summarize it
                answer = self._summarize_research(question, raw_data)
                results["strategy_used"] = strat
                results["answer"] = answer
                results["raw_source"] = strat

                # Save to long-term memory
                if save_to_memory and self.memory:
                    try:
                        self.memory.save_knowledge(
                            topic=question,
                            content=answer,
                            source=f"research_agent:{strat}"
                        )
                        results["saved_to_memory"] = True
                    except Exception:
                        pass

                results["status"] = "ok"
                return results

        # All strategies failed
        results["status"] = "failed"
        results["answer"] = f"I couldn't find an answer to '{question}'. Errors: {results['errors']}"
        return results

    def _read_url(self, url, max_chars=5000):
        """Read a specific URL and extract its content."""
        browser, err = self._get_browser(headless=True)
        if err:
            return {"error": err}
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            title = page.title()
            content = page.inner_text("body")[:max_chars]
            context.close()
            return {"status": "ok", "title": title, "url": url, "content": content}
        except Exception as e:
            return {"error": f"Failed to read {url}: {str(e)}"}

    def process(self, input_data):
        action = input_data.get("action", "research")
        question = input_data.get("question", input_data.get("query", ""))
        strategy = input_data.get("strategy", "auto")
        save = input_data.get("save_to_memory", True)

        if action == "research":
            if not question:
                return {"error": "Missing 'question' to research"}
            return self.research(question, strategy=strategy, save_to_memory=save)

        elif action == "search_web":
            if not question:
                return {"error": "Missing 'question' to search"}
            data, err = self._search_duckduckgo(question)
            if err:
                return {"error": err}
            return {"status": "ok", "results": data}

        elif action == "ask_chatgpt":
            if not question:
                return {"error": "Missing 'question' to ask ChatGPT"}
            data, err = self._ask_chatgpt(question)
            if err:
                return {"error": err}
            return {"status": "ok", **data}

        elif action == "ask_gemini":
            if not question:
                return {"error": "Missing 'question' to ask Gemini"}
            data, err = self._ask_gemini(question)
            if err:
                return {"error": err}
            return {"status": "ok", **data}

        elif action == "read_url":
            url = input_data.get("url", "")
            if not url:
                return {"error": "Missing 'url' to read"}
            return self._read_url(url, input_data.get("max_chars", 5000))

        elif action == "check_memory_first":
            # Check if we already know the answer before researching
            if not question:
                return {"error": "Missing 'question'"}
            if self.memory:
                existing = self.memory.search_knowledge(question, limit=3)
                if existing.get("results") and len(existing["results"]) > 0:
                    top = existing["results"][0]
                    if top.get("relevance", 0) > 0.6:
                        return {
                            "status": "ok",
                            "answer": top["content"],
                            "source": "memory",
                            "relevance": top["relevance"],
                            "researched": False
                        }
            # Not in memory — research it
            return self.research(question, strategy=strategy, save_to_memory=save)

        else:
            return {"error": f"Unknown action: {action}. Use: research, search_web, ask_chatgpt, ask_gemini, read_url, check_memory_first"}
