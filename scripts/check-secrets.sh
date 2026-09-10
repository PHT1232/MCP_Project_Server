#!/bin/sh
# Fail when tracked files include local env/credential files or selected live-secret formats.
set -eu

repo_root=$(git rev-parse --show-toplevel) || {
    printf '%s\n' 'Secret scan failed: cannot locate the Git worktree.' >&2
    exit 2
}
cd "$repo_root"

git ls-files > "${TMPDIR:-/tmp}/pcs-secret-files.$$" || {
    printf '%s\n' 'Secret scan failed: cannot list tracked files.' >&2
    exit 2
}
trap 'rm -f "${TMPDIR:-/tmp}/pcs-secret-files.$$" "${TMPDIR:-/tmp}/pcs-secret-findings.$$"' EXIT HUP INT TERM

if grep -E -i '(^|/)\.env($|\.)|\.(pem|key|p12|pfx)$|(^|/)id_(rsa|dsa|ecdsa|ed25519)($|\.)|(^|/)\.ssh/|(^|/)secrets/' "${TMPDIR:-/tmp}/pcs-secret-files.$$" \
    | grep -E -v '(^|/)\.env\.example$' > "${TMPDIR:-/tmp}/pcs-secret-findings.$$"; then
    printf '%s\n' 'Tracked environment or credential files detected:' >&2
    cat "${TMPDIR:-/tmp}/pcs-secret-findings.$$" >&2
    exit 1
else
    status=$?
    if [ "$status" -ne 1 ]; then
        printf '%s\n' 'Secret scan failed while checking tracked filenames.' >&2
        exit 2
    fi
fi

# Scan tracked text for selected high-confidence formats. This is a focused
# regression gate, not an entropy-based replacement for a dedicated secret scanner.
if git grep -n -I -E 'AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|sk-[A-Za-z0-9_-]{32,}|tskey-(auth|client)-[A-Za-z0-9_-]{20,}' -- ':!server/uv.lock' ':!web/package-lock.json' > "${TMPDIR:-/tmp}/pcs-secret-findings.$$"; then
    printf '%s\n' 'Likely secrets detected in tracked content:' >&2
    cat "${TMPDIR:-/tmp}/pcs-secret-findings.$$" >&2
    exit 1
else
    status=$?
    if [ "$status" -ne 1 ]; then
        printf '%s\n' 'Secret scan failed while checking tracked content.' >&2
        exit 2
    fi
fi

printf '%s\n' 'Secret scan passed: no tracked local env/credential files or selected live-secret formats.'
