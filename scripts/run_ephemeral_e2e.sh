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
SERVE_PORT="${EPHEMERAL_E2E_PORT:-}"
SITE_NAME=""
SERVER_PID=""
PREVIOUS_SITE=""
SERVE_LOG=""
BASE_URL=""
PORT=""

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
SERVE_LOG="/tmp/bench-serve-${RUN_ID}.log"

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
	if [ -n "${PREVIOUS_SITE:-}" ] && [ -d "$BENCH_ROOT/sites/$PREVIOUS_SITE" ]; then
		cd "$BENCH_ROOT"
		bench use "$PREVIOUS_SITE" >/dev/null 2>&1 || true
	fi
	exit "$exit_code"
}

trap cleanup EXIT

if [ -z "$SERVE_PORT" ] && [ "${CI:-}" = "true" ]; then
	SERVE_PORT="18002"
fi

cd "$BENCH_ROOT"
if [ -f "$BENCH_ROOT/sites/currentsite.txt" ]; then
	PREVIOUS_SITE="$(cat "$BENCH_ROOT/sites/currentsite.txt")"
fi

bench new-site "$SITE_NAME" --db-root-username "$DB_ROOT_USERNAME" --db-root-password "$DB_ROOT_PASSWORD" --admin-password "$EPHEMERAL_ADMIN_PASSWORD"
bench --site "$SITE_NAME" install-app erpnext
bench --site "$SITE_NAME" install-app production_entry_app
bench build --app production_entry_app
bench --site "$SITE_NAME" execute erpnext.setup.setup_wizard.operations.install_fixtures.install --args '["India"]'
bench --site "$SITE_NAME" execute production_entry_app.production_entry_app.utils.test_setup.before_tests
bench --site "$SITE_NAME" set-config developer_mode 1
bench --site "$SITE_NAME" set-config allow_e2e_tests 1
bench --site "$SITE_NAME" execute production_entry_app.production_entry_app.api._is_developer_mode_enabled
bench --site "$SITE_NAME" execute production_entry_app.production_entry_app.api._is_allow_e2e_tests_enabled
bench use "$SITE_NAME"

if [ -n "$SERVE_PORT" ]; then
	nohup bench --site "$SITE_NAME" serve --port "$SERVE_PORT" --noreload > "$SERVE_LOG" 2>&1 &
else
	nohup bench --site "$SITE_NAME" serve --port 0 --noreload > "$SERVE_LOG" 2>&1 &
fi
SERVER_PID=$!
for _ in $(seq 1 45); do
	if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
		cat "$SERVE_LOG" >&2 || true
		exit 1
	fi
	if [ -n "$SERVE_PORT" ]; then
		PORT="$SERVE_PORT"
	else
		PORT="$("$BENCH_PYTHON" - "$SERVE_LOG" <<'PY'
import sys
from pathlib import Path

from production_entry_app.production_entry_app.utils.ephemeral_test_site import extract_port_from_serve_log

log_path = Path(sys.argv[1])
if not log_path.exists():
	sys.exit(1)
port = extract_port_from_serve_log(log_path.read_text())
if port is None:
	sys.exit(1)
print(port)
PY
)" || true
	fi
	if [ -n "$PORT" ]; then
		BASE_URL="http://localhost:$PORT"
	fi
	if [ -n "$BASE_URL" ] && curl -sSf "$BASE_URL/login" >/dev/null; then
		break
	fi
	sleep 2
done
if [ -z "$BASE_URL" ]; then
	cat "$SERVE_LOG" >&2 || true
	exit 1
fi
curl -sSf "$BASE_URL/login" >/dev/null || {
	cat "$SERVE_LOG" >&2 || true
	exit 1
}

cd "$APP_ROOT"
export PLAYWRIGHT_BASE_URL="$BASE_URL"
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
