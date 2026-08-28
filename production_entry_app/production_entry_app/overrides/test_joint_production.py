from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import erpnext
import frappe
import frappe.client
import frappe.handler
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, flt, get_datetime

from production_entry_app.production_entry_app.api import (
	get_joint_production_items,
	get_joint_rm_consumption,
	get_joint_stock_entry_type,
)
from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data
from production_entry_app.production_entry_app.compat import IS_V16_OR_GREATER
from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary
from production_entry_app.production_entry_app.joint_production import (
	_get_joint_bom_details,
	allocate_joint_output_value,
	calculate_joint_rm_consumption,
	materialize_joint_production_rows,
	validate_and_apply_joint_production,
)
from production_entry_app.production_entry_app.report.report_utils import (
	get_entry_qty_maps,
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
	ensure_workstation,
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
	def test_v16_secondary_scrap_is_used_when_legacy_table_is_empty(self) -> None:
		bom = frappe._dict(
			name="BOM-JOINT-V16",
			item="FG-V16",
			docstatus=1,
			is_active=1,
			quantity=100,
			total_cost=100,
			meta=frappe._dict(has_field=lambda fieldname: fieldname == "scrap_items"),
			items=[
				frappe._dict(
					item_code="RM-V16",
					stock_qty=49.125,
					qty=49.125,
					stock_uom="Kg",
					uom="Kg",
				)
			],
			scrap_items=[],
			secondary_items=[frappe._dict(type="Scrap", item_code="SCRAP-V16", qty=1.5, rate=10)],
		)

		with (
			patch(
				"production_entry_app.production_entry_app.joint_production.frappe.get_doc",
				return_value=bom,
			),
			patch(
				"production_entry_app.production_entry_app.joint_production._get_item_stock_uoms",
				return_value={"SCRAP-V16": "Kg"},
			),
		):
			details = _get_joint_bom_details(bom.name)

		self.assertEqual(
			[(row.item_code, row.qty, row.uom) for row in details.scrap_items],
			[("SCRAP-V16", 1.5, "Kg")],
		)

	def test_normal_manufacture_rejects_explicit_non_positive_strokes(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			_default_total_strokes,
		)

		for total_strokes in (0, -1):
			with self.subTest(total_strokes=total_strokes):
				entry = frappe.get_doc(
					{
						"doctype": "Stock Entry",
						"purpose": "Manufacture",
						"fg_completed_qty": 100,
						"custom_pea_total_strokes": total_strokes,
					}
				)
				with self.assertRaisesRegex(frappe.ValidationError, "greater than zero"):
					_default_total_strokes(entry)

	def test_joint_rm_consumption_adds_bom_sheet_capacity_shares(self) -> None:
		self.assertAlmostEqual(
			calculate_joint_rm_consumption(
				lh_gross_qty=39,
				lh_bom_quantity=77,
				lh_rm_qty=39.3,
				rh_gross_qty=38,
				rh_bom_quantity=77,
				rh_rm_qty=39.3,
			),
			39.3,
			places=6,
		)
		self.assertAlmostEqual(
			calculate_joint_rm_consumption(
				lh_gross_qty=77,
				lh_bom_quantity=77,
				lh_rm_qty=39.3,
				rh_gross_qty=77,
				rh_bom_quantity=77,
				rh_rm_qty=39.3,
			),
			78.6,
			places=6,
		)

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

	def test_configured_joint_repack_type_is_available_to_the_stock_entry_form(self) -> None:
		expected = f"Joint Repack {frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": expected,
				"purpose": "Repack",
				"custom_pea_joint_lh_rh_production": 1,
			}
		).insert(ignore_permissions=True)
		stock_entry_type = get_joint_stock_entry_type()

		self.assertEqual(stock_entry_type, expected)
		self.assertEqual(frappe.db.get_value("Stock Entry Type", stock_entry_type, "purpose"), "Repack")
		self.assertEqual(
			frappe.db.get_value(
				"Stock Entry Type",
				stock_entry_type,
				"custom_pea_joint_lh_rh_production",
			),
			1,
		)


