from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.api import (
	get_items_with_rejection,
	get_shift_details_for_stock_entry,
)
from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
	_build_shift_doc,
	bootstrap_manufacture_masters,
)
from production_entry_app.production_entry_app.utils.production_warehouses import (
	WAREHOUSE_FIELDS,
	require_warehouse,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	ensure_branch,
	ensure_item,
	ensure_joint_test_bom,
	ensure_warehouse,
	resolve_test_company,
	set_test_branch_warehouse_defaults,
)


class TestBranchWarehouseSettings(FrappeTestCase):
	def test_each_required_production_warehouse_has_a_validation_message(self) -> None:
		for fieldname in ("work_in_progress_warehouse", "rejection_warehouse", "scrap_warehouse"):
			with (
				self.subTest(fieldname=fieldname),
				self.assertRaisesRegex(frappe.ValidationError, "Please set a"),
			):
				require_warehouse({}, fieldname)

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
		self.assertEqual(shift.raw_material_warehouse, masters["rm_warehouse"])
		self.assertFalse(shift.work_in_progress_warehouse)
		frappe.db.set_value("Shift", shift.name, "status", "Running")
		details = get_shift_details_for_stock_entry(shift.name)
		self.assertEqual(details["company"], masters["company"])
		self.assertEqual(details["branch"], shift.branch)
		self.assertTrue(details["custom_pea_planned_start_date"])
		self.assertFalse(details["from_warehouse"])
		self.assertFalse(details["to_warehouse"])
		with self.assertRaisesRegex(frappe.ValidationError, "Work In Progress Warehouse"):
			get_items_with_rejection(
				frappe.as_json(
					{
						"doctype": "Stock Entry",
						"purpose": "Manufacture",
						"company": masters["company"],
						"custom_pea_shift": shift.name,
					}
				)
			)

	def test_work_order_fetch_preserves_native_warehouses_with_and_without_shift(self) -> None:
		masters = bootstrap_manufacture_masters()
		scrap_item = ensure_item("_Work Order Warehouse Scrap")
		bom = ensure_joint_test_bom(
			item_code=masters["fg_item"],
			rm_item=masters["rm_item"],
			scrap_items=[(scrap_item, 1, 0)],
			company=masters["company"],
			bom_quantity=10,
			rm_qty=20,
		)
		work_order = frappe.get_doc(
			{
				"doctype": "Work Order",
				"company": masters["company"],
				"production_item": masters["fg_item"],
				"bom_no": bom,
				"qty": 10,
				"skip_transfer": 1,
				"source_warehouse": masters["rm_warehouse"],
				"wip_warehouse": masters["rm_warehouse"],
				"fg_warehouse": masters["fg_warehouse"],
				"scrap_warehouse": masters["fg_warehouse"],
			}
		)
		work_order.get_items_and_operations_from_bom()
		work_order.insert()
		work_order.submit()
		shift = _build_shift_doc(masters=masters, status="Draft").insert()
		for shift_name in (None, shift.name):
			with self.subTest(shift=shift_name):
				values = {
					"doctype": "Stock Entry",
					"purpose": "Manufacture",
					"stock_entry_type": "Manufacture",
					"company": masters["company"],
					"work_order": work_order.name,
					"custom_pea_shift": shift_name,
					"bom_no": bom,
					"from_bom": 1,
					"fg_completed_qty": 10,
					"use_multi_level_bom": 0,
					"posting_date": frappe.utils.nowdate(),
					"posting_time": "12:00:00",
				}
				native = frappe.get_doc(values)
				native.get_items()
				rows = get_items_with_rejection(frappe.as_json(values))
				self.assertTrue(any(row.item_code == scrap_item for row in native.items))
				self.assertEqual(
					[(row["item_code"], row["s_warehouse"], row["t_warehouse"]) for row in rows],
					[(row.item_code, row.s_warehouse, row.t_warehouse) for row in native.items],
				)
