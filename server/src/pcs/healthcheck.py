"""Container health probe (FR40, AC25).

Runs inside the container, so it connects over loopback regardless of the bind
address (which may be ``0.0.0.0`` or a tailnet IP). A ``0.0.0.0`` bind still
accepts loopback connections; a tailnet bind is also reachable from within the
container's network namespace via ``127.0.0.1`` only when it also binds
loopback, so probe the bind host directly in that case.
"""

from __future__ import annotations

import urllib.error
import urllib.request

from pcs.bind import is_wildcard
from pcs.config import get_settings


def main() -> None:
    """GET /api/health over loopback (or the tailnet bind); exit 1 on failure."""
    settings = get_settings()
    bind = settings.bind_host
    target = "127.0.0.1" if (bind == "127.0.0.1" or is_wildcard(bind)) else bind
    url = f"http://{target}:{settings.port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status != 200:
                raise SystemExit(1)
    except (urllib.error.URLError, OSError, TimeoutError):
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
