#!/usr/bin/env bash

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_ROOT="${BENCH_ROOT:-$(cd "$APP_ROOT/../.." && pwd)}"
BENCH_PYTHON="${BENCH_PYTHON:-$BENCH_ROOT/env/bin/python}"
DB_ROOT_USERNAME="${DB_ROOT_USERNAME:-root}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-}"
EPHEMERAL_ADMIN_PASSWORD="${EPHEMERAL_ADMIN_PASSWORD:-admin}"
RUN_ID="${EPHEMERAL_SITE_RUN_ID:-$(date +%Y%m%d%H%M%S)-$$}"

export PYTHONPATH="$APP_ROOT:$BENCH_ROOT/apps/frappe${PYTHONPATH:+:$PYTHONPATH}"

if [ -z "$DB_ROOT_PASSWORD" ]; then
	echo "DB_ROOT_PASSWORD is required for ephemeral site creation and teardown." >&2
	exit 1
fi

SITE_NAME="$("$BENCH_PYTHON" - "$RUN_ID" <<'PY'
import sys

from production_entry_app.production_entry_app.utils.ephemeral_test_site import build_site_name

print(build_site_name("py", sys.argv[1]))
PY
)"

cleanup() {
	local exit_code=$?
	set +e
	if [ -n "${SITE_NAME:-}" ] && [ -d "$BENCH_ROOT/sites/$SITE_NAME" ]; then
		echo "Dropping ephemeral site $SITE_NAME"
		cd "$BENCH_ROOT"
		drop_cmd=(bench drop-site "$SITE_NAME" --force --no-backup --db-root-username "$DB_ROOT_USERNAME")
		if [ -n "$DB_ROOT_PASSWORD" ]; then
			drop_cmd+=(--db-root-password "$DB_ROOT_PASSWORD")
		fi
		"${drop_cmd[@]}"
	fi
	exit "$exit_code"
}

trap cleanup EXIT

cd "$BENCH_ROOT"

new_site_cmd=(bench new-site "$SITE_NAME" --db-root-username "$DB_ROOT_USERNAME" --admin-password "$EPHEMERAL_ADMIN_PASSWORD")
if [ -n "$DB_ROOT_PASSWORD" ]; then
	new_site_cmd+=(--db-root-password "$DB_ROOT_PASSWORD")
fi
"${new_site_cmd[@]}"
bench --site "$SITE_NAME" install-app erpnext
bench --site "$SITE_NAME" install-app production_entry_app
bench build --app production_entry_app
bench --site "$SITE_NAME" execute erpnext.setup.setup_wizard.operations.install_fixtures.install --args '["India"]'
bench --site "$SITE_NAME" set-config allow_tests true
bench --site "$SITE_NAME" execute production_entry_app.production_entry_app.utils.test_setup.before_tests

if [ "$#" -gt 0 ]; then
	bench --site "$SITE_NAME" run-tests --app production_entry_app --module "$1"
else
	bench --site "$SITE_NAME" run-tests --app production_entry_app
fi
