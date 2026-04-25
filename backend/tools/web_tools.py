from typing import Dict, Any


class WebTools:
    """
    Web search tool.

    TODO (v0.2): Replace mock with a real search API integration.
    Candidates: Tavily (tavily.com), Bing Search API, SerpAPI, Brave Search API.
    The interface (search method signature and return format) will stay the same.
    """

    def search(self, query: str) -> Dict[str, Any]:
        # TODO: Integrate real web search API (Tavily / Bing / SerpAPI / Brave)
        return {
            "status": "success",
            "query": query,
            "results": [
                {
                    "title": "[MOCK] Web search is not implemented in v0.1",
                    "url": "https://example.com/placeholder",
                    "snippet": (
                        "This is a mock result. Real web search will be added in v0.2. "
                        "To enable: implement WebTools.search() with your chosen search API."
                    ),
                }
            ],
            "_note": "TODO: v0.2 — connect to real search API (Tavily recommended)",
        }
