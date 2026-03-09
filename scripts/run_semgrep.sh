#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rules_dir="${SEMGREP_RULES_DIR:-${TMPDIR:-/tmp}/pea-frappe-semgrep-rules}"

if ! command -v semgrep >/dev/null 2>&1; then
	echo "semgrep is required for local pre-commit. Install it with: pip install semgrep" >&2
	exit 1
fi

if [ ! -d "$rules_dir/.git" ]; then
	rm -rf "$rules_dir"
	git clone --depth 1 https://github.com/frappe/semgrep-rules.git "$rules_dir"
fi

cd "$repo_root"

if [ "$#" -eq 0 ]; then
	exec semgrep scan --error --config "$rules_dir/rules" --config r/python.lang.correctness
fi

exec semgrep scan --error --config "$rules_dir/rules" --config r/python.lang.correctness "$@"
