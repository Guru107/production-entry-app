#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_SPEC="${AI_SLOP_PACKAGE_SPEC:-ai-slop-detector[js]==3.6.0}"
CI_MODE="${AI_SLOP_CI_MODE:-soft}"
CONFIG_FILE="${AI_SLOP_CONFIG:-${ROOT_DIR}/.slopconfig.yaml}"
TARGET="${1:-${ROOT_DIR}}"

if ! command -v uvx >/dev/null 2>&1; then
	echo "uvx is required to run AI-SLOP Detector. Install uv: https://docs.astral.sh/uv/" >&2
	exit 127
fi

cd "${ROOT_DIR}"
exec uvx --from "${PACKAGE_SPEC}" slop-detector \
	--project "${TARGET}" \
	--config "${CONFIG_FILE}" \
	--js \
	--ci-mode "${CI_MODE}" \
	--ci-report \
	--no-history
