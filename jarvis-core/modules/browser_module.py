# modules/browser_module.py
import asyncio
import os
import subprocess
import webbrowser
from .base import ModuleBase

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class BrowserModule(ModuleBase):
    """Control a real browser like a human — open pages, click, type, read content, take screenshots.
    Falls back to system browser when Playwright isn't installed."""

    def __init__(self):
        super().__init__("browser")
        self._browser = None
        self._context = None
        self._page = None

    def _ensure_browser(self):
        if not PLAYWRIGHT_AVAILABLE:
            return {"error": "playwright_not_installed"}
        if self._browser is None or not self._browser.is_connected():
            try:
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(
                    headless=False,
                    args=["--start-maximized"]
                )
                self._context = self._browser.new_context(
                    viewport=None,
                    no_viewport=True,
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                self._page = self._context.new_page()
            except Exception as e:
                return {"error": f"Failed to launch browser: {str(e)}"}
        return None

    def _get_page(self):
        if self._page is None or self._page.is_closed():
            if self._context:
                self._page = self._context.new_page()
        return self._page

    def _open_url(self, url):
        if not url.startswith("http"):
            url = "https://" + url

        # Try Playwright first
        err = self._ensure_browser()
        if err and err.get("error") == "playwright_not_installed":
            # Fallback: open in user's default browser
            try:
                webbrowser.open(url)
                return {"status": "ok", "url": url, "title": "(opened in default browser)", "method": "webbrowser"}
            except Exception as e:
                return {"error": f"Could not open URL: {e}"}
        elif err:
            return err

        try:
            page = self._get_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return {"status": "ok", "url": page.url, "title": page.title()}
        except Exception as e:
            return {"error": f"Failed to open URL: {str(e)}"}

    def _read_page(self, max_chars=3000):
        err = self._ensure_browser()
        if err:
            return {"error": "Page reading requires Playwright. Tip: pip install playwright && playwright install chromium"}
        try:
            page = self._get_page()
            text = page.inner_text("body")
            text = text.strip()
            truncated = len(text) > max_chars
            return {
                "status": "ok",
                "url": page.url,
                "title": page.title(),
                "content": text[:max_chars],
                "truncated": truncated
            }
        except Exception as e:
            return {"error": str(e)}

    def _click(self, selector):
        err = self._ensure_browser()
        if err:
            return err
        try:
            page = self._get_page()
            page.click(selector, timeout=10000)
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            return {"status": "ok", "clicked": selector, "url": page.url}
        except Exception as e:
            return {"error": f"Click failed on '{selector}': {str(e)}"}

    def _type_text(self, selector, text, press_enter=False):
        err = self._ensure_browser()
        if err:
            return err
        try:
            page = self._get_page()
            page.fill(selector, text, timeout=10000)
            if press_enter:
                page.press(selector, "Enter")
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            return {"status": "ok", "typed": text, "selector": selector, "url": page.url}
        except Exception as e:
            return {"error": f"Type failed on '{selector}': {str(e)}"}

    def _screenshot(self, path="memory/browser_screenshot.png"):
        err = self._ensure_browser()
        if err:
            return err
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            page = self._get_page()
            page.screenshot(path=path, full_page=False)
            return {"status": "ok", "saved": path}
        except Exception as e:
            return {"error": str(e)}

    def _scroll(self, direction="down", amount=500):
        err = self._ensure_browser()
        if err:
            return err
        try:
            page = self._get_page()
            scroll_y = amount if direction == "down" else -amount
            page.evaluate(f"window.scrollBy(0, {scroll_y})")
            return {"status": "ok", "scrolled": direction, "amount": amount}
        except Exception as e:
            return {"error": str(e)}

    def _new_tab(self, url=None):
        err = self._ensure_browser()
        if err:
            return err
        try:
            self._page = self._context.new_page()
            if url:
                if not url.startswith("http"):
                    url = "https://" + url
                self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return {"status": "ok", "message": "New tab opened", "url": self._page.url if url else "about:blank"}
        except Exception as e:
            return {"error": str(e)}

    def _close_tab(self):
        try:
            if self._page and not self._page.is_closed():
                self._page.close()
            pages = self._context.pages if self._context else []
            self._page = pages[-1] if pages else None
            return {"status": "ok", "message": "Tab closed"}
        except Exception as e:
            return {"error": str(e)}

    def _list_tabs(self):
        err = self._ensure_browser()
        if err:
            return err
        try:
            tabs = []
            for i, page in enumerate(self._context.pages):
                tabs.append({"index": i, "url": page.url, "title": page.title()})
            return {"status": "ok", "tabs": tabs, "count": len(tabs)}
        except Exception as e:
            return {"error": str(e)}

    def _switch_tab(self, index):
        err = self._ensure_browser()
        if err:
            return err
        try:
            pages = self._context.pages
            if 0 <= index < len(pages):
                self._page = pages[index]
                self._page.bring_to_front()
                return {"status": "ok", "switched_to": index, "url": self._page.url}
            return {"error": f"Tab index {index} out of range (0-{len(pages)-1})"}
        except Exception as e:
            return {"error": str(e)}

    def _get_links(self, max_links=20):
        err = self._ensure_browser()
        if err:
            return err
        try:
            page = self._get_page()
            links = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href]')).slice(0, %d).map(a => ({
                    text: a.innerText.trim().substring(0, 100),
                    href: a.href
                })).filter(l => l.text && l.href.startsWith('http'));
            }""" % max_links)
            return {"status": "ok", "links": links, "count": len(links)}
        except Exception as e:
            return {"error": str(e)}

    def _click_link_by_text(self, link_text):
        """Click a link by its visible text (partial match, case-insensitive)."""
        err = self._ensure_browser()
        if err:
            return err
        try:
            page = self._get_page()
            # try exact match first, then partial
            link = page.get_by_role("link", name=link_text).first
            if link and link.is_visible():
                link.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                return {"status": "ok", "clicked_link": link_text, "url": page.url, "title": page.title()}
            # fallback: find by text content
            link = page.locator(f"a:has-text('{link_text}')").first
            if link and link.is_visible():
                link.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                return {"status": "ok", "clicked_link": link_text, "url": page.url, "title": page.title()}
            return {"error": f"No visible link found with text '{link_text}'"}
        except Exception as e:
            return {"error": f"Failed to click link '{link_text}': {str(e)}"}

    def _close_browser(self):
        try:
            if self._browser:
                self._browser.close()
            if hasattr(self, '_pw') and self._pw:
                self._pw.stop()
            self._browser = None
            self._context = None
            self._page = None
            return {"status": "ok", "message": "Browser closed"}
        except Exception as e:
            return {"error": str(e)}

    def process(self, input_data):
        action = input_data.get("action", "open")
        url = input_data.get("url", "")
        selector = input_data.get("selector", "")
        text = input_data.get("text", "")

        if action == "open":
            if not url:
                return {"error": "Missing 'url' to open"}
            return self._open_url(url)
        elif action == "read":
            return self._read_page(input_data.get("max_chars", 3000))
        elif action == "click":
            if not selector:
                return {"error": "Missing 'selector' to click"}
            return self._click(selector)
        elif action == "type":
            if not selector:
                return {"error": "Missing 'selector' to type into"}
            return self._type_text(selector, text, input_data.get("press_enter", False))
        elif action == "screenshot":
            return self._screenshot(input_data.get("path", "memory/browser_screenshot.png"))
        elif action == "scroll":
            return self._scroll(input_data.get("direction", "down"), input_data.get("amount", 500))
        elif action == "new_tab":
            return self._new_tab(url)
        elif action == "close_tab":
            return self._close_tab()
        elif action == "list_tabs":
            return self._list_tabs()
        elif action == "switch_tab":
            return self._switch_tab(input_data.get("index", 0))
        elif action == "get_links":
            return self._get_links(input_data.get("max_links", 20))
        elif action == "click_link":
            link_text = input_data.get("link_text", "")
            if not link_text:
                return {"error": "Missing 'link_text' — the visible text of the link to click"}
            return self._click_link_by_text(link_text)
        elif action == "close_browser":
            return self._close_browser()
        else:
            return {"error": f"Unknown action: {action}. Use: open, read, click, type, screenshot, scroll, new_tab, close_tab, list_tabs, switch_tab, get_links, close_browser"}
