from __future__ import annotations

from unittest.mock import Mock, patch

from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils import test_setup


class TestTestSetup(FrappeTestCase):
	def test_before_tests_skips_core_record_creation_when_records_exist(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.db.exists",
				side_effect=lambda doctype, name=None: doctype in {"Company", "Cost Center"},
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.install_test_run_cleanup"
			) as install_cleanup,
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.cleanup_reserved_benchmark_data"
			) as cleanup_benchmarks,
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._get_erpnext_before_tests"
			) as get_erpnext_before_tests,
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._ensure_company_defaults"
			) as ensure_defaults,
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._ensure_branch_defaults"
			) as ensure_branch_defaults,
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._ensure_gender_records"
			) as ensure_genders,
		):
			test_setup.before_tests()

		get_erpnext_before_tests.assert_not_called()
		install_cleanup.assert_called_once_with()
		cleanup_benchmarks.assert_called_once_with()
		ensure_defaults.assert_called_once_with()
		ensure_branch_defaults.assert_called_once_with()
		ensure_genders.assert_called_once_with()

	def test_before_tests_runs_erpnext_bootstrap_when_cost_center_missing(self) -> None:
		def fake_exists(doctype, name=None):
			return doctype == "Company"

		erpnext_before_tests = Mock()
		with (
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.db.exists",
				side_effect=fake_exists,
			),
			patch("production_entry_app.production_entry_app.utils.test_setup.install_test_run_cleanup"),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.cleanup_reserved_benchmark_data"
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._get_erpnext_before_tests",
				return_value=erpnext_before_tests,
			) as get_erpnext_before_tests,
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_company_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_branch_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_gender_records"),
		):
			test_setup.before_tests()

		get_erpnext_before_tests.assert_called_once_with()
		erpnext_before_tests.assert_called_once_with()

	def test_before_tests_runs_erpnext_bootstrap_when_company_missing(self) -> None:
		erpnext_before_tests = Mock()
		with (
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.db.exists",
				return_value=False,
			),
			patch("production_entry_app.production_entry_app.utils.test_setup.install_test_run_cleanup"),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.cleanup_reserved_benchmark_data"
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._get_erpnext_before_tests",
				return_value=erpnext_before_tests,
			) as get_erpnext_before_tests,
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_company_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_branch_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_gender_records"),
		):
			test_setup.before_tests()

		get_erpnext_before_tests.assert_called_once_with()
		erpnext_before_tests.assert_called_once_with()

	def test_before_tests_tolerates_missing_erpnext_bootstrap_hook(self) -> None:
		def fake_exists(doctype, name=None):
			return doctype == "Company"

		with (
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.db.exists",
				side_effect=fake_exists,
			),
			patch("production_entry_app.production_entry_app.utils.test_setup.install_test_run_cleanup"),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.cleanup_reserved_benchmark_data"
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._get_erpnext_before_tests",
				return_value=None,
			) as get_erpnext_before_tests,
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_company_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_branch_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_gender_records"),
		):
			test_setup.before_tests()

		get_erpnext_before_tests.assert_called_once_with()
