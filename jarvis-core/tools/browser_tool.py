import requests

from tools.base import BaseTool


class BrowserTool(BaseTool):
    name = "browser"
    description = "Fetch a URL and return its text content. Params: url (str)"

    async def execute(self, url: str = "", **kwargs) -> str:
        if not url:
            return "No URL provided."
        try:
            resp = requests.get(url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
            })
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "text" in ct or "html" in ct or "json" in ct:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                for t in soup.select("script, style, nav, footer, header"):
                    t.decompose()
                text = soup.get_text(separator="\n", strip=True)
                return text[:3000]
            return f"Fetched {url} ({len(resp.content)} bytes, type: {ct})"
        except ImportError:
            return "Browser tool requires beautifulsoup4"
        except Exception as e:
            return f"Browser error: {e}"
