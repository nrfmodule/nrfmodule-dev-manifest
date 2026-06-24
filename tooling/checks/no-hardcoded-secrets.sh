#!/usr/bin/env bash
# Rule: no hardcoded secrets/credentials in source — store them in NVS settings
# or the filesystem. "One vulnerability on GitHub and the key is exposed."
#
# Tight patterns (keep false positives low): a string literal (>=8 chars)
# assigned to a secret-named identifier, an AWS access-key id, or a PEM private
# key header. Obvious placeholders are excluded.
#
# Usage: no-hardcoded-secrets.sh <file>...
set -u

status=0
for f in "$@"; do
	[ -f "$f" ] || continue
	m=$(grep -nEi \
		'(api[_-]?key|secret|passwd|password|passphrase|token|credential|private[_-]?key)([[:space:]]*[=:][[:space:]]*|[[:space:]]+)"[^"]{8,}"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----' "$f" \
		| grep -vEi '"(changeme|change_me|placeholder|example|your[_-]|xxx+|todo|dummy|sample|none|null|<[^"]*>)' || true)
	if [ -n "$m" ]; then
		echo "[no-hardcoded-secrets] $f — store secrets in NVS/settings/FS, not source:"
		echo "$m" | sed 's/^/    /'
		status=1
	fi
done
exit $status
