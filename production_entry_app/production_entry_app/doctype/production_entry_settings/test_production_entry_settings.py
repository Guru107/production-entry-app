from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.api import get_shift_details_for_stock_entry
from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
	_build_shift_doc,
	bootstrap_manufacture_masters,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	ensure_branch,
	ensure_warehouse,
	resolve_test_company,
	set_test_branch_warehouse_defaults,
)


class TestBranchWarehouseSettings(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_duplicate_company_branch_defaults_are_rejected(self) -> None:
		settings = frappe.get_single("Production Entry Settings")
		values = {
			"company": resolve_test_company(),
			"branch": ensure_branch("_Warehouse Defaults Test"),
		}
		settings.set("branch_warehouse_defaults", [values, values])
		with self.assertRaisesRegex(frappe.ValidationError, "Duplicate warehouse defaults"):
			settings.save()

	def test_warehouse_from_another_company_is_rejected(self) -> None:
		company = resolve_test_company()
		other_company = (
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": f"_Warehouse Defaults {frappe.generate_hash(length=6)}",
					"abbr": frappe.generate_hash(length=5).upper(),
					"default_currency": frappe.db.get_value("Company", company, "default_currency"),
					"country": frappe.db.get_value("Company", company, "country"),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		warehouse = ensure_warehouse("_Branch Defaults Foreign Warehouse", other_company)
		settings = frappe.get_single("Production Entry Settings")
		settings.set(
			"branch_warehouse_defaults",
			[
				{
					"company": company,
					"branch": ensure_branch("_Warehouse Defaults Test"),
					"work_in_progress_warehouse": warehouse,
				}
			],
		)
		with self.assertRaisesRegex(frappe.ValidationError, "must belong to Company"):
			settings.save()

	def test_shift_defaults_match_its_branch_and_preserve_explicit_values(self) -> None:
		masters = bootstrap_manufacture_masters()
		branch = ensure_branch("_Warehouse Defaults Second Branch")
		second_wip = ensure_warehouse("_Second Branch WIP", masters["company"])
		set_test_branch_warehouse_defaults(
			masters["company"],
			branch,
			work_in_progress_warehouse=second_wip,
			scrap_warehouse=masters["scrap_warehouse"],
		)
		shift = _build_shift_doc(masters=masters, status="Draft")
		shift.branch = branch
		shift.work_in_progress_warehouse = None
		shift.scrap_warehouse = None
		shift.insert()
		self.assertEqual(shift.work_in_progress_warehouse, second_wip)
		self.assertEqual(shift.scrap_warehouse, masters["scrap_warehouse"])
		self.assertEqual(shift.rejection_warehouse, masters["rejection_warehouse"])
		frappe.db.set_value("Shift", shift.name, {"status": "Running", "work_in_progress_warehouse": None})
		details = get_shift_details_for_stock_entry(shift.name)
		self.assertEqual(details["from_warehouse"], second_wip)
		self.assertEqual(details["to_warehouse"], second_wip)

	def test_missing_branch_defaults_do_not_use_another_branch(self) -> None:
		masters = bootstrap_manufacture_masters()
		shift = _build_shift_doc(masters=masters, status="Draft")
		shift.branch = ensure_branch("_Warehouse Defaults Unconfigured")
		shift.work_in_progress_warehouse = None
		shift.insert()
		self.assertFalse(shift.work_in_progress_warehouse)
		frappe.db.set_value("Shift", shift.name, "status", "Running")
		with self.assertRaisesRegex(frappe.ValidationError, "Work In Progress Warehouse"):
			get_shift_details_for_stock_entry(shift.name)
