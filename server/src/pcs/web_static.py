"""Serve the built Vite frontend from the same HTTP process (NFR13, FR40)."""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles

from pcs.config import get_settings

# Prefixes owned by the API / MCP transport — never served the SPA shell.
_RESERVED: tuple[str, ...] = ("/api/", "/mcp", "/assets/")


def register_frontend(app: Starlette) -> None:
    """Mount ``/assets`` and an SPA shell from ``PCS_STATIC_DIR`` when it exists.

    Missing dir is a no-op so unit tests and stdio-only runs stay unchanged (FR42).
    A catch-all GET falls back to ``index.html`` so client-side routes
    (``/projects/x``) work on reload — API/MCP paths are excluded.
    """
    raw = get_settings().static_dir.strip()
    if not raw:
        return
    root = Path(raw)
    index = root / "index.html"
    if not root.is_dir() or not index.is_file():
        return
    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="web-assets")

    async def spa_shell(request: Request) -> Response:
        path = request.url.path
        if any(path == p.rstrip("/") or path.startswith(p) for p in _RESERVED):
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(index)

    app.add_route("/", spa_shell, methods=["GET"])
    app.add_route("/{path:path}", spa_shell, methods=["GET"])
