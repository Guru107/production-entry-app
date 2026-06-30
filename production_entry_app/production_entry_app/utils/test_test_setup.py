from __future__ import annotations

from unittest.mock import Mock, patch

import frappe
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
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._scope_global_fiscal_years_for_erpnext_tests"
			) as scope_fiscal_years,
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._run_installed_app_before_tests"
			) as run_app_before_tests,
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._install_skip_test_records_compat"
			) as install_skip_compat,
		):
			test_setup.before_tests()

		get_erpnext_before_tests.assert_not_called()
		install_cleanup.assert_called_once_with()
		scope_fiscal_years.assert_called_once_with()
		run_app_before_tests.assert_called_once_with("india_compliance")
		install_skip_compat.assert_called_once_with()
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
				"production_entry_app.production_entry_app.utils.test_setup._get_erpnext_before_tests",
				return_value=erpnext_before_tests,
			) as get_erpnext_before_tests,
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._bootstrap_erpnext_defaults_without_hook"
			) as fallback_bootstrap,
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_company_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_branch_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_gender_records"),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup"
				"._scope_global_fiscal_years_for_erpnext_tests"
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._run_installed_app_before_tests"
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._install_skip_test_records_compat"
			),
		):
			test_setup.before_tests()

		get_erpnext_before_tests.assert_called_once_with()
		erpnext_before_tests.assert_called_once_with()
		fallback_bootstrap.assert_not_called()

	def test_before_tests_runs_erpnext_bootstrap_when_company_missing(self) -> None:
		erpnext_before_tests = Mock()
		with (
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.db.exists",
				return_value=False,
			),
			patch("production_entry_app.production_entry_app.utils.test_setup.install_test_run_cleanup"),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._get_erpnext_before_tests",
				return_value=erpnext_before_tests,
			) as get_erpnext_before_tests,
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._bootstrap_erpnext_defaults_without_hook"
			) as fallback_bootstrap,
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_company_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_branch_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_gender_records"),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup"
				"._scope_global_fiscal_years_for_erpnext_tests"
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._run_installed_app_before_tests"
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._install_skip_test_records_compat"
			),
		):
			test_setup.before_tests()

		get_erpnext_before_tests.assert_called_once_with()
		erpnext_before_tests.assert_called_once_with()
		fallback_bootstrap.assert_not_called()

	def test_before_tests_uses_local_fallback_when_erpnext_bootstrap_hook_missing(self) -> None:
		def fake_exists(doctype, name=None):
			return doctype == "Company"

		with (
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.db.exists",
				side_effect=fake_exists,
			),
			patch("production_entry_app.production_entry_app.utils.test_setup.install_test_run_cleanup"),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._get_erpnext_before_tests",
				return_value=None,
			) as get_erpnext_before_tests,
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._bootstrap_erpnext_defaults_without_hook"
			) as fallback_bootstrap,
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_company_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_branch_defaults"),
			patch("production_entry_app.production_entry_app.utils.test_setup._ensure_gender_records"),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup"
				"._scope_global_fiscal_years_for_erpnext_tests"
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._run_installed_app_before_tests"
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup._install_skip_test_records_compat"
			),
		):
			test_setup.before_tests()

		get_erpnext_before_tests.assert_called_once_with()
		fallback_bootstrap.assert_called_once_with()

	def test_run_installed_app_before_tests_uses_registered_hooks(self) -> None:
		hook = Mock()

		with (
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.get_installed_apps",
				return_value=["frappe", "erpnext", "india_compliance"],
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.get_hooks",
				return_value=["india_compliance.tests.before_tests"],
			) as get_hooks,
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.get_attr",
				return_value=hook,
			) as get_attr,
		):
			test_setup._run_installed_app_before_tests("india_compliance")

		get_hooks.assert_called_once_with("before_tests", app_name="india_compliance")
		get_attr.assert_called_once_with("india_compliance.tests.before_tests")
		hook.assert_called_once_with()

	def test_scope_global_fiscal_years_adds_company_to_unscoped_non_test_years(self) -> None:
		meta = Mock()
		meta.has_field.return_value = True
		now = Mock()
		now.year = 2026
		fiscal_year_doc = Mock()
		fiscal_year_doc.get.return_value = []

		with (
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.get_meta",
				return_value=meta,
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.db.get_single_value",
				return_value="TCPL",
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.now_datetime", return_value=now
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.get_all",
				return_value=[
					frappe._dict(name="2026-2027"),
					frappe._dict(name="_Test Fiscal Year 2026"),
					frappe._dict(name="Already Scoped FY"),
				],
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.db.exists",
				side_effect=lambda doctype, filters=None: (
					doctype == "Fiscal Year Company" and filters["parent"] == "Already Scoped FY"
				),
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_setup.frappe.get_doc",
				return_value=fiscal_year_doc,
			) as get_doc,
		):
			test_setup._scope_global_fiscal_years_for_erpnext_tests()

		get_doc.assert_called_once_with("Fiscal Year", "2026-2027")
		fiscal_year_doc.append.assert_called_once_with("companies", {"company": "TCPL"})
		fiscal_year_doc.save.assert_called_once_with(ignore_permissions=True)

	def test_install_skip_test_records_compat_wraps_v16_make_test_records(self) -> None:
		from frappe.tests import utils as frappe_test_utils
		from frappe.tests.utils import generators

		original = Mock(return_value=[("Item", 1)])
		original_utils_make_test_records = frappe_test_utils.make_test_records
		original_generator_make_test_records = generators.make_test_records
		previous_skip = frappe.flags.get("skip_test_records")

		try:
			frappe_test_utils.make_test_records = original
			generators.make_test_records = original
			frappe.flags.skip_test_records = True

			test_setup._install_skip_test_records_compat()

			self.assertEqual(frappe_test_utils.make_test_records("Item"), [])
			original.assert_not_called()
			self.assertIs(generators.make_test_records, frappe_test_utils.make_test_records)

			frappe.flags.skip_test_records = False
			self.assertEqual(frappe_test_utils.make_test_records("Item"), [("Item", 1)])
			original.assert_called_once_with("Item")
		finally:
			frappe_test_utils.make_test_records = original_utils_make_test_records
			generators.make_test_records = original_generator_make_test_records
			if previous_skip is None:
				frappe.flags.pop("skip_test_records", None)
			else:
				frappe.flags.skip_test_records = previous_skip
