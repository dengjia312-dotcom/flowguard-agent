from pathlib import Path
from typing import Dict, Any


class FileTools:
    """
    File operations scoped to the workspace directory.
    Path traversal attacks are blocked by _safe_path().
    """

    def __init__(self, workspace_path: str) -> None:
        self.workspace = Path(workspace_path).resolve()

    def _safe_path(self, filename: str) -> Path:
        target = (self.workspace / filename).resolve()
        if not str(target).startswith(str(self.workspace)):
            raise PermissionError(
                f"Access denied: '{filename}' resolves outside the workspace directory."
            )
        return target

    def read(self, filename: str) -> Dict[str, Any]:
        try:
            path = self._safe_path(filename)
            if not path.exists():
                return {"status": "failed", "error": f"File not found: {filename}"}
            if not path.is_file():
                return {"status": "failed", "error": f"Not a file: {filename}"}
            content = path.read_text(encoding="utf-8")
            return {
                "status": "success",
                "filename": filename,
                "content": content,
                "size_bytes": path.stat().st_size,
            }
        except PermissionError as exc:
            return {"status": "failed", "error": str(exc)}
        except Exception as exc:
            return {"status": "failed", "error": f"Read error: {exc}"}

    def write(self, filename: str, content: str) -> Dict[str, Any]:
        try:
            path = self._safe_path(filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return {
                "status": "success",
                "filename": filename,
                "bytes_written": len(content.encode("utf-8")),
            }
        except PermissionError as exc:
            return {"status": "failed", "error": str(exc)}
        except Exception as exc:
            return {"status": "failed", "error": f"Write error: {exc}"}

    def list_files(self, pattern: str = "*") -> Dict[str, Any]:
        try:
            files = [
                {"name": f.name, "size_bytes": f.stat().st_size}
                for f in self.workspace.glob(pattern)
                if f.is_file()
            ]
            return {"status": "success", "files": files, "count": len(files)}
        except Exception as exc:
            return {"status": "failed", "error": f"List error: {exc}"}
