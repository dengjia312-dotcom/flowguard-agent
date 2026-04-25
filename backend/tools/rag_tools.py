from pathlib import Path
from typing import Dict, Any, List


class RAGTools:
    """
    Keyword-based retrieval across workspace files.

    TODO (v0.2): Replace with embedding-based semantic search once the
    'embedding' model role is wired up in ModelRouter. The interface
    (search method signature and return format) will remain the same,
    making the upgrade transparent to AgentRuntime.
    """

    SUPPORTED_EXTENSIONS = ["*.md", "*.txt", "*.json"]

    def __init__(self, workspace_path: str) -> None:
        self.workspace = Path(workspace_path)

    def search(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        """
        Keyword search across workspace markdown, txt, and JSON files.

        Returns ranked results with matched keywords and text snippets.
        Score = fraction of query keywords found in the document.
        """
        try:
            if not query.strip():
                return {"status": "failed", "error": "Query cannot be empty"}

            keywords = [kw.lower() for kw in query.split() if len(kw) > 1]
            if not keywords:
                return {"status": "failed", "error": "No usable keywords extracted from query"}

            results = []
            for ext in self.SUPPORTED_EXTENSIONS:
                for file_path in self.workspace.glob(ext):
                    try:
                        content = file_path.read_text(encoding="utf-8")
                    except Exception:
                        continue

                    content_lower = content.lower()
                    matched = [kw for kw in keywords if kw in content_lower]
                    if not matched:
                        continue

                    score = len(matched) / len(keywords)
                    snippets = self._extract_snippets(content, matched)
                    results.append(
                        {
                            "file": file_path.name,
                            "score": round(score, 3),
                            "matched_keywords": matched,
                            "snippets": snippets[:2],
                        }
                    )

            results.sort(key=lambda x: x["score"], reverse=True)
            return {
                "status": "success",
                "query": query,
                "results": results[:top_k],
                "total_found": len(results),
                "_note": "v0.1: keyword search. TODO: upgrade to embedding-based RAG in v0.2",
            }
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}

    def _extract_snippets(
        self, content: str, keywords: List[str], snippet_len: int = 200
    ) -> List[str]:
        snippets = []
        content_lower = content.lower()
        for kw in keywords:
            idx = content_lower.find(kw)
            if idx < 0:
                continue
            start = max(0, idx - 60)
            end = min(len(content), idx + snippet_len)
            snippet = content[start:end].strip()
            if snippet and snippet not in snippets:
                snippets.append(snippet)
        return snippets
