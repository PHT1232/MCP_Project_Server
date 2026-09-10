"""Serve the built Vite frontend from the same HTTP process (NFR13, FR40)."""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles

from pcs.config import get_settings


def register_frontend(app: Starlette) -> None:
    """Mount ``/assets`` and ``/`` from ``PCS_STATIC_DIR`` when the dir exists.

    Missing dir is a no-op so unit tests and stdio-only runs stay unchanged (FR42).
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

    async def index_page(_request: object) -> Response:
        return FileResponse(index)

    app.add_route("/", index_page, methods=["GET"])
