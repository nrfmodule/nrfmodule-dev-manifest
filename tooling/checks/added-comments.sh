#!/usr/bin/env bash
# Advisory: list comment lines ADDED in a unified diff (read from stdin).
#
# Rationale for a change belongs in the commit message, not inline. This pass
# surfaces net-new comment lines at commit time so they get justified or cut —
# it never fails the gate. Flags added lines that are wholly a comment (`//`,
# `/*`, or a `*` block continuation). Skips functional markers (style:no-paren)
# and SPDX tags. Trailing comments on code lines are left to judgement.
#
# Usage: git diff --cached | added-comments.sh
set -u

out=$(awk '
	/^\+\+\+ /  { f = $2; sub(/^b\//, "", f); next }
	/^@@/       { match($0, /\+[0-9]+/); ln = substr($0, RSTART + 1, RLENGTH - 1) + 0; next }
	/^-/        { next }
	/^\+/ {
		c = substr($0, 2); t = c; sub(/^[ \t]+/, "", t)
		# A leading `*` is a block-comment continuation only when followed by
		# space/tab/slash or end — not `*out`/`*ptr` (pointer code).
		if (t ~ /^(\/\/|\/\*|\*[ \t\/]|\*$)/ && t !~ /style:no-paren/ && t !~ /SPDX-License/) {
			printf("    %s:%d:%s\n", f, ln, c)
		}
		ln++; next
	}
	/^ /        { ln++ }
')

if [ -n "$out" ]; then
	n=$(printf '%s\n' "$out" | grep -c .)
	echo "── added-comments ADVISORY (put rationale in the commit message — justify or cut) ──"
	echo "  $n new comment line(s):"
	printf '%s\n' "$out"
fi
exit 0
