#!/usr/bin/env bash
# Publish mintsniper to GitHub as a public repository.
#
# Requires a GitHub token with "public_repo" scope:
#   GitHub -> Settings -> Developer settings -> Personal access tokens
#
# Usage:
#   GITHUB_TOKEN=ghp_xxx bash scripts/publish.sh [repo-name]
#
# The token is used only for this push and is never stored in the repository.

set -euo pipefail

REPO_NAME="${1:-mintsniper}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "error: GITHUB_TOKEN is not set." >&2
  echo "Create one at https://github.com/settings/tokens with scope 'public_repo'," >&2
  echo "then run: GITHUB_TOKEN=ghp_xxx bash scripts/publish.sh" >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "error: git is required" >&2
  exit 1
fi

echo "==> publishing $REPO_NAME from $SKILL_DIR"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cp -R "$SKILL_DIR"/. "$WORK"/
rm -rf "$WORK/state" "$WORK/.git" "$WORK"/__pycache__ "$WORK"/scripts/__pycache__

cd "$WORK"
git init -q
git add -A
git -c user.name="${GIT_AUTHOR_NAME:-menghaoran214-lang}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-menghaoran214@gmail.com}" \
    commit -q -m "feat: mintsniper - BSC mint project early discovery skill"
git branch -M main

AUTH_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${GIT_OWNER:-menghaoran214-lang}/${REPO_NAME}.git"

echo "==> pushing to $REPO_NAME"
GIT_TERMINAL_PROMPT=0 git push -u "$AUTH_URL" main

echo
echo "==> done"
echo "    repo:  https://github.com/${GIT_OWNER:-menghaoran214-lang}/${REPO_NAME}"
echo "    install: npx skills add https://github.com/${GIT_OWNER:-menghaoran214-lang}/${REPO_NAME}"
echo
echo "If the repository does not exist yet, create it first:"
echo "    https://github.com/new?name=${REPO_NAME}&description=Early+discovery+of+BSC+mint+projects"
