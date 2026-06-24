#!/usr/bin/env bash
# Rule: guard Kconfig features with `#if defined(CONFIG_X)`, not #ifdef/#ifndef.
# A plain #ifdef silently passes when the symbol is mistyped; #if defined()
# composes (&&/||) and is the house standard.
#
# Usage: no-ifdef-config.sh <file>...
set -u

status=0
for f in "$@"; do
	[ -f "$f" ] || continue
	# Match Kconfig guards, but exclude include guards like `#ifndef CONFIG_FOO_H_`
	# (a header named config_*.h legitimately guards on CONFIG_*_H_).
	matches=$(grep -nE '^[[:space:]]*#[[:space:]]*(ifdef|ifndef)[[:space:]]+CONFIG_' "$f" \
		| grep -vE '#[[:space:]]*(ifdef|ifndef)[[:space:]]+CONFIG_[A-Za-z0-9_]*_H_?[[:space:]]*$' || true)
	if [ -n "$matches" ]; then
		echo "[no-ifdef-config] $f — use '#if defined(CONFIG_X)' not #ifdef/#ifndef:"
		echo "$matches" | sed 's/^/    /'
		status=1
	fi
done
exit $status
