#!/usr/bin/env bash
# clang-tidy over project sources, using the compile database Zephyr writes
# into the build dir. ADVISORY by default (prints, exits 0); set
# TIDY_ENFORCE=1 to fail on findings.
#
# Needs: clang-tidy on PATH or from `pip install clang-tidy` (Windows user
# scripts dir). Skips with a notice when clang-tidy or a compile database is
# missing, so machines without either are not blocked.
#
# The database carries GCC-only flags that clang rejects; a filtered copy is
# made in a temp dir. Header warnings are limited to this repo's src/.
#
# Env: TIDY_BUILD_DIR (dir holding compile_commands.json; default = first
# match of build*/*/compile_commands.json or build*/compile_commands.json).
#
# Usage: clang-tidy.sh <file>...
set -u

CHECKS='-*,bugprone-*,clang-analyzer-*'
CHECKS+=',-bugprone-reserved-identifier'          # Zephyr/nrfx __ names
CHECKS+=',-bugprone-easily-swappable-parameters'  # style, not bugs
CHECKS+=',-bugprone-branch-clone'                 # LOG_* and shell macros expand to clones
CHECKS+=',-clang-analyzer-security.insecureAPI.*' # memset/memcpy "insecure" noise
CHECKS+=',-clang-analyzer-core.FixedAddressDereference' # nrfx register access
GCC_ONLY_FLAGS=' -fno-printf-return-value| -fno-reorder-functions| -mfp16-format=ieee'

find_tidy() {
	command -v clang-tidy 2>/dev/null && return 0
	# pip --user install on Windows lands in the per-version Scripts dir.
	for exe in "${APPDATA:-/nonexistent}"/Python/Python3*/Scripts/clang-tidy.exe; do
		[ -x "$exe" ] && { echo "$exe"; return 0; }
	done
	return 1
}

TIDY="$(find_tidy)" || { echo "[clang-tidy] not installed (pip install clang-tidy); skipped."; exit 0; }

db=""
if [ -n "${TIDY_BUILD_DIR:-}" ]; then
	db="$TIDY_BUILD_DIR/compile_commands.json"
else
	for cand in build*/*/compile_commands.json build*/compile_commands.json; do
		case "$cand" in *mcuboot*|*b0*|*tfm*) continue ;; esac
		[ -f "$cand" ] && { db="$cand"; break; }
	done
fi
[ -f "$db" ] || { echo "[clang-tidy] no compile_commands.json under build*/; skipped."; exit 0; }

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
sed -E "s/$GCC_ONLY_FLAGS//g" "$db" > "$tmp/compile_commands.json"

# Only files the database knows (unit-test mains and headers are not in the app DB).
db_files="$(python -c "import json,sys;print('\n'.join(x['file'].replace('\\\\','/').lower() for x in json.load(open(sys.argv[1]))))" "$tmp/compile_commands.json")"
hits=0; checked=0
for f in "$@"; do
	abs="$(cd "$(dirname "$f")" && pwd -W 2>/dev/null || pwd)/$(basename "$f")"
	printf '%s\n' "$db_files" | grep -qxF "$(printf '%s' "$abs" | tr '[:upper:]' '[:lower:]')" || continue
	checked=$((checked + 1))
	out="$("$TIDY" -p "$tmp" --quiet --checks="$CHECKS" \
		--header-filter=".*$(basename "$root")[\\\\/]src[\\\\/].*" "$f" 2>/dev/null \
		| grep -E 'warning:' | sed -E "s|^.*$(basename "$root")[\\\\/]||" | sort -u)"
	if [ -n "$out" ]; then
		echo "$out" | sed 's/^/    /'
		hits=$((hits + $(echo "$out" | wc -l)))
	fi
done

echo "[clang-tidy] $checked file(s) analyzed, $hits finding(s) (db: $db)"
if [ "$hits" -gt 0 ] && [ "${TIDY_ENFORCE:-0}" = "1" ]; then
	exit 1
fi
exit 0
