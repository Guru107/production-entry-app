from __future__ import annotations

import json
from typing import Any

import frappe
import frappe.client
import frappe.handler
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime

from production_entry_app.production_entry_app.api import get_joint_production_items
from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary
from production_entry_app.production_entry_app.overrides.joint_production import (
	allocate_joint_output_value,
	build_joint_item_rows,
	calculate_joint_scrap_quantity,
)
from production_entry_app.production_entry_app.report.report_utils import (
	get_entry_total_strokes,
	get_parent_quantity_metrics,
	is_production_stock_entry,
)
from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
	_build_shift_doc,
	bootstrap_manufacture_masters,
	make_direct_manufacture_entry,
	make_running_shift,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	cleanup_running_shifts,
	ensure_item,
	ensure_stock,
)


def _is_scrap_row(row: Any) -> bool:
	return bool(row.get("is_scrap_item") or row.get("is_legacy_scrap_item") or row.get("type") == "Scrap")


def _make_running_shift_through_api(masters: dict[str, Any]) -> object:
	cleanup_running_shifts()
	draft = _build_shift_doc(masters=masters, status="Draft")
	inserted = frappe.client.insert(draft.as_dict())
	previous_request = getattr(frappe.local, "request", None)
	frappe.local.request = frappe._dict(method="POST")
	try:
		frappe.handler.run_doc_method(method="start_shift", dt="Shift", dn=inserted["name"])
	finally:
		frappe.local.request = previous_request
	return frappe.get_doc("Shift", inserted["name"])


class TestJointProductionCalculations(FrappeTestCase):
	def test_joint_scrap_uses_total_rm_and_both_gross_outputs(self) -> None:
		result = calculate_joint_scrap_quantity(
			total_rm_consumption=49.125,
			lh_gross_qty=40,
			lh_unit_net_weight=0.6,
			rh_gross_qty=41,
			rh_unit_net_weight=0.55,
		)

		self.assertAlmostEqual(result, 2.575, places=6)

	def test_output_value_is_allocated_by_bom_cost_weight(self) -> None:
		allocation = allocate_joint_output_value(
			net_production_value=98.4,
			lh_gross_qty=40,
			lh_bom_unit_cost=1,
			rh_gross_qty=41,
			rh_bom_unit_cost=1.2,
		)

		self.assertAlmostEqual(allocation["LH"], 44.1255605381, places=6)
		self.assertAlmostEqual(allocation["RH"], 54.2744394619, places=6)
		self.assertAlmostEqual(sum(allocation.values()), 98.4, places=6)

	def test_report_strokes_use_the_single_physical_joint_stroke_count(self) -> None:
		strokes, rejection_qty = get_entry_total_strokes(
			{
				"name": "STE-JOINT-1",
				"custom_pea_is_joint_lh_rh": 1,
				"custom_pea_total_strokes": 41,
				"fg_completed_qty": 0,
			},
			good_qty_map={"STE-JOINT-1": 80},
			rejection_qty_map={"STE-JOINT-1": 1},
		)

		self.assertEqual((strokes, rejection_qty), (41, 1))

	def test_reports_include_joint_repack_but_exclude_generic_repack(self) -> None:
		self.assertTrue(is_production_stock_entry({"purpose": "Manufacture"}))
		self.assertTrue(is_production_stock_entry({"purpose": "Repack", "custom_pea_is_joint_lh_rh": 1}))
		self.assertFalse(is_production_stock_entry({"purpose": "Repack"}))


class TestJointProductionStockEntryType(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_joint_lh_rh_stock_entry_type_requires_repack_purpose(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": f"Joint Manufacture {frappe.generate_hash(length=6)}",
				"purpose": "Manufacture",
				"custom_pea_joint_lh_rh_production": 1,
			}
		)

		with self.assertRaisesRegex(frappe.ValidationError, "must use Repack purpose"):
			doc.insert(ignore_permissions=True)


