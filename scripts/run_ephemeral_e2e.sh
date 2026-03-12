#!/usr/bin/env bash

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_ROOT="${BENCH_ROOT:-$(cd "$APP_ROOT/../.." && pwd)}"
BENCH_PYTHON="${BENCH_PYTHON:-$BENCH_ROOT/env/bin/python}"
DB_ROOT_USERNAME="${DB_ROOT_USERNAME:-root}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-}"
EPHEMERAL_ADMIN_PASSWORD="${EPHEMERAL_ADMIN_PASSWORD:-123}"
RUN_ID="${EPHEMERAL_SITE_RUN_ID:-$(date +%Y%m%d%H%M%S)-$$}"
E2E_MODE="${1:-smoke}"
SITE_NAME=""
SERVER_PID=""

export PYTHONPATH="$APP_ROOT:$BENCH_ROOT/apps/frappe${PYTHONPATH:+:$PYTHONPATH}"

if [ -z "$DB_ROOT_PASSWORD" ]; then
	echo "DB_ROOT_PASSWORD is required for ephemeral site creation and teardown." >&2
	exit 1
fi

SITE_NAME="$("$BENCH_PYTHON" - "$RUN_ID" <<'PY'
import sys

from production_entry_app.production_entry_app.utils.ephemeral_test_site import build_site_name

print(build_site_name("e2e", sys.argv[1]))
PY
)"

cleanup() {
	local exit_code=$?
	set +e
	if [ -n "${SERVER_PID:-}" ]; then
		kill "$SERVER_PID" >/dev/null 2>&1 || true
		wait "$SERVER_PID" >/dev/null 2>&1 || true
	fi
	if [ -n "${SITE_NAME:-}" ] && [ -d "$BENCH_ROOT/sites/$SITE_NAME" ]; then
		echo "Dropping ephemeral site $SITE_NAME"
		cd "$BENCH_ROOT"
		bench drop-site "$SITE_NAME" --force --no-backup --db-root-username "$DB_ROOT_USERNAME" --db-root-password "$DB_ROOT_PASSWORD"
	fi
	exit "$exit_code"
}

trap cleanup EXIT

cd "$BENCH_ROOT"

bench new-site "$SITE_NAME" --db-root-username "$DB_ROOT_USERNAME" --db-root-password "$DB_ROOT_PASSWORD" --admin-password "$EPHEMERAL_ADMIN_PASSWORD"
bench --site "$SITE_NAME" install-app erpnext
bench --site "$SITE_NAME" install-app production_entry_app
bench build --app production_entry_app
bench --site "$SITE_NAME" execute erpnext.setup.setup_wizard.operations.install_fixtures.install --args '["India"]'
bench --site "$SITE_NAME" execute erpnext.setup.utils.before_tests
bench --site "$SITE_NAME" set-config developer_mode 1
bench --site "$SITE_NAME" set-config allow_e2e_tests 1

nohup bench --site "$SITE_NAME" serve --port 8002 --noreload > /tmp/bench-serve.log 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 45); do
	if curl -sSf http://localhost:8002/login >/dev/null; then
		break
	fi
	sleep 2
done
curl -sSf http://localhost:8002/login >/dev/null

cd "$APP_ROOT"
export PLAYWRIGHT_BASE_URL="http://localhost:8002"
export PLAYWRIGHT_USERNAME="Administrator"
export PLAYWRIGHT_PASSWORD="$EPHEMERAL_ADMIN_PASSWORD"
export PLAYWRIGHT_EPHEMERAL_SITE="1"

case "$E2E_MODE" in
	smoke)
		npm run test:e2e
		;;
	regression)
		npm run test:e2e:regression
		;;
	ci)
		npm run test:e2e:ci
		;;
	*)
		npx playwright test "$@"
		;;
esac
