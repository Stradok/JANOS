# modules/youtube_module.py
import json
import requests
from .base import ModuleBase

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class YouTubeModule(ModuleBase):
    """Search YouTube, find the best video, and play it — like a human would."""

    OLLAMA_URL = "http://localhost:11434/api/chat"

    def __init__(self):
        super().__init__("youtube")

    def _search_youtube(self, query, max_results=5):
        """Search YouTube and extract video results. Falls back to direct URL."""
        if not PLAYWRIGHT_AVAILABLE:
            # Fallback: open YouTube search in system browser
            import webbrowser
            search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            webbrowser.open(search_url)
            return [{"title": query, "url": search_url, "channel": "YouTube Search", "views": ""}], None
        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            page = ctx.new_page()

            search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)  # let JS render

            videos = page.evaluate("""(maxResults) => {
                const items = document.querySelectorAll('ytd-video-renderer, ytd-rich-item-renderer');
                const results = [];
                for (let i = 0; i < Math.min(items.length, maxResults); i++) {
                    const item = items[i];
                    const titleEl = item.querySelector('#video-title');
                    const channelEl = item.querySelector('#channel-name a, .ytd-channel-name a, #text.ytd-channel-name');
                    const viewsEl = item.querySelector('#metadata-line span');
                    if (titleEl && titleEl.href) {
                        results.push({
                            title: titleEl.innerText.trim(),
                            url: titleEl.href,
                            channel: channelEl ? channelEl.innerText.trim() : 'Unknown',
                            views: viewsEl ? viewsEl.innerText.trim() : '',
                        });
                    }
                }
                return results;
            }""", max_results)

            browser.close()
            pw.stop()
            return videos, None
        except Exception as e:
            return None, str(e)

    def _pick_best_video(self, query, videos):
        """Ask LLM to pick the best video from search results."""
        if not videos:
            return None

        video_list = "\n".join(
            f"{i+1}. \"{v['title']}\" by {v['channel']} ({v['views']}) — {v['url']}"
            for i, v in enumerate(videos)
        )

        prompt = f"""The user wants: "{query}"

Here are YouTube search results:
{video_list}

Pick the BEST video for the user's needs. Consider relevance, views, and channel quality.
Respond with ONLY a JSON object: {{"pick": <number 1-{len(videos)}>, "reason": "brief reason"}}"""

        try:
            resp = requests.post(self.OLLAMA_URL, json={
                "model": "llama3.1:8b",
                "messages": [
                    {"role": "system", "content": "You pick the best YouTube video. Respond ONLY with JSON."},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 128}
            }, timeout=60)
            data = resp.json()
            text = data["message"]["content"].strip()
            # parse JSON from response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                result = json.loads(text[start:end])
                pick = result.get("pick", 1) - 1
                if 0 <= pick < len(videos):
                    return {"video": videos[pick], "reason": result.get("reason", "")}
            return {"video": videos[0], "reason": "Top result"}
        except Exception:
            return {"video": videos[0], "reason": "Top result (LLM unavailable)"}

    def _play_video(self, url):
        """Open a YouTube video — Playwright for ad handling, or system browser as fallback."""
        if not url.startswith("http"):
            url = "https://" + url

        if not PLAYWRIGHT_AVAILABLE:
            # Fallback: open in user's default browser
            import webbrowser
            try:
                webbrowser.open(url)
                return {"status": "ok", "message": "Opened video in browser", "url": url, "method": "webbrowser"}
            except Exception:
                import os
                os.startfile(url)
                return {"status": "ok", "message": "Opened video in browser", "url": url, "method": "startfile"}

        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(
                headless=False,
                args=["--start-maximized"]
            )
            ctx = browser.new_context(
                no_viewport=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            self._skip_ads(page)
            self._pw = pw
            self._browser = browser
            self._page = page
            return {"status": "ok", "message": "Playing video (ads handled)", "url": url}
        except Exception as e:
            return {"error": str(e)}

    def _skip_ads(self, page):
        """Wait for and skip YouTube ads if they appear."""
        import time

        for attempt in range(15):  # try for ~30 seconds
            try:
                # check for "Skip Ad" / "Skip Ads" button
                skip_btn = page.query_selector(
                    "button.ytp-skip-ad-button, "
                    "button.ytp-ad-skip-button, "
                    "button.ytp-ad-skip-button-modern, "
                    "[class*='skip-button'], "
                    ".ytp-skip-ad .ytp-skip-ad-button"
                )
                if skip_btn and skip_btn.is_visible():
                    skip_btn.click()
                    time.sleep(1)
                    return  # ad skipped

                # check if ad is playing (ad overlay visible but no skip button yet)
                ad_playing = page.query_selector(
                    ".ytp-ad-player-overlay, "
                    ".ytp-ad-text, "
                    "[class*='ad-showing']"
                )
                if not ad_playing:
                    return  # no ad, video is playing

                time.sleep(2)  # wait for skip button to appear
            except Exception:
                time.sleep(2)
                continue

    def process(self, input_data):
        action = input_data.get("action", "search_and_play")
        query = input_data.get("query", "")
        url = input_data.get("url", "")
        max_results = input_data.get("max_results", 5)

        if action == "search":
            if not query:
                return {"error": "Missing 'query' to search YouTube"}
            videos, err = self._search_youtube(query, max_results)
            if err:
                return {"error": f"YouTube search failed: {err}"}
            return {"status": "ok", "query": query, "results": videos or []}

        elif action == "search_and_play":
            if not query:
                return {"error": "Missing 'query' to search YouTube"}
            videos, err = self._search_youtube(query, max_results)
            if err:
                return {"error": f"YouTube search failed: {err}"}
            if not videos:
                return {"status": "ok", "query": query, "results": [], "message": "No videos found"}

            best = self._pick_best_video(query, videos)
            if best and best.get("video"):
                play_result = self._play_video(best["video"]["url"])
                return {
                    "status": "ok",
                    "query": query,
                    "picked": best["video"],
                    "reason": best.get("reason", ""),
                    "play": play_result,
                    "all_results": videos
                }
            return {"status": "ok", "query": query, "results": videos, "message": "Could not pick best video"}

        elif action == "play":
            if not url:
                return {"error": "Missing 'url' to play"}
            return self._play_video(url)

        else:
            return {"error": f"Unknown action: {action}. Use: search, search_and_play, play"}
