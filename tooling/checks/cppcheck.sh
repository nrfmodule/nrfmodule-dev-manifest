#!/usr/bin/env bash
# cppcheck over the given sources. No build database needed, so it fits the
# PR lint. ENFORCED when cppcheck is installed; skips with a notice when it
# is not, so machines without it are not blocked.
#
# Only findings cppcheck is sure about (error + warning severities). Zephyr
# and nrfx headers are not on the include path on purpose: without them the
# run takes seconds, and unknown macros are tolerated.
#
# Usage: cppcheck.sh <file>...
set -u

command -v cppcheck >/dev/null 2>&1 || { echo "[cppcheck] not installed; skipped."; exit 0; }

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
inc=()
for d in "$root/src" "$root/include" "$root/drivers"; do
	[ -d "$d" ] && inc+=("-I$d")
done

out="$(cppcheck --quiet --error-exitcode=0 \
	--enable=warning,performance,portability \
	--inline-suppr \
	--suppress=missingInclude --suppress=missingIncludeSystem \
	--suppress=unknownMacro \
	--template='{file}:{line}: [{id}] {message}' \
	${inc[@]+"${inc[@]}"} "$@" 2>&1 | grep -E '^\S+:[0-9]+: \[' | sort -u)"

if [ -n "$out" ]; then
	echo "── cppcheck ──"
	echo "$out" | sed 's/^/    /'
	echo "[cppcheck] $(echo "$out" | wc -l) finding(s)"
	exit 1
fi
echo "[cppcheck] clean"
exit 0
