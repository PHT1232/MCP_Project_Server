"""Container health probe that uses the real bind address (FR41, AC26)."""

from __future__ import annotations

import urllib.error
import urllib.request

from pcs.config import get_settings


def main() -> None:
    """GET /api/health on bind_host:port; exit 1 on failure."""
    settings = get_settings()
    url = f"http://{settings.bind_host}:{settings.port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status != 200:
                raise SystemExit(1)
    except (urllib.error.URLError, OSError, TimeoutError):
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
