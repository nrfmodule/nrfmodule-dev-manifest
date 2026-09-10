#!/usr/bin/env bash
# Rule: no em dashes in comments. Plain hyphens or a new sentence instead.
# Reads a unified diff on stdin and fails on ADDED comment lines only, so
# existing files are not blocked until someone touches those lines.
#
# Usage: git diff --cached | no-em-dash.sh
set -u

hits=$(grep -E '^\+[^+]' | grep $'—' | grep -E '(//|/\*|^\+[[:space:]]*\*)' || true)
if [ -n "$hits" ]; then
	echo "[no-em-dash] em dash in an added comment, use a hyphen or split the sentence:"
	echo "$hits" | sed 's/^/    /'
	exit 1
fi
exit 0
