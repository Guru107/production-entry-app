from __future__ import annotations

from typing import Any

import frappe

from production_entry_app.production_entry_app import api
from production_entry_app.production_entry_app.report import report_benchmark

_PYTHON_TEST_BENCHMARK_KEYS: tuple[str, ...] = ("PHASE2", "WRITEPATH")
_ORIGINAL_FRAPPE_TEST_CASE_RUN = None


def capture_manufacturing_settings_snapshot() -> dict[str, Any]:
	return api._get_manufacturing_settings_snapshot()


def restore_manufacturing_settings_snapshot(snapshot: dict[str, Any] | None) -> None:
	api._restore_manufacturing_settings(snapshot)


def cleanup_reserved_test_data() -> None:
	# Persistent-site runs still use document-level cleanup, but authoritative suites now
	# rely on dropping the whole ephemeral site after the run.
	api._cleanup_reserved_e2e_artifacts()
	for dataset_key in _PYTHON_TEST_BENCHMARK_KEYS:
		report_benchmark.cleanup_report_benchmark(dataset_key)


def cleanup_reserved_benchmark_data() -> None:
	for dataset_key in _PYTHON_TEST_BENCHMARK_KEYS:
		report_benchmark.cleanup_report_benchmark(dataset_key)


def cleanup_after_python_test(snapshot: dict[str, Any] | None) -> None:
	last_error: Exception | None = None
	for _attempt in range(2):
		try:
			frappe.db.rollback()
			restore_manufacturing_settings_snapshot(snapshot)
			cleanup_reserved_test_data()
			frappe.db.commit()
			return
		except Exception as exc:
			last_error = exc
			frappe.db.rollback()
	if last_error is not None:
		frappe.log_error(
			title="Python test cleanup failed",
			message=f"Unable to clean reserved test data: {last_error}",
		)


def _is_production_entry_app_test_case(test_case: Any) -> bool:
	module_name = getattr(test_case.__class__, "__module__", "") or ""
	return module_name.startswith("production_entry_app.")


def install_test_run_cleanup() -> None:
	from frappe.tests.utils import FrappeTestCase

	global _ORIGINAL_FRAPPE_TEST_CASE_RUN
	if getattr(FrappeTestCase, "_pea_cleanup_installed", False):
		return

	_ORIGINAL_FRAPPE_TEST_CASE_RUN = FrappeTestCase.run

	def _run_with_cleanup(self, result=None):
		if not _is_production_entry_app_test_case(self):
			return _ORIGINAL_FRAPPE_TEST_CASE_RUN(self, result)
		snapshot = capture_manufacturing_settings_snapshot()
		try:
			return _ORIGINAL_FRAPPE_TEST_CASE_RUN(self, result)
		finally:
			cleanup_after_python_test(snapshot)

	FrappeTestCase.run = _run_with_cleanup
	FrappeTestCase._pea_cleanup_installed = True
