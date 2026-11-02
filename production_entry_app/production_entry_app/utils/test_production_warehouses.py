from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.production_warehouses import (
	get_configured_scrap_warehouses,
	get_scrap_row_warehouse,
	validate_warehouse_companies,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	bootstrap_manufacturing_test_context,
	ensure_branch,
	ensure_warehouse,
	set_test_branch_warehouse_defaults,
)


class TestValidateWarehouseCompanies(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_missing_warehouse_reports_does_not_exist(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, r"Warehouse .* does not exist"):
			validate_warehouse_companies(
				[{"company": "_Test Company", "work_in_progress_warehouse": "Missing Warehouse XYZ"}]
			)


class TestScrapRowWarehouse(FrappeTestCase):
	def test_only_scrap_group_items_route_to_the_scrap_warehouse(self) -> None:
		warehouses = {"scrap_warehouse": "Scrap - TC", "work_in_progress_warehouse": "WIP - TC"}

		self.assertEqual(get_scrap_row_warehouse(warehouses, "Scrap"), "Scrap - TC")
		self.assertEqual(get_scrap_row_warehouse(warehouses, "Products"), "WIP - TC")

	def test_scrap_row_warehouse_requires_only_the_used_destination(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "Scrap Warehouse"):
			get_scrap_row_warehouse({}, "Scrap")
		with self.assertRaisesRegex(frappe.ValidationError, "Work In Progress Warehouse"):
			get_scrap_row_warehouse({}, "Products")


class TestConfiguredScrapWarehouses(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_configured_scrap_warehouses_cover_every_branch_of_the_company(self) -> None:
		ctx = bootstrap_manufacturing_test_context("Scrap Scope")
		other_branch = ensure_branch("Scrap Scope Other Branch")
		other_scrap_warehouse = ensure_warehouse("Scrap Scope Other Scrap", ctx["company"])
		set_test_branch_warehouse_defaults(
			ctx["company"], other_branch, scrap_warehouse=other_scrap_warehouse
		)

		self.assertEqual(
			get_configured_scrap_warehouses(ctx["company"]) & {ctx["scrap_warehouse"], other_scrap_warehouse},
			{ctx["scrap_warehouse"], other_scrap_warehouse},
		)

	def test_configured_scrap_warehouses_are_empty_without_a_company(self) -> None:
		self.assertEqual(get_configured_scrap_warehouses(None), set())