class TestJointProductionItems(FrappeTestCase):
	def setUp(self) -> None:
		self.masters = bootstrap_manufacture_masters()
		suffix = frappe.generate_hash(length=6)
		self.lh_item = ensure_item(f"_Joint_LH_{suffix}")
		self.rh_item = ensure_item(f"_Joint_RH_{suffix}")
		self.rm_item = ensure_item(f"_Joint_RM_{suffix}", stock_uom="Kg")
		self.scrap_item = ensure_item(f"_Joint_Scrap_{suffix}", stock_uom="Kg")
		self.lh_bom = self._make_bom(self.lh_item, scrap_qty=1.125)
		self.rh_bom = self._make_bom(self.rh_item, scrap_qty=2.125)
		frappe.db.set_value(
			"Item",
			self.lh_item,
			{"custom_pea_has_die_tool": 1, "custom_pea_stroke_capacity": 10000},
			update_modified=False,
		)
		self.stock_entry_type = f"Joint Repack {suffix}"
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": self.stock_entry_type,
				"purpose": "Repack",
				"custom_pea_joint_lh_rh_production": 1,
			}
		).insert(ignore_permissions=True)

	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_builds_one_rm_two_side_outputs_rejection_and_joint_scrap(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"purpose": "Repack",
				"company": self.masters["company"],
				"from_warehouse": self.masters["wip_warehouse"],
				"to_warehouse": self.masters["fg_warehouse"],
				"custom_pea_is_joint_lh_rh": 1,
				"custom_pea_lh_bom": self.lh_bom,
				"custom_pea_lh_gross_qty": 40,
				"custom_pea_lh_rejection_qty": 1,
				"custom_pea_rh_bom": self.rh_bom,
				"custom_pea_rh_gross_qty": 41,
				"custom_pea_rh_rejection_qty": 0,
				"custom_pea_total_strokes": 41,
				"custom_pea_die_tool_item": self.lh_item,
				"custom_pea_total_rm_consumption": 49.125,
			}
		)

		rows = build_joint_item_rows(doc)

		self.assertEqual(len([row for row in rows if row.get("s_warehouse")]), 1)
		self.assertEqual(sum(row["qty"] for row in rows if row.get("s_warehouse")), 49.125)
		self.assertEqual(
			[
				(row["custom_pea_joint_output_side"], row["qty"])
				for row in rows
				if row.get("is_finished_item")
				and not row.get("custom_pea_is_rejection_item")
				and not _is_scrap_row(row)
			],
			[("LH", 39.0), ("RH", 41.0)],
		)
		rejection = next(row for row in rows if row.get("custom_pea_is_rejection_item"))
		self.assertEqual((rejection["custom_pea_joint_output_side"], rejection["qty"]), ("LH", 1.0))
		scrap = next(row for row in rows if _is_scrap_row(row))
		self.assertEqual(scrap["item_code"], self.scrap_item)
		self.assertGreater(scrap["qty"], 0)
		self.assertAlmostEqual(doc.custom_pea_joint_scrap_qty, scrap["qty"], places=6)

	def test_joint_repack_can_be_inserted_with_native_stock_entry_items(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)

		doc.insert(ignore_permissions=True)

		self.assertEqual(doc.docstatus, 0)
		self.assertEqual(len([row for row in doc.items if row.s_warehouse]), 1)
		self.assertEqual(
			[
				(row.custom_pea_joint_output_side, row.qty)
				for row in doc.items
				if row.custom_pea_is_rejection_item
			],
			[("LH", 1.0)],
		)
		self.assertEqual(
			{
				row.custom_pea_joint_output_side
				for row in doc.items
				if row.is_finished_item and not _is_scrap_row(row)
			},
			{"LH", "RH"},
		)

	def test_joint_items_are_available_through_the_stock_entry_api(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		doc.set("items", [])

		rows = get_joint_production_items(json.dumps(doc.as_dict(), default=str))

		self.assertEqual(len([row for row in rows if row.get("s_warehouse")]), 1)
		self.assertEqual(
			{
				row.get("custom_pea_joint_output_side")
				for row in rows
				if row.get("is_finished_item") and not _is_scrap_row(row)
			},
			{"LH", "RH"},
		)

	def test_total_rm_consumption_must_match_the_single_rm_item_total(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		rm_row = next(row for row in doc.items if row.s_warehouse)
		rm_row.qty = 49
		rm_row.transfer_qty = 49

		with self.assertRaisesRegex(frappe.ValidationError, "Total RM Consumption"):
			doc.insert(ignore_permissions=True)

	def test_output_rows_are_not_compared_to_expected_quantities(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		lh_good_row = next(
			row
			for row in doc.items
			if row.custom_pea_joint_output_side == "LH" and not row.custom_pea_is_rejection_item
		)
		lh_good_row.qty = 38
		lh_good_row.transfer_qty = 38

		doc.insert(ignore_permissions=True)

		self.assertEqual(doc.docstatus, 0)

	def test_api_e2e_shift_start_joint_submit_and_cancel_reverses_everything(self) -> None:
		shift = _make_running_shift_through_api(self.masters)
		self.assertEqual(shift.status, "Running")
		inserted = frappe.client.insert(self._make_joint_entry(shift).as_dict())
		submitted = frappe.client.submit(inserted)
		doc = frappe.get_doc("Stock Entry", submitted["name"])

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.custom_pea_ok_qty, 80)
		self.assertAlmostEqual(doc.custom_pea_actual_spm, 41 / 45, places=6)
		self.assertTrue(
			frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": doc.name, "is_cancelled": 0},
				pluck="name",
			)
		)
		sle_value_by_detail = {
			row.voucher_detail_no: float(row.stock_value_difference or 0)
			for row in frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": doc.name, "is_cancelled": 0},
				fields=["voucher_detail_no", "stock_value_difference"],
			)
		}
		side_values = {
			side: sum(
				sle_value_by_detail.get(row.name, 0)
				for row in doc.items
				if row.custom_pea_joint_output_side == side
			)
			for side in ("LH", "RH")
		}
		lh_bom = frappe.get_doc("BOM", self.lh_bom)
		rh_bom = frappe.get_doc("BOM", self.rh_bom)
		expected_ratio = (40 * lh_bom.total_cost / lh_bom.quantity) / (
			41 * rh_bom.total_cost / rh_bom.quantity
		)
		self.assertAlmostEqual(side_values["LH"] / side_values["RH"], expected_ratio, places=4)
		incoming_value = sum(value for value in sle_value_by_detail.values() if value > 0)
		outgoing_value = -sum(value for value in sle_value_by_detail.values() if value < 0)
		self.assertAlmostEqual(incoming_value, outgoing_value, places=5)
		self.assertEqual(get_parent_quantity_metrics([doc.name])[doc.name]["good_qty"], 80)
		self.assertEqual(
			frappe.db.get_value("Die Tool Counter", self.lh_item, "current_stroke_count"),
			41,
		)
		summary = get_shift_summary(shift.name)["snapshot"]
		self.assertEqual(summary["entry_count"], 1)
		self.assertEqual(summary["total_qty"], 81)
		self.assertEqual(summary["ok_qty"], 80)
		self.assertEqual(summary["rejection_qty"], 1)
		self.assertAlmostEqual(summary["overall_throughput_spm"], 41 / 45, places=6)

		frappe.client.cancel("Stock Entry", doc.name)
		doc.reload()

		self.assertEqual(doc.docstatus, 2)
		self.assertFalse(
			frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": doc.name, "is_cancelled": 0},
				pluck="name",
			)
		)
		self.assertEqual(
			frappe.db.get_value("Die Tool Counter", self.lh_item, "current_stroke_count"),
			0,
		)

	def test_api_e2e_shift_start_normal_manufacture_submit_and_cancel(self) -> None:
		shift = _make_running_shift_through_api(self.masters)
		self.assertEqual(shift.status, "Running")
		draft = make_direct_manufacture_entry(
			self.masters,
			shift=shift.name,
			fg_qty=100,
			rejection_qty=2,
		)
		doc = frappe.get_doc("Stock Entry", frappe.client.submit(draft.as_dict())["name"])

		self.assertEqual(doc.docstatus, 1)
		self.assertTrue(
			frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": doc.name, "is_cancelled": 0},
				pluck="name",
			)
		)

		frappe.client.cancel("Stock Entry", doc.name)
		doc.reload()

		self.assertEqual(doc.docstatus, 2)
		self.assertFalse(
			frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": doc.name, "is_cancelled": 0},
				pluck="name",
			)
		)

	def _make_joint_entry(self, shift: object) -> object:
		ensure_stock(
			self.rm_item,
			self.masters["wip_warehouse"],
			self.masters["company"],
			target_qty=100,
		)
		start = add_to_date(
			get_datetime(f"{shift.shift_date} {shift.planned_start_time}"),
			minutes=15,
		)
		end = add_to_date(start, minutes=45)
		doc = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"purpose": "Repack",
				"stock_entry_type": self.stock_entry_type,
				"company": self.masters["company"],
				"from_warehouse": self.masters["wip_warehouse"],
				"to_warehouse": self.masters["fg_warehouse"],
				"custom_pea_shift": shift.name,
				"custom_pea_actual_start_date": start,
				"custom_pea_actual_end_date": end,
				"custom_pea_is_joint_lh_rh": 1,
				"custom_pea_lh_bom": self.lh_bom,
				"custom_pea_lh_gross_qty": 40,
				"custom_pea_lh_rejection_qty": 1,
				"custom_pea_rh_bom": self.rh_bom,
				"custom_pea_rh_gross_qty": 41,
				"custom_pea_rh_rejection_qty": 0,
				"custom_pea_total_strokes": 41,
				"custom_pea_die_tool_item": self.lh_item,
				"custom_pea_total_rm_consumption": 49.125,
				"custom_pea_rejection_breakup": [
					{
						"rejection_reason": "Burr",
						"qty": 1,
						"output_side": "LH",
						"item_code": self.lh_item,
					}
				],
			}
		)
		doc.set(
			"items",
			get_joint_production_items(json.dumps(doc.as_dict(), default=str)),
		)
		return doc

	def _make_bom(self, item_code: str, *, scrap_qty: float) -> str:
		values = {
			"doctype": "BOM",
			"item": item_code,
			"company": self.masters["company"],
			"quantity": 100,
			"is_active": 1,
			"items": [{"item_code": self.rm_item, "qty": 49.125, "rate": 50}],
		}
		if frappe.get_meta("BOM", cached=True).has_field("scrap_items"):
			values["scrap_items"] = [{"item_code": self.scrap_item, "stock_qty": scrap_qty, "rate": 10}]
		else:
			values["secondary_items"] = [
				{
					"type": "Scrap",
					"item_code": self.scrap_item,
					"qty": scrap_qty,
					"uom": "Kg",
					"conversion_factor": 1,
					"cost_allocation_per": 0,
					"process_loss_per": 0,
				}
			]
		bom = frappe.get_doc(values).insert(ignore_permissions=True)
		bom.submit()
		return bom.name
