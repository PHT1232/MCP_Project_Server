#!/bin/sh
# Container entrypoint: wait for Postgres, migrate, then serve HTTP (AC25, FR40).
set -eu
cd /app

python - <<'PY'
import os
import socket
import time
from urllib.parse import urlparse

raw = os.environ.get("PCS_DATABASE_URL", "")
parsed = urlparse(raw.replace("postgresql+psycopg", "postgresql", 1))
host = parsed.hostname or "postgres"
port = parsed.port or 5432
deadline = time.time() + 60
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit(f"postgres not reachable at {host}:{port}")
PY

alembic upgrade head
exec pcs http