class TestJointProductionItems(FrappeTestCase):
	def setUp(self) -> None:
		self.masters = bootstrap_manufacture_masters()
		suffix = frappe.generate_hash(length=6)
		self.lh_item = ensure_item(f"_Joint_LH_{suffix}")
		self.rh_item = ensure_item(f"_Joint_RH_{suffix}")
		self.rm_item = ensure_item(f"_Joint_RM_{suffix}", stock_uom="Kg")
		self.scrap_item = ensure_item(f"_Joint_Scrap_{suffix}", stock_uom="Kg")
		self.scrap_nos_item = ensure_item(f"_Joint_Scrap_Nos_{suffix}", stock_uom="Nos")
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
		frappe.local.enable_perpetual_inventory = {}

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
				"custom_pea_total_rm_consumption": 1,
			}
		)

		rows = materialize_joint_production_rows(doc)

		self.assertAlmostEqual(doc.custom_pea_total_rm_consumption, 39.79125, places=6)
		self.assertEqual(len([row for row in rows if row.get("s_warehouse")]), 1)
		self.assertAlmostEqual(
			sum(row["qty"] for row in rows if row.get("s_warehouse")),
			39.79125,
			places=6,
		)
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

	def test_materializes_every_bom_scrap_item_with_mixed_uoms(self) -> None:
		rh_only_scrap_item = ensure_item(
			f"_Joint_RH_Only_Scrap_{frappe.generate_hash(length=6)}",
			stock_uom="Kg",
		)
		lh_bom = self._make_bom(
			self.lh_item,
			scrap_items=[(self.scrap_item, 1.125, 10), (self.scrap_nos_item, 2, 4)],
		)
		rh_bom = self._make_bom(
			self.rh_item,
			scrap_items=[
				(self.scrap_item, 2.125, 10),
				(self.scrap_nos_item, 20, 4),
				(rh_only_scrap_item, 0.5, 2),
			],
		)
		shift = make_running_shift(self.masters)

		doc = self._make_joint_entry(shift, lh_bom=lh_bom, rh_bom=rh_bom)
		doc.insert(ignore_permissions=True)

		scrap_rows = {row.item_code: row for row in doc.items if _is_scrap_row(row)}
		self.assertEqual(set(scrap_rows), {self.scrap_item, self.scrap_nos_item, rh_only_scrap_item})
		self.assertAlmostEqual(scrap_rows[self.scrap_item].qty, 1.32125, places=6)
		self.assertEqual(scrap_rows[self.scrap_item].stock_uom, "Kg")
		self.assertEqual(scrap_rows[self.scrap_nos_item].qty, 9)
		self.assertEqual(scrap_rows[self.scrap_nos_item].stock_uom, "Nos")
		self.assertAlmostEqual(scrap_rows[rh_only_scrap_item].qty, 0.205, places=6)

	def test_fetch_items_rounds_aggregated_whole_number_scrap_half_up(self) -> None:
		lh_bom = self._make_bom(
			self.lh_item,
			scrap_items=[(self.scrap_nos_item, 1, 4)],
		)
		rh_bom = self._make_bom(
			self.rh_item,
			scrap_items=[(self.scrap_nos_item, 1, 4)],
		)
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift, lh_bom=lh_bom, rh_bom=rh_bom)
		doc.custom_pea_lh_gross_qty = 49
		doc.custom_pea_rh_gross_qty = 1
		doc.custom_pea_total_strokes = 49
		doc.set("items", get_joint_production_items(json.dumps(doc.as_dict(), default=str)))

		doc.insert(ignore_permissions=True)

		scrap_row = next(row for row in doc.items if _is_scrap_row(row))
		self.assertEqual(scrap_row.item_code, self.scrap_nos_item)
		self.assertEqual(scrap_row.stock_uom, "Nos")
		self.assertEqual(scrap_row.qty, 1)
		self.assertEqual(scrap_row.basic_rate, 2)

		doc.submit()
		self.assertTrue(
			frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": doc.name, "is_cancelled": 0},
				pluck="name",
			)
		)
		doc.cancel()
		self.assertFalse(
			frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": doc.name, "is_cancelled": 0},
				pluck="name",
			)
		)

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

	def test_joint_rm_consumption_is_available_through_the_stock_entry_api(self) -> None:
		self.assertAlmostEqual(
			get_joint_rm_consumption(
				lh_bom=self.lh_bom,
				rh_bom=self.rh_bom,
				lh_gross_qty=101,
				rh_gross_qty=41,
			),
			69.7575,
			places=6,
		)

	def test_joint_boms_reject_different_rm_quantities(self) -> None:
		lh_bom = self._make_bom(self.lh_item, bom_quantity=77, rm_qty=39.3, scrap_qty=1.125)
		rh_bom = self._make_bom(self.rh_item, bom_quantity=77, rm_qty=40, scrap_qty=2.125)
		shift = make_running_shift(self.masters)

		with self.assertRaisesRegex(frappe.ValidationError, "same raw material quantity"):
			self._make_joint_entry(shift, lh_bom=lh_bom, rh_bom=rh_bom)

	def test_total_rm_consumption_must_match_the_single_rm_item_total(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		rm_row = next(row for row in doc.items if row.s_warehouse)
		rm_row.qty = 49
		rm_row.transfer_qty = 49

		with self.assertRaisesRegex(frappe.ValidationError, "Total RM Consumption"):
			doc.insert(ignore_permissions=True)

	def test_stale_output_quantity_requires_fetch_items_again(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		lh_good_row = next(
			row
			for row in doc.items
			if row.custom_pea_joint_output_side == "LH" and not row.custom_pea_is_rejection_item
		)
		lh_good_row.qty = 38
		lh_good_row.transfer_qty = 38

		with self.assertRaisesRegex(frappe.ValidationError, "Run Fetch Items again"):
			doc.insert(ignore_permissions=True)

	def test_split_and_reordered_rows_preserve_the_item_table(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		rm_row = next(row for row in doc.items if row.s_warehouse)
		rh_row = next(
			row
			for row in doc.items
			if row.custom_pea_joint_output_side == "RH" and not row.custom_pea_is_rejection_item
		)
		rm_row.qty = 20
		rm_row.transfer_qty = 20
		rh_row.qty = 20
		rh_row.transfer_qty = 20
		self._append_split_row(doc, rm_row, qty=19.79125)
		self._append_split_row(doc, rh_row, qty=21)
		doc.set("items", list(reversed(doc.items)))
		expected_rows = len(doc.items)

		doc.insert(ignore_permissions=True)

		self.assertEqual(len(doc.items), expected_rows)
		self.assertAlmostEqual(
			sum(row.qty * row.conversion_factor for row in doc.items if row.s_warehouse),
			39.79125,
			places=6,
		)
		self.assertEqual(
			sum(
				row.qty * row.conversion_factor
				for row in doc.items
				if row.custom_pea_joint_output_side == "RH" and not row.custom_pea_is_rejection_item
			),
			41,
		)

	def test_validation_accepts_split_rows_with_distinct_native_logistics(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		frappe.db.set_value("Item", self.rm_item, "has_batch_no", 1, update_modified=False)
		frappe.clear_document_cache("Item", self.rm_item)
		batches = [
			frappe.get_doc(
				{
					"doctype": "Batch",
					"batch_id": f"JOINT-BATCH-{suffix}",
					"item": self.rm_item,
				}
			).insert(ignore_permissions=True)
			for suffix in ("A", "B")
		]
		for bom_name in (self.lh_bom, self.rh_bom):
			bom = frappe.get_doc("BOM", bom_name)
			scrap_rows = bom.get("scrap_items") or bom.get("secondary_items")
			frappe.db.set_value(scrap_rows[0].doctype, scrap_rows[0].name, "rate", 0, update_modified=False)
			frappe.clear_document_cache("BOM", bom_name)
		rm_row = next(row for row in doc.items if row.s_warehouse)
		rm_row.qty = 20
		rm_row.transfer_qty = 20
		rm_row.batch_no = batches[0].name
		rm_row.use_serial_batch_fields = 1
		self._append_split_row(doc, rm_row, qty=19.79125)
		doc.items[-1].batch_no = batches[1].name
		doc.items[-1].use_serial_batch_fields = 1

		doc.insert(ignore_permissions=True)

		self.assertEqual(
			[row.batch_no for row in doc.items if row.s_warehouse],
			[batches[0].name, batches[1].name],
		)

	def test_validation_and_valuation_use_stock_quantity_for_uom_conversions(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		lh_item = frappe.get_doc("Item", self.lh_item)
		lh_item.append("uoms", {"uom": "Pair", "conversion_factor": 2})
		lh_item.save(ignore_permissions=True)
		lh_row = next(
			row
			for row in doc.items
			if row.custom_pea_joint_output_side == "LH" and not row.custom_pea_is_rejection_item
		)
		lh_row.uom = "Pair"
		lh_row.qty = 19.5
		lh_row.conversion_factor = 2
		lh_row.transfer_qty = 38.99
		rm_row = next(row for row in doc.items if row.s_warehouse)
		rm_row.basic_rate = 50
		rm_row.basic_amount = rm_row.qty * rm_row.conversion_factor * rm_row.basic_rate

		validate_and_apply_joint_production(doc)

		rh_row = next(
			row
			for row in doc.items
			if row.custom_pea_joint_output_side == "RH" and not row.custom_pea_is_rejection_item
		)
		expected_rate_ratio = (
			frappe.get_doc("BOM", self.lh_bom).total_cost / frappe.get_doc("BOM", self.rh_bom).total_cost
		)
		self.assertAlmostEqual(lh_row.basic_rate / rh_row.basic_rate, expected_rate_ratio, places=6)

	def test_validation_preserves_native_serial_selection_on_draft_save(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		doc.custom_pea_lh_gross_qty = 1
		doc.custom_pea_lh_rejection_qty = 0
		doc.custom_pea_rh_gross_qty = 1
		doc.custom_pea_rh_rejection_qty = 0
		doc.custom_pea_total_strokes = 1
		doc.set("custom_pea_rejection_breakup", [])
		doc.set("items", get_joint_production_items(json.dumps(doc.as_dict(), default=str)))
		frappe.db.set_value("Item", self.lh_item, "has_serial_no", 1, update_modified=False)
		frappe.clear_document_cache("Item", self.lh_item)
		lh_row = next(
			row
			for row in doc.items
			if row.custom_pea_joint_output_side == "LH" and not row.custom_pea_is_rejection_item
		)
		serial_no = f"JOINT-SERIAL-{frappe.generate_hash(length=8)}"
		lh_row.serial_no = serial_no
		lh_row.use_serial_batch_fields = 1

		doc.insert(ignore_permissions=True)

		self.assertEqual(lh_row.serial_no, serial_no)

	def test_validation_rejects_missing_surplus_and_misclassified_roles(self) -> None:
		shift = make_running_shift(self.masters)
		mutations = {
			"missing row": lambda doc: doc.items.pop(),
			"surplus row": lambda doc: self._append_split_row(doc, doc.items[0], qty=1),
			"wrong item": lambda doc: doc.items[1].set("item_code", self.rm_item),
			"wrong side": lambda doc: doc.items[1].set("custom_pea_joint_output_side", "RH"),
			"wrong rejection marker": lambda doc: doc.items[1].set("custom_pea_is_rejection_item", 1),
		}
		for label, mutate in mutations.items():
			with self.subTest(label=label):
				doc = self._make_joint_entry(shift)
				mutate(doc)
				with self.assertRaisesRegex(frappe.ValidationError, "Run Fetch Items again"):
					validate_and_apply_joint_production(doc)

	def test_tampered_scrap_classification_requires_fetch_items_again(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		scrap_row = next(row for row in doc.items if _is_scrap_row(row))
		scrap_row.is_scrap_item = 0
		scrap_row.is_legacy_scrap_item = 0
		scrap_row.type = None

		with self.assertRaisesRegex(frappe.ValidationError, "Run Fetch Items again"):
			doc.insert(ignore_permissions=True)

	def test_native_scrap_finished_classification_is_preserved_on_save(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		if hasattr(doc, "mark_finished_and_secondary_items"):
			native_classifier = doc.mark_finished_and_secondary_items
		else:
			native_classifier = doc.mark_finished_and_scrap_items
		native_classifier()
		expected_is_finished_item = next(row for row in doc.items if _is_scrap_row(row)).is_finished_item

		doc.insert(ignore_permissions=True)

		scrap_row = next(row for row in doc.items if _is_scrap_row(row))
		self.assertEqual(scrap_row.is_finished_item, expected_is_finished_item)

	def test_both_sides_may_be_fully_rejected(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		doc.custom_pea_lh_rejection_qty = 40
		doc.custom_pea_rh_rejection_qty = 41
		doc.set(
			"custom_pea_rejection_breakup",
			[
				{"rejection_reason": "Burr", "qty": 40, "output_side": "LH", "item_code": self.lh_item},
				{"rejection_reason": "Burr", "qty": 41, "output_side": "RH", "item_code": self.rh_item},
			],
		)
		doc.set("items", get_joint_production_items(json.dumps(doc.as_dict(), default=str)))

		doc.insert(ignore_permissions=True)
		doc.submit()

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.custom_pea_ok_qty, 0)
		self.assertFalse(
			[
				row
				for row in doc.items
				if row.custom_pea_joint_output_side
				and not row.custom_pea_is_rejection_item
				and not _is_scrap_row(row)
			]
		)

	def test_joint_rejection_breakup_api_requires_positive_quantity_and_reason(self) -> None:
		shift = make_running_shift(self.masters)
		invalid_rows = (
			(
				{
					"rejection_reason": "Burr",
					"qty": 0,
					"output_side": "LH",
					"item_code": self.lh_item,
				},
				"quantity greater than 0",
			),
			(
				{
					"qty": 1,
					"output_side": "LH",
					"item_code": self.lh_item,
				},
				"rejection reason",
			),
		)
		for row, message in invalid_rows:
			with self.subTest(message=message):
				doc = self._make_joint_entry(shift)
				doc.set("custom_pea_rejection_breakup", [row])
				with self.assertRaisesRegex(frappe.ValidationError, message):
					frappe.client.insert(doc.as_dict())

		for fieldname, value, message in (
			("output_side", "INVALID", "must specify LH or RH"),
			("item_code", self.rh_item, "must match the selected LH BOM"),
		):
			with self.subTest(fieldname=fieldname):
				doc = self._make_joint_entry(shift)
				doc.custom_pea_rejection_breakup[0].set(fieldname, value)
				with self.assertRaisesRegex(frappe.ValidationError, message):
					frappe.client.insert(doc.as_dict())

		doc = self._make_joint_entry(shift)
		doc.custom_pea_lh_rejection_qty = 0
		doc.set("items", get_joint_production_items(json.dumps(doc.as_dict(), default=str)))
		with self.assertRaisesRegex(frappe.ValidationError, "LH rejection breakup total"):
			frappe.client.insert(doc.as_dict())

	def test_joint_rejection_breakup_api_derives_items_and_rework_total_per_side(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		doc.custom_pea_lh_rejection_qty = 2
		doc.custom_pea_rh_rejection_qty = 3
		doc.set(
			"custom_pea_rejection_breakup",
			[
				{
					"rejection_reason": "Burr",
					"qty": 2,
					"output_side": "LH",
					"is_rework": 1,
				},
				{
					"rejection_reason": "Burr",
					"qty": 3,
					"output_side": "RH",
					"is_rework": 1,
				},
			],
		)
		doc.set("items", get_joint_production_items(json.dumps(doc.as_dict(), default=str)))

		inserted = frappe.client.insert(doc.as_dict())

		self.assertEqual(inserted["custom_pea_rework_qty"], 5)
		self.assertEqual(
			[(row["output_side"], row["item_code"]) for row in inserted["custom_pea_rejection_breakup"]],
			[("LH", self.lh_item), ("RH", self.rh_item)],
		)

	def test_item_bom_quality_reports_attribute_joint_rejection_and_rework_by_side(self) -> None:
		from production_entry_app.production_entry_app.report.item_bom_rejection_hotspots.item_bom_rejection_hotspots import (
			execute as rejection_execute,
		)
		from production_entry_app.production_entry_app.report.item_bom_rework_hotspots.item_bom_rework_hotspots import (
			execute as rework_execute,
		)

		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		doc.custom_pea_lh_rejection_qty = 2
		doc.custom_pea_rh_rejection_qty = 3
		doc.set(
			"custom_pea_rejection_breakup",
			[
				{
					"rejection_reason": "Burr",
					"qty": 2,
					"output_side": "LH",
					"is_rework": 0,
				},
				{
					"rejection_reason": "Burr",
					"qty": 3,
					"output_side": "RH",
					"is_rework": 1,
				},
			],
		)
		doc.set("items", get_joint_production_items(json.dumps(doc.as_dict(), default=str)))
		inserted = frappe.client.insert(doc.as_dict())
		frappe.client.submit(inserted)

		_, rejection_rows = rejection_execute({"custom_pea_shift": shift.name})
		_, rework_rows = rework_execute({"custom_pea_shift": shift.name})
		_, lh_bom_rows = rejection_execute({"custom_pea_shift": shift.name, "bom_no": self.lh_bom})
		rejection_by_item = {row["item_code"]: row for row in rejection_rows}
		rework_by_item = {row["item_code"]: row for row in rework_rows}

		self.assertEqual(
			(rejection_by_item[self.lh_item]["bom_no"], rejection_by_item[self.lh_item]["total_qty"]),
			(self.lh_bom, 40),
		)
		self.assertEqual(rejection_by_item[self.lh_item]["rejection_qty"], 2)
		self.assertEqual(rejection_by_item[self.rh_item]["rejection_qty"], 0)
		self.assertEqual(
			(rework_by_item[self.rh_item]["bom_no"], rework_by_item[self.rh_item]["total_qty"]),
			(self.rh_bom, 41),
		)
		self.assertEqual(rework_by_item[self.rh_item]["rework_qty"], 3)
		self.assertEqual(rework_by_item[self.lh_item]["rework_qty"], 0)
		self.assertEqual([row["item_code"] for row in lh_bom_rows], [self.lh_item])

	def test_each_side_may_individually_be_fully_rejected(self) -> None:
		shift = make_running_shift(self.masters)
		for side, rejection_qty in (("LH", 40), ("RH", 41)):
			with self.subTest(side=side):
				doc = self._make_joint_entry(shift)
				doc.custom_pea_lh_rejection_qty = rejection_qty if side == "LH" else 0
				doc.custom_pea_rh_rejection_qty = rejection_qty if side == "RH" else 0
				doc.set(
					"custom_pea_rejection_breakup",
					[
						{
							"rejection_reason": "Burr",
							"qty": rejection_qty,
							"output_side": side,
							"item_code": self.lh_item if side == "LH" else self.rh_item,
						}
					],
				)
				doc.set("items", get_joint_production_items(json.dumps(doc.as_dict(), default=str)))

				validate_and_apply_joint_production(doc)

				self.assertFalse(
					[
						row
						for row in doc.items
						if row.custom_pea_joint_output_side == side
						and not row.custom_pea_is_rejection_item
						and not _is_scrap_row(row)
					]
				)

	def test_native_additional_cost_allocation_is_preserved(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		expense_account = frappe.get_cached_value(
			"Company",
			self.masters["company"],
			"stock_adjustment_account",
		)
		doc.append(
			"additional_costs",
			{
				"expense_account": expense_account,
				"description": "Joint Production handling",
				"amount": 100,
			},
		)

		doc.insert(ignore_permissions=True)
		doc.submit()

		self.assertEqual(doc.total_additional_costs, 100)
		self.assertAlmostEqual(
			sum(flt(row.additional_cost) for row in doc.items if row.is_finished_item),
			100,
			places=5,
		)
		stock_value_differences = [
			flt(row.get("stock_value_difference"))
			for row in frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": doc.name, "is_cancelled": 0},
				fields=["stock_value_difference"],
			)
		]
		incoming_value = sum(value for value in stock_value_differences if value > 0)
		outgoing_value = -sum(value for value in stock_value_differences if value < 0)
		currency_precision = int(frappe.db.get_single_value("System Settings", "currency_precision") or 2)
		self.assertAlmostEqual(
			incoming_value - outgoing_value,
			100,
			delta=(10**-currency_precision) * len(stock_value_differences),
		)

	def test_api_e2e_shift_start_joint_submit_and_cancel_reverses_everything(self) -> None:
		stock_adjustment_account = frappe.db.get_value(
			"Account",
			{
				"company": self.masters["company"],
				"account_type": "Stock Adjustment",
				"is_group": 0,
			},
			"name",
		)
		frappe.db.set_value(
			"Company",
			self.masters["company"],
			{
				"enable_perpetual_inventory": 1,
				"stock_adjustment_account": stock_adjustment_account,
			},
			update_modified=False,
		)
		frappe.clear_document_cache("Company", self.masters["company"])
		frappe.local.enable_perpetual_inventory = {}
		self.assertEqual(erpnext.is_perpetual_inventory_enabled(self.masters["company"]), 1)
		shift = _make_running_shift_through_api(self.masters)
		self.assertEqual(shift.status, "Running")
		ensure_workstation("Joint Production Timeline", standard_spm=2)
		workstation = (
			frappe.db.get_value("Workstation", {"workstation_name": "Joint Production Timeline"}, "name")
			or "Joint Production Timeline"
		)
		joint_entry = self._make_joint_entry(shift)
		joint_entry.custom_pea_workstation = workstation
		joint_entry.append(
			"additional_costs",
			{
				"expense_account": stock_adjustment_account,
				"description": "Joint Production lifecycle test",
				"amount": 100,
			},
		)
		inserted = frappe.client.insert(joint_entry.as_dict())
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
		gl_entries = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Stock Entry", "voucher_no": doc.name, "is_cancelled": 0},
			pluck="name",
		)
		self.assertTrue(gl_entries)
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
		currency_precision = int(frappe.db.get_single_value("System Settings", "currency_precision") or 2)
		self.assertAlmostEqual(
			incoming_value - outgoing_value,
			100,
			delta=(10**-currency_precision) * len(sle_value_by_detail),
		)
		self.assertEqual(get_parent_quantity_metrics([doc.name])[doc.name]["good_qty"], 80)
		_, _, fg_item_map = get_entry_qty_maps([doc.name], include_fg_item=True)
		self.assertNotEqual(fg_item_map.get(doc.name), self.scrap_item)
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
		timeline = get_shift_timeline_data("Workstation", workstation)
		self.assertEqual(len(timeline["entries"]), 1)
		self.assertEqual(timeline["entries"][0]["fg_qty"], 80)
		self.assertEqual(timeline["entries"][0]["rejection_qty"], 1)
		self.assertEqual(timeline["entries"][0]["ok_qty"], 80)

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
		self.assertFalse(
			frappe.get_all(
				"GL Entry",
				filters={"voucher_type": "Stock Entry", "voucher_no": doc.name, "is_cancelled": 0},
				pluck="name",
			)
		)
		self.assertEqual(
			frappe.db.get_value("Die Tool Counter", self.lh_item, "current_stroke_count"),
			0,
		)

		amended = frappe.copy_doc(doc)
		amended.docstatus = 0
		amended.amended_from = doc.name
		amended.insert(ignore_permissions=True)
		amended.submit()
		self.assertEqual(amended.docstatus, 1)
		self.assertEqual(amended.amended_from, doc.name)
		self.assertTrue(
			frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": amended.name, "is_cancelled": 0},
				pluck="name",
			)
		)
		self.assertTrue(
			frappe.get_all(
				"GL Entry",
				filters={"voucher_type": "Stock Entry", "voucher_no": amended.name, "is_cancelled": 0},
				pluck="name",
			)
		)

	def test_api_e2e_shift_start_normal_manufacture_submit_and_cancel(self) -> None:
		shift = _make_running_shift_through_api(self.masters)
		self.assertEqual(shift.status, "Running")
		frappe.db.set_value(
			"Item",
			self.masters["fg_item"],
			{
				"custom_pea_has_die_tool": 1,
				"custom_pea_stroke_capacity": 10000,
			},
			update_modified=False,
		)
		frappe.db.delete("Die Tool Counter", {"die_tool_item": self.masters["fg_item"]})
		draft = make_direct_manufacture_entry(
			self.masters,
			shift=shift.name,
			fg_qty=100,
			rejection_qty=2,
		)
		self.assertEqual(draft.custom_pea_total_strokes, 100)
		draft.custom_pea_total_strokes = 40
		doc = frappe.get_doc("Stock Entry", frappe.client.submit(draft.as_dict())["name"])

		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.custom_pea_total_strokes, 40)
		self.assertAlmostEqual(doc.custom_pea_actual_spm, 40 / 45, places=6)
		self.assertEqual(
			frappe.db.get_value("Die Tool Counter", self.masters["fg_item"], "current_stroke_count"),
			40,
		)
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
		self.assertEqual(
			frappe.db.get_value("Die Tool Counter", self.masters["fg_item"], "current_stroke_count"),
			0,
		)
		self.assertFalse(
			frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": doc.name, "is_cancelled": 0},
				pluck="name",
			)
		)

		amended = frappe.copy_doc(doc)
		amended.docstatus = 0
		amended.amended_from = doc.name
		amended.insert(ignore_permissions=True)
		self.assertEqual(amended.custom_pea_total_strokes, 40)

		amended.submit()

		self.assertEqual(amended.docstatus, 1)
		self.assertEqual(amended.amended_from, doc.name)
		self.assertEqual(amended.custom_pea_total_strokes, 40)
		self.assertEqual(
			frappe.db.get_value("Die Tool Counter", self.masters["fg_item"], "current_stroke_count"),
			40,
		)

	def _make_joint_entry(
		self,
		shift: object,
		*,
		lh_bom: str | None = None,
		rh_bom: str | None = None,
	) -> object:
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
				"custom_pea_lh_bom": lh_bom or self.lh_bom,
				"custom_pea_lh_gross_qty": 40,
				"custom_pea_lh_rejection_qty": 1,
				"custom_pea_rh_bom": rh_bom or self.rh_bom,
				"custom_pea_rh_gross_qty": 41,
				"custom_pea_rh_rejection_qty": 0,
				"custom_pea_total_strokes": 41,
				"custom_pea_die_tool_item": self.lh_item,
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

	def _append_split_row(self, doc: object, source_row: object, *, qty: float) -> None:
		row = {
			fieldname: source_row.get(fieldname)
			for fieldname in (
				"item_code",
				"item_name",
				"description",
				"uom",
				"stock_uom",
				"conversion_factor",
				"s_warehouse",
				"t_warehouse",
				"bom_no",
				"is_finished_item",
				"is_scrap_item",
				"is_legacy_scrap_item",
				"type",
				"set_basic_rate_manually",
				"basic_rate",
				"custom_pea_is_rejection_item",
				"custom_pea_joint_output_side",
			)
		}
		row.update({"qty": qty, "transfer_qty": qty})
		doc.append("items", row)

	def _make_bom(
		self,
		item_code: str,
		*,
		bom_quantity: float = 100,
		rm_qty: float = 49.125,
		scrap_qty: float | None = None,
		scrap_items: list[tuple[str, float, float]] | None = None,
	) -> str:
		scrap_items = scrap_items or [(self.scrap_item, flt(scrap_qty), 10)]
		values = {
			"doctype": "BOM",
			"item": item_code,
			"company": self.masters["company"],
			"quantity": bom_quantity,
			"is_active": 1,
			"items": [{"item_code": self.rm_item, "qty": rm_qty, "rate": 50}],
		}
		if IS_V16_OR_GREATER:
			values["secondary_items"] = [
				{
					"type": "Scrap",
					"item_code": scrap_item,
					"qty": qty,
					"uom": frappe.db.get_value("Item", scrap_item, "stock_uom"),
					"conversion_factor": 1,
					"rate": rate,
					"cost_allocation_per": 0,
					"process_loss_per": 0,
				}
				for scrap_item, qty, rate in scrap_items
			]
		else:
			values["scrap_items"] = [
				{"item_code": scrap_item, "stock_qty": qty, "rate": rate}
				for scrap_item, qty, rate in scrap_items
			]
		bom = frappe.get_doc(values).insert(ignore_permissions=True)
		bom.submit()
		return bom.name
