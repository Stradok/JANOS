import requests

from tools.base import BaseTool


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web. Params: query (str)"

    async def execute(self, query: str = "", **kwargs) -> str:
        if not query:
            return "No query provided."
        try:
            url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
            })
            resp.raise_for_status()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for r in soup.select(".result__body")[:5]:
                title_el = r.select_one(".result__title a")
                snippet_el = r.select_one(".result__snippet")
                if title_el:
                    title = title_el.get_text(strip=True)
                    link = title_el.get("href", "")
                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                    results.append(f"{title}\n{link}\n{snippet}\n")
            return "\n".join(results) if results else "No results found."
        except ImportError:
            return "Web search requires beautifulsoup4: pip install beautifulsoup4"
        except Exception as e:
            return f"Search error: {e}"
