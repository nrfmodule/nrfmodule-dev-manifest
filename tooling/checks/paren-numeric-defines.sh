#!/usr/bin/env bash
# Rule: parenthesize numeric literals in object-like #defines — `#define X (1000)`
# not `#define X 1000`. Protects against precedence surprises when the macro is
# used in a larger expression.
#
# Heuristic (object-like macros only): flags `#define NAME <bare-number>`.
# Skips function-like macros (`#define NAME(...)`), already-parenthesized values,
# and string/char values. Some false positives are expected.
#
# Escape hatch: a trailing `style:no-paren` comment exempts a line, for the cases
# where parens break the build (e.g. a SYS_INIT priority gets token-pasted).
#
# Usage: paren-numeric-defines.sh <file>...
set -u

# #define <NAME> <optional-sign><int-or-hex><optional-suffix> followed by end or
# a comment. The NAME must be followed by whitespace (so `NAME(` function-like
# macros, which have no space, are excluded).
pattern='^[[:space:]]*#[[:space:]]*define[[:space:]]+[A-Za-z_][A-Za-z0-9_]*[[:space:]]+-?(0[xX][0-9A-Fa-f]+|[0-9]+)[uUlL]*[[:space:]]*(/[/*].*)?$'

status=0
for f in "$@"; do
	[ -f "$f" ] || continue
	# Drop lines that opt out via a trailing `style:no-paren` comment.
	matches=$(grep -nE "$pattern" "$f" | grep -v 'style:no-paren' || true)
	if [ -n "$matches" ]; then
		echo "[paren-numeric-defines] $f — wrap the numeric literal in parens, e.g. (1000):"
		echo "$matches" | sed 's/^/    /'
		status=1
	fi
done
exit $status
