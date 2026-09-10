#!/bin/sh
# Fail when tracked files include local env/credential files or likely live secrets.
set -eu

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

bad_files=$(git ls-files | grep -E '(^|/)\.env($|\.)|\.(pem|key|p12|pfx)$|(^|/)id_rsa($|\.)|(^|/)\.ssh/|(^|/)secrets/' | grep -v -E '^\.env\.example$' || true)
if [ -n "$bad_files" ]; then
    printf '%s\n' 'Tracked environment or credential files detected:' >&2
    printf '%s\n' "$bad_files" >&2
    exit 1
fi

# Scan tracked text only. Patterns require realistic lengths and avoid the
# deliberately abbreviated examples used in deployment documentation.
findings=$(git grep -n -I -E 'AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|sk-[A-Za-z0-9_-]{32,}|tskey-(auth|client)-[A-Za-z0-9_-]{20,}' -- ':!server/uv.lock' ':!web/package-lock.json' || true)
if [ -n "$findings" ]; then
    printf '%s\n' 'Likely secrets detected in tracked content:' >&2
    printf '%s\n' "$findings" >&2
    exit 1
fi

printf '%s\n' 'Secret scan passed: no tracked local env/credential files or likely live secrets.'
