#!/usr/bin/env bash
# Rule: no AI attribution in commit messages or PR bodies.
#
# Usage: no-ai-attribution.sh <text-file>   (e.g. a commit-msg file)
set -u

file="${1:-}"
[ -f "$file" ] || exit 0

if grep -qiE 'co-authored-by:[[:space:]]*claude|generated with[[:space:]].*claude|claude code|🤖' "$file"; then
	echo "[no-ai-attribution] AI attribution found — remove it:"
	grep -niE 'co-authored-by:[[:space:]]*claude|generated with[[:space:]].*claude|claude code|🤖' "$file" | sed 's/^/    /'
	exit 1
fi
exit 0
