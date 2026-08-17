from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.report_access import (
	PEA_REPORT_NAMES,
	get_report_permission_query_conditions,
	get_script,
	run,
)


class TestReadOnlyReportAccess(FrappeTestCase):
	def test_frappe_hooks_enforce_report_allowlist(self) -> None:
		from production_entry_app import hooks

		self.assertEqual(
			hooks.permission_query_conditions["Report"],
			"production_entry_app.production_entry_app.report_access.get_report_permission_query_conditions",
		)
		self.assertEqual(
			hooks.override_whitelisted_methods["frappe.desk.query_report.get_script"],
			"production_entry_app.production_entry_app.report_access.get_script",
		)
		self.assertEqual(
			hooks.override_whitelisted_methods["frappe.desk.query_report.run"],
			"production_entry_app.production_entry_app.report_access.run",
		)

	def test_allowlist_matches_standard_app_reports(self) -> None:
		report_names = frappe.get_all(
			"Report",
			filters={"module": "Production Entry App", "is_standard": "Yes", "disabled": 0},
			pluck="name",
		)

		self.assertEqual(set(PEA_REPORT_NAMES), set(report_names))

	def test_run_rejects_non_app_report_for_pea_read_only(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.report_access.frappe.get_roles",
				return_value=["PEA Read Only"],
			),
			patch("production_entry_app.production_entry_app.report_access.query_report.run") as core_run,
			self.assertRaises(frappe.PermissionError),
		):
			run("General Ledger")

		core_run.assert_not_called()

	def test_get_script_rejects_non_app_report_for_pea_read_only(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.report_access.frappe.get_roles",
				return_value=["PEA Read Only"],
			),
			patch(
				"production_entry_app.production_entry_app.report_access.query_report.get_script"
			) as core_get_script,
			self.assertRaises(frappe.PermissionError),
		):
			get_script("General Ledger")

		core_get_script.assert_not_called()

	def test_run_allows_app_report_for_pea_read_only(self) -> None:
		report_name = "Production OEE Report"
		with (
			patch(
				"production_entry_app.production_entry_app.report_access.frappe.get_roles",
				return_value=["PEA Read Only"],
			),
			patch(
				"production_entry_app.production_entry_app.report_access.query_report.run",
				return_value={"result": []},
			) as core_run,
		):
			result = run(report_name, filters={})

		self.assertEqual(result, {"result": []})
		core_run.assert_called_once_with(report_name=report_name, filters={})

	def test_report_query_condition_limits_pea_read_only_to_allowlist(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.report_access.frappe.get_roles",
			return_value=["PEA Read Only"],
		):
			condition = get_report_permission_query_conditions("readonly@example.com")

		self.assertIn("`tabReport`.`name` in", condition)
		for report_name in PEA_REPORT_NAMES:
			self.assertIn(frappe.db.escape(report_name), condition)

	def test_report_query_condition_does_not_restrict_other_users(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.report_access.frappe.get_roles",
			return_value=["System Manager"],
		):
			condition = get_report_permission_query_conditions("manager@example.com")

		self.assertEqual(condition, "")
