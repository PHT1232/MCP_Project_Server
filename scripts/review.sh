#!/usr/bin/env bash
# review.sh TXX  — gather everything needed to review a task branch.
# Prints diffstat, saves the full diff, runs checks, runs acceptance tests,
# and prints the task's acceptance checklist + handoff.
set -euo pipefail

TASK="${1:?usage: scripts/review.sh TXX}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BRANCH="$(git branch -a --list "*task/${TASK}-*" | head -1 | sed 's/^[* ]*//; s#remotes/[^/]*/##')"
[ -n "$BRANCH" ] || { echo "no branch matching task/${TASK}-*"; exit 1; }

echo "== Task ${TASK}  branch: ${BRANCH} =="
git fetch --quiet --all || true

OUT="reviews/${TASK}.diff"
git diff "main...${BRANCH}" > "$OUT"
echo "== diffstat =="
git diff --stat "main...${BRANCH}"
echo "full diff -> ${OUT}"

echo
echo "== just check (on ${BRANCH}) =="
git stash --include-untracked --quiet || true
CURRENT="$(git branch --show-current)"
git checkout --quiet "$BRANCH"
set +e
just check
CHECK=$?
just accept "$TASK" 2>/dev/null
git checkout --quiet "$CURRENT"
git stash pop --quiet 2>/dev/null || true
set -e
echo "just check exit: ${CHECK}"

echo
echo "== acceptance checklist + handoff (tasks/${TASK}-*.md) =="
sed -n '/## Acceptance checklist/,$p' tasks/${TASK}-*.md || true
