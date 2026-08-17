#!/usr/bin/env bash
#
# Point a repo's git hooks at the shared nrfmodule tooling hooks. Run from
# inside the target repo (or pass it as $1):
#
#   bash <workspace>/config/manifest/tooling/install-hooks.sh
#
# Uses core.hooksPath, so there are no per-repo hook files to commit and every
# repo stays in sync with the canonical hooks. Re-run after moving the workspace.
set -e

TOOLING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${1:-$PWD}"

cd "$REPO"
git rev-parse --git-dir >/dev/null 2>&1 || { echo "error: $REPO is not a git repo"; exit 1; }

git config core.hooksPath "$TOOLING_DIR/hooks"
echo "installed: $(git rev-parse --show-toplevel) -> core.hooksPath = $TOOLING_DIR/hooks"
