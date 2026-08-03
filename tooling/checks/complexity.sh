#!/usr/bin/env bash
# Rule: keep functions small and simple. Flags functions whose cyclomatic
# complexity exceeds CCN_LIMIT (default 15) or whose length exceeds
# FN_LEN_LIMIT lines (default 120). Catches the "one 300-line function"
# failure mode that reads fine in a diff but is untestable.
#
# Backend: lizard (pip install lizard). If lizard is not installed the check
# prints a notice and passes, so local environments without it are not blocked;
# CI installs it in the Docker image and always enforces.
#
# Escape hatch: a comment on the line above the function whose text STARTS
# with `#lizard forgives` (lizard matches the comment start; trailing rationale
# is fine, leading words are not: `/* #lizard forgives: linear init */` works,
# `/* boot glue #lizard forgives */` does not). Use for large-but-flat
# switch dispatchers where splitting would hurt readability.
#
# Also warns (advisory, never fails) when a checked .c file exceeds
# FILE_LEN_WARN lines: single functions stay small under the enforced limits
# while a file quietly accretes concerns; this is the nudge to split it.
#
# Usage: complexity.sh <file>...
set -u

CCN_LIMIT="${CCN_LIMIT:-15}"
FN_LEN_LIMIT="${FN_LEN_LIMIT:-120}"
FILE_LEN_WARN="${FILE_LEN_WARN:-500}"

if command -v lizard >/dev/null 2>&1; then
	LIZARD=(lizard)
elif python3 -m lizard --version >/dev/null 2>&1; then
	LIZARD=(python3 -m lizard)
elif python -m lizard --version >/dev/null 2>&1; then
	LIZARD=(python -m lizard)
else
	echo "[complexity] lizard not installed; skipping (pip install lizard)"
	exit 0
fi

out=$("${LIZARD[@]}" --CCN "$CCN_LIMIT" --length "$FN_LEN_LIMIT" \
	--warnings_only --modified "$@" 2>&1)
rc=$?

for f in "$@"; do
	case "$f" in
	*.c|*.cpp)
		lines=$(wc -l < "$f" 2>/dev/null || echo 0)
		if [ "$lines" -gt "$FILE_LEN_WARN" ]; then
			echo "[complexity] ADVISORY: $f is $lines lines (> $FILE_LEN_WARN); consider splitting concerns"
		fi
		;;
	esac
done

if [ $rc -ne 0 ] && [ -n "$out" ]; then
	echo "[complexity] function(s) over CCN $CCN_LIMIT or $FN_LEN_LIMIT lines; split, or start a comment above the function with '#lizard forgives':"
	echo "$out" | sed 's/^/    /'
	exit 1
fi
exit 0
