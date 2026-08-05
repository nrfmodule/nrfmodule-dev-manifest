#!/usr/bin/env bash
#
# nrfmodule code-quality gate — clang-format + custom rule checks (+ optional
# checkpatch) over a set of C/C++ files. Shared by git hooks, CI, and /check.
#
# Usage:
#   check.sh [file...]          # check given files (default: staged C/H files)
#   check.sh --range <A>..<B>   # check C/H files changed in a git range
#   check.sh --all              # check every tracked C/H file in this repo
#
# Env overrides: CLANG_FORMAT, CHECKPATCH, NRFMODULE_TOOLING (this dir).
# Set RUN_CHECKPATCH=1 to make checkpatch run (off by default — noisy, advisory).
set -u

TOOLING_DIR="${NRFMODULE_TOOLING:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
STYLE_FILE="$TOOLING_DIR/.clang-format"
CHECKS_DIR="$TOOLING_DIR/checks"

# --- locate clang-format: env -> PATH -> pip --user (Windows) ----------------
if [ -z "${CLANG_FORMAT:-}" ]; then
	if command -v clang-format >/dev/null 2>&1; then
		CLANG_FORMAT="clang-format"
	elif [ -n "${APPDATA:-}" ] && [ -x "$APPDATA/Python/Python311/Scripts/clang-format.exe" ]; then
		CLANG_FORMAT="$APPDATA/Python/Python311/Scripts/clang-format.exe"
	else
		CLANG_FORMAT=""
	fi
fi

# --- locate checkpatch (Zephyr) ----------------------------------------------
if [ -z "${CHECKPATCH:-}" ] && [ -n "${ZEPHYR_BASE:-}" ] && [ -f "$ZEPHYR_BASE/scripts/checkpatch.pl" ]; then
	CHECKPATCH="$ZEPHYR_BASE/scripts/checkpatch.pl"
fi

# --- collect target files ----------------------------------------------------
is_src() { case "$1" in *.c|*.h|*.cpp|*.hpp|*.cc) return 0 ;; *) return 1 ;; esac; }

mode="${1:-}"
range="${2:-}"

declare -a files=()
case "${1:-}" in
	--all)
		while IFS= read -r f; do is_src "$f" && files+=("$f"); done \
			< <(git ls-files '*.c' '*.h' '*.cpp' '*.hpp' '*.cc') ;;
	--range)
		[ -n "${2:-}" ] || { echo "check.sh --range needs <A>..<B>"; exit 2; }
		while IFS= read -r f; do is_src "$f" && [ -f "$f" ] && files+=("$f"); done \
			< <(git diff --name-only --diff-filter=d "$2") ;;
	"")
		while IFS= read -r f; do is_src "$f" && [ -f "$f" ] && files+=("$f"); done \
			< <(git diff --cached --name-only --diff-filter=d) ;;
	--*)
		# An unknown flag must not be silently treated as a (missing) file and
		# pass the gate — fail loudly so a typo'd --range/--all is caught.
		echo "check.sh: unknown option '$1' (expected --all, --range <A>..<B>, or file...)"
		exit 2 ;;
	*)
		for f in "$@"; do is_src "$f" && [ -f "$f" ] && files+=("$f"); done ;;
esac

# Drop vendored third-party files (opt out with a "nrfmodule-lint: vendored"
# marker) so faithful upstream copies aren't held to house style.
if [ "${#files[@]}" -gt 0 ]; then
	declare -a kept=()
	for f in "${files[@]}"; do
		grep -qiE 'nrfmodule-lint:[[:space:]]*vendored' "$f" 2>/dev/null && continue
		kept+=("$f")
	done
	files=( ${kept[@]+"${kept[@]}"} )
fi

if [ "${#files[@]}" -eq 0 ]; then
	echo "check: no C/C++ files to check."
	exit 0
fi

echo "check: ${#files[@]} file(s)"
fail=0

# --- 1. custom rule checks (house style) — ENFORCED --------------------------
bash "$CHECKS_DIR/no-ifdef-config.sh"        "${files[@]}" || fail=1
bash "$CHECKS_DIR/paren-numeric-defines.sh"  "${files[@]}" || fail=1
bash "$CHECKS_DIR/no-hardcoded-secrets.sh"   "${files[@]}" || fail=1
bash "$CHECKS_DIR/complexity.sh"             "${files[@]}" || fail=1

# --- 2. clang-format — ADVISORY (reports drift, never blocks/reformats) -------
# By design: it flags formatting that differs from the canonical style so we can
# catch agent drift, but it does NOT fail the gate or touch hand-aligned code.
# Set CLANG_FORMAT_VERBOSE=1 to print the exact per-line suggestions.
if [ -n "$CLANG_FORMAT" ]; then
	style_arg="$STYLE_FILE"
	# A native Windows clang-format.exe cannot read an MSYS (/d/..) path.
	command -v cygpath >/dev/null 2>&1 && style_arg="$(cygpath -m "$STYLE_FILE")"
	cf_n=0
	for f in "${files[@]}"; do
		out=$("$CLANG_FORMAT" --style="file:$style_arg" --dry-run --Werror "$f" 2>&1)
		if [ -n "$out" ]; then
			if [ "$cf_n" -eq 0 ]; then
				echo "── clang-format ADVISORY (style drift, not enforced) ──"
			fi
			cf_n=$((cf_n + 1))
			echo "  [clang-format] $f differs from canonical style"
			[ "${CLANG_FORMAT_VERBOSE:-0}" = "1" ] && echo "$out" | sed 's/^/      /'
		fi
	done
	[ "$cf_n" -gt 0 ] && echo "  ($cf_n file(s) — inspect: clang-format --style=file:$STYLE_FILE <file>)"
fi

# --- 2b. added-comments — ADVISORY (diff-based: staged or range only) --------
# Surfaces net-new comment lines so rationale gets moved to the commit message.
case "$mode" in
	"")      git diff --cached  | bash "$CHECKS_DIR/added-comments.sh" ;;
	--range) git diff "$range"  | bash "$CHECKS_DIR/added-comments.sh" ;;
esac

# --- 3. checkpatch (advisory; opt-in) ----------------------------------------
if [ "${RUN_CHECKPATCH:-0}" = "1" ] && [ -n "${CHECKPATCH:-}" ]; then
	echo "[checkpatch] advisory output:"
	"$CHECKPATCH" --no-tree --terse --show-types \
		--ignore SPDX_LICENSE_TAG,FILE_PATH_CHANGES,GERRIT_CHANGE_ID,EMAIL_SUBJECT \
		-f "${files[@]}" || true
fi

if [ "$fail" -ne 0 ]; then
	echo "check: FAILED"
	exit 1
fi
echo "check: OK"
exit 0
