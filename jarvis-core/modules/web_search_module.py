# modules/web_search_module.py
import json
import re
import webbrowser
import urllib.parse
import requests
from .base import ModuleBase

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class WebSearchModule(ModuleBase):
    """Search the web using DuckDuckGo (no API key needed)."""

    OLLAMA_URL = "http://localhost:11434/api/chat"

    def __init__(self):
        super().__init__("web_search")

    # ── DuckDuckGo HTML search via requests (no API key, no Playwright) ──
    def _search_ddg_api(self, query, max_results=5):
        """Scrape DuckDuckGo HTML lite page via requests (no JS needed)."""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
            url = "https://html.duckduckgo.com/html/"
            resp = requests.post(url, data={"q": query}, headers=headers, timeout=15)
            resp.raise_for_status()
            html = resp.text

            results = []
            strip_tags = lambda s: re.sub(r'<[^>]+>', '', s).strip()

            # Extract title links
            titles = re.findall(
                r'class="result__a"\s+href="([^"]*)"[^>]*>(.*?)</a>',
                html, re.DOTALL
            )
            # Extract snippets
            snippets = re.findall(
                r'class="result__snippet"[^>]*>(.*?)</a>',
                html, re.DOTALL
            )

            for i, (href, title_html) in enumerate(titles[:max_results]):
                actual = href
                m = re.search(r'uddg=([^&]+)', href)
                if m:
                    actual = urllib.parse.unquote(m.group(1))
                snippet = strip_tags(snippets[i]) if i < len(snippets) else ""
                results.append({
                    "title": strip_tags(title_html),
                    "url": actual,
                    "snippet": snippet
                })
            return results, None
        except Exception as e:
            return None, str(e)

    def _search_duckduckgo(self, query, max_results=5):
        """Search DuckDuckGo — tries requests first, falls back to Playwright."""
        # Try lightweight approach first (no Playwright needed)
        results, err = self._search_ddg_api(query, max_results)
        if results:
            return results, None

        # Fall back to Playwright if available
        if not PLAYWRIGHT_AVAILABLE:
            # Last resort: open in browser for user
            search_url = f"https://duckduckgo.com/?q={urllib.parse.quote_plus(query)}"
            webbrowser.open(search_url)
            return None, f"Opened search in browser: {search_url}"

        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()

            search_url = f"https://html.duckduckgo.com/html/?q={query}"
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)

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

            browser.close()
            pw.stop()
            return results, None
        except Exception as e:
            return None, str(e)

    def _read_page_content(self, url, max_chars=3000):
        """Fetch and read a web page's text content."""
        # Try simple requests approach first (works for many pages)
        try:
            headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            html = resp.text
            title_m = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
            title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else url
            # Strip tags for text content
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()[:max_chars]
            if len(text) > 200:
                return {"title": title, "url": url, "content": text}, None
        except Exception:
            pass

        # Fall back to Playwright if available
        if not PLAYWRIGHT_AVAILABLE:
            return None, "Could not read page content"
        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)

            content = page.inner_text("body")
            title = page.title()
            browser.close()
            pw.stop()

            content = content.strip()[:max_chars]
            return {"title": title, "url": url, "content": content}, None
        except Exception as e:
            return None, str(e)

    def _summarize_with_llm(self, query, search_results, page_content=None):
        """Ask the LLM to summarize search results into a helpful answer."""
        context = f"User asked: {query}\n\nSearch results:\n"
        for i, r in enumerate(search_results, 1):
            context += f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}\n\n"

        if page_content:
            context += f"\nDetailed content from top result ({page_content['url']}):\n{page_content['content'][:2000]}\n"

        prompt = f"""{context}

Based on the search results above, provide a concise, helpful answer to the user's question: "{query}"
Include relevant details and mention sources. Keep it conversational."""

        try:
            resp = requests.post(self.OLLAMA_URL, json={
                "model": "qwen2.5:7b-instruct",
                "messages": [
                    {"role": "system", "content": "You are Jarvis, a helpful AI assistant. Summarize web search results concisely and conversationally. Cite sources."},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "options": {"temperature": 0.5, "num_predict": 512}
            }, timeout=120)
            data = resp.json()
            return data["message"]["content"]
        except Exception as e:
            return f"Search found results but I couldn't summarize them: {str(e)}"

    def process(self, input_data):
        action = input_data.get("action", "search")
        query = input_data.get("query", "")
        url = input_data.get("url", "")
        max_results = input_data.get("max_results", 5)
        summarize = input_data.get("summarize", True)

        if action == "search":
            if not query:
                return {"error": "Missing 'query' to search for"}

            results, err = self._search_duckduckgo(query, max_results)
            if err:
                return {"error": f"Search failed: {err}"}
            if not results:
                return {"status": "ok", "query": query, "results": [], "summary": "No results found."}

            # optionally read top result for more detail
            page_content = None
            if results and summarize:
                page_content, _ = self._read_page_content(results[0]["url"])

            summary = ""
            if summarize:
                summary = self._summarize_with_llm(query, results, page_content)

            return {
                "status": "ok",
                "query": query,
                "results": results,
                "summary": summary,
            }

        elif action == "read_page":
            if not url:
                return {"error": "Missing 'url' to read"}
            content, err = self._read_page_content(url, input_data.get("max_chars", 3000))
            if err:
                return {"error": f"Failed to read page: {err}"}
            return {"status": "ok", **content}

        else:
            return {"error": f"Unknown action: {action}. Use: search, read_page"}
