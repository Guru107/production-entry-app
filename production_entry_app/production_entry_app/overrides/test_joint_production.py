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
	get_items_with_rejection,
	get_joint_production_items,
	get_joint_rm_consumption,
	get_joint_stock_entry_type,
)
from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data
from production_entry_app.production_entry_app.doctype.shift.shift import (
	_get_entry_summary_quantities,
	get_shift_summary,
)
from production_entry_app.production_entry_app.joint_production import (
	_get_bom_scrap_item_details,
	_get_item_details,
	_get_joint_bom_details,
	_set_scrap_row_classification,
	allocate_joint_output_value,
	calculate_joint_rm_consumption,
	is_joint_lh_rh_production,
	materialize_joint_production_rows,
	validate_and_apply_joint_production,
)
from production_entry_app.production_entry_app.report.report_utils import (
	get_entry_output_quantities,
	get_entry_qty_maps,
	get_entry_total_strokes,
	get_finished_item_maps,
	get_parent_quantity_metrics,
	is_production_stock_entry,
)
from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
	_build_shift_doc,
	bootstrap_manufacture_masters,
	make_direct_manufacture_entry,
	make_running_shift,
)
from production_entry_app.production_entry_app.utils.rejection_warehouse import resolve_rejection_warehouse
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	build_joint_bom_scrap_row,
	cleanup_running_shifts,
	ensure_item,
	ensure_joint_test_bom,
	ensure_stock,
	ensure_workstation,
	get_joint_bom_scrap_rate,
	set_test_branch_warehouse_defaults,
)


def _is_scrap_row(row: Any) -> bool:
	return bool(
		row.get("is_scrap_item")
		or row.get("is_legacy_scrap_item")
		or row.get("secondary_item_type") == "Scrap"
		or row.get("type") == "Scrap"
	)


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
	def test_joint_bom_scrap_fixture_supports_rate_schema(self) -> None:
		meta = frappe._dict(has_field=lambda fieldname: fieldname == "rate")

		row = build_joint_bom_scrap_row(
			secondary_item_meta=meta,
			item_code="SCRAP-OLD",
			qty=2,
			rate=7,
			uom="Kg",
		)

		self.assertEqual(row["rate"], 7)
		self.assertEqual(row["type"], "Scrap")
		self.assertNotIn("valuation_type", row)
		self.assertEqual(get_joint_bom_scrap_rate(frappe._dict(row)), 7)

	def test_joint_bom_scrap_fixture_supports_manual_cost_schema(self) -> None:
		meta = frappe._dict(
			has_field=lambda fieldname: fieldname in {"secondary_item_type", "valuation_type", "cost"}
		)

		row = build_joint_bom_scrap_row(
			secondary_item_meta=meta,
			item_code="SCRAP-NEW",
			qty=2,
			rate=7,
			uom="Kg",
		)

		self.assertEqual(row["valuation_type"], "Manual")
		self.assertEqual(row["cost"], 14)
		self.assertNotIn("rate", row)
		self.assertEqual(get_joint_bom_scrap_rate(frappe._dict(row)), 7)
		self.assertEqual(get_joint_bom_scrap_rate(frappe._dict(cost=14, stock_qty=2)), 7)
		self.assertEqual(get_joint_bom_scrap_rate(frappe._dict(cost=14, stock_qty=0, qty=0)), 0)

	def test_right_first_time_quantities_match_across_production_modes(self) -> None:
		normal_entry = frappe._dict(
			purpose="Manufacture",
			fg_completed_qty=100,
			custom_pea_rejection_qty=5,
			custom_pea_rework_qty=3,
			custom_pea_total_strokes=100,
		)
		joint_entry = frappe._dict(
			purpose="Repack",
			custom_pea_is_joint_lh_rh=1,
			custom_pea_lh_gross_qty=40,
			custom_pea_lh_rejection_qty=2,
			custom_pea_rh_gross_qty=60,
			custom_pea_rh_rejection_qty=3,
			custom_pea_rework_qty=3,
			custom_pea_total_strokes=100,
		)
		normal_report_metrics = {
			"good_qty": 95,
			"rejection_qty": 2,
			"rework_qty": 3,
			"total_rejected_qty": 5,
		}

		normal_report_quantities = get_entry_output_quantities(
			normal_entry,
			normal_metrics=normal_report_metrics,
		)
		joint_report_quantities = get_entry_output_quantities(joint_entry)

		self.assertEqual(normal_report_quantities, joint_report_quantities)
		self.assertEqual(tuple(normal_report_quantities), (100, 95, 5))
		self.assertEqual(_get_entry_summary_quantities(normal_entry), (100, 95, 5, 100))
		self.assertEqual(_get_entry_summary_quantities(joint_entry), (100, 95, 5, 100))

	def test_joint_item_details_are_loaded_in_one_query(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.joint_production.frappe.get_list",
			return_value=[
				{"name": "RM", "item_name": "Raw Material", "description": "RM", "stock_uom": "Kg"},
				{"name": "FG", "item_name": "Finished Good", "description": "FG", "stock_uom": "Nos"},
			],
		) as get_list:
			details = _get_item_details(["RM", "FG", "RM"])

		self.assertEqual(set(details), {"RM", "FG"})
		get_list.assert_called_once_with(
			"Item",
			filters={"name": ["in", ["RM", "FG"]]},
			fields=["name", "item_name", "description", "stock_uom"],
		)

	def test_scrap_rate_fallback_uses_the_correct_cross_version_total_field(self) -> None:
		cases = (
			(frappe._dict(doctype="BOM Secondary Item", item_code="SCRAP", qty=2, rate=0, cost=8), 4),
			(
				frappe._dict(doctype="BOM Scrap Item", item_code="SCRAP", stock_qty=2, rate=0, amount=10),
				5,
			),
		)
		for row, expected_rate in cases:
			with self.subTest(doctype=row.doctype):
				details = _get_bom_scrap_item_details(row, {"SCRAP": "Kg"})
				self.assertEqual(details.rate, expected_rate)

	def test_scrap_row_classification_supports_each_stock_entry_detail_schema(self) -> None:
		for fieldname in ("is_scrap_item", "type", "secondary_item_type"):
			with self.subTest(fieldname=fieldname):
				row = {}
				meta = frappe._dict(has_field=lambda candidate: candidate == fieldname)
				with patch(
					"production_entry_app.production_entry_app.joint_production.frappe.get_meta",
					return_value=meta,
				):
					_set_scrap_row_classification(row)

				self.assertTrue(_is_scrap_row(row))

	def test_v16_secondary_scrap_supports_both_type_fieldnames(self) -> None:
		for type_fieldname in ("type", "secondary_item_type"):
			with self.subTest(type_fieldname=type_fieldname):
				secondary_item = frappe._dict(item_code="SCRAP-V16", qty=1.5, rate=10)
				secondary_item[type_fieldname] = "Scrap"
				bom = frappe._dict(
					name="BOM-JOINT-V16",
					item="FG-V16",
					docstatus=1,
					is_active=1,
					quantity=100,
					total_cost=100,
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
					secondary_items=[secondary_item],
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

	def test_normal_manufacture_defaults_zero_strokes_and_rejects_negative_strokes(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			_default_total_strokes,
		)

		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"purpose": "Manufacture",
				"fg_completed_qty": 100,
				"custom_pea_total_strokes": 0,
			}
		)
		_default_total_strokes(entry)
		self.assertEqual(entry.custom_pea_total_strokes, 100)

		entry.custom_pea_total_strokes = -1
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

	def test_joint_stock_entry_type_lookup_is_cached_on_the_document(self) -> None:
		doc = frappe.new_doc("Stock Entry")
		doc.stock_entry_type = "Joint LH RH Repack"
		with patch.object(frappe.db, "get_value", return_value=1) as get_value:
			self.assertTrue(is_joint_lh_rh_production(doc))
			self.assertTrue(is_joint_lh_rh_production(doc))

		get_value.assert_called_once_with(
			"Stock Entry Type",
			"Joint LH RH Repack",
			"custom_pea_joint_lh_rh_production",
		)

	def test_rejection_warehouse_requires_explicit_shift_or_settings_configuration(self) -> None:
		doc = frappe.new_doc("Stock Entry")
		doc.branch = None
		with self.assertRaisesRegex(frappe.ValidationError, "set a Rejection Warehouse"):
			resolve_rejection_warehouse(doc)


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
	def test_fetch_items_defaults_survive_joint_draft_save(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		frappe.db.set_value("Shift", shift.name, "work_in_progress_warehouse", None)
		doc.from_warehouse = None
		doc.to_warehouse = None
		doc.branch = self.masters["branch"]
		for shift_name in (shift.name, None):
			with self.subTest(shift=shift_name):
				entry = frappe.copy_doc(doc)
				entry.custom_pea_shift = shift_name
				entry.set("items", get_joint_production_items(json.dumps(entry.as_dict(), default=str)))
				entry.insert(ignore_permissions=True)
				entry.submit()
				self.assertEqual(entry.docstatus, 1)
				self.assertEqual(
					{row.s_warehouse for row in entry.items if row.s_warehouse},
					{self.masters["wip_warehouse"]},
				)
				self.assertEqual(
					{row.t_warehouse for row in entry.items if _is_scrap_row(row)},
					{self.masters["scrap_warehouse"]},
				)
				entry.cancel()

	def test_fetch_defaults_cannot_bypass_warehouse_read_permission(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		payload = doc.as_dict()
		payload.update(from_warehouse=None, to_warehouse=None)
		for joint in (True, False):
			with self.subTest(joint=joint):
				if not joint:
					payload.update(
						purpose="Manufacture",
						stock_entry_type="Manufacture",
						custom_pea_is_joint_lh_rh=0,
						bom_no=self.lh_bom,
						fg_completed_qty=40,
					)
				fetch = get_joint_production_items if joint else get_items_with_rejection
				with patch.object(
					frappe,
					"has_permission",
					side_effect=lambda doctype, *args, **kwargs: doctype != "Warehouse",
				):
					with self.assertRaises(frappe.PermissionError):
						fetch(json.dumps(payload, default=str))

	def test_fetch_items_routes_both_flows_to_shift_warehouses(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		set_test_branch_warehouse_defaults(
			self.masters["company"],
			self.masters["branch"],
			scrap_warehouse=self.masters["rm_warehouse"],
			rejection_warehouse=self.masters["fg_warehouse"],
		)
		for joint in (True, False):
			with self.subTest(joint=joint):
				payload = doc.as_dict()
				if not joint:
					payload.update(
						purpose="Manufacture",
						stock_entry_type="Manufacture",
						custom_pea_is_joint_lh_rh=0,
						bom_no=self.lh_bom,
						fg_completed_qty=40,
						custom_pea_rejection_qty=1,
					)
				fetch = get_joint_production_items if joint else get_items_with_rejection
				rows = fetch(json.dumps(payload, default=str))
				self.assertEqual(
					{row["s_warehouse"] for row in rows if row.get("s_warehouse")},
					{self.masters["wip_warehouse"]},
				)
				self.assertEqual(
					{row["t_warehouse"] for row in rows if _is_scrap_row(row)},
					{self.masters["scrap_warehouse"]},
				)
				self.assertEqual(
					{row["t_warehouse"] for row in rows if row.get("custom_pea_is_rejection_item")},
					{self.masters["rejection_warehouse"]},
				)
				self.assertEqual(
					{
						row["t_warehouse"]
						for row in rows
						if row.get("t_warehouse")
						and not _is_scrap_row(row)
						and not row.get("custom_pea_is_rejection_item")
					},
					{self.masters["fg_warehouse"]},
				)

	def test_fetch_items_without_shift_uses_company_branch_defaults(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		for joint in (True, False):
			with self.subTest(joint=joint):
				payload = doc.as_dict()
				payload.update(
					custom_pea_shift=None,
					branch=self.masters["branch"],
					from_warehouse=None,
					to_warehouse=None,
				)
				if not joint:
					payload.update(
						purpose="Manufacture",
						stock_entry_type="Manufacture",
						custom_pea_is_joint_lh_rh=0,
						bom_no=self.lh_bom,
						fg_completed_qty=40,
						custom_pea_rejection_qty=1,
					)
				fetch = get_joint_production_items if joint else get_items_with_rejection
				rows = fetch(json.dumps(payload, default=str))
				self.assertEqual(
					{row["s_warehouse"] for row in rows if row.get("s_warehouse")},
					{self.masters["wip_warehouse"]},
				)
				self.assertEqual(
					{row["t_warehouse"] for row in rows if _is_scrap_row(row)},
					{self.masters["scrap_warehouse"]},
				)
				payload["branch"] = None
				with self.assertRaisesRegex(frappe.ValidationError, "Work In Progress Warehouse"):
					fetch(json.dumps(payload, default=str))

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

	def test_report_item_maps_choose_first_good_output_in_detail_order(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		lh_row = next(
			row
			for row in doc.items
			if row.custom_pea_joint_output_side == "LH" and not row.custom_pea_is_rejection_item
		)
		lh_row.qty = 20
		lh_row.transfer_qty = 20
		self._append_split_row(doc, lh_row, qty=19)
		doc.insert(ignore_permissions=True)

		good_qty, rejected_qty = get_entry_qty_maps([doc.name])
		first_items, labels = get_finished_item_maps([doc.name])

		self.assertEqual(first_items, {doc.name: self.lh_item})
		self.assertEqual(labels, {doc.name: f"{self.lh_item} + {self.rh_item}"})
		self.assertEqual(good_qty[doc.name], 80)
		self.assertEqual(rejected_qty[doc.name], 1)

	def test_joint_bom_fixture_does_not_reuse_a_stale_scrap_recipe(self) -> None:
		matching_bom = self._make_bom(self.lh_item, scrap_qty=1.125)
		changed_bom = self._make_bom(self.lh_item, scrap_qty=9.5)

		self.assertEqual(matching_bom, self.lh_bom)
		self.assertNotEqual(changed_bom, matching_bom)

	def test_joint_bom_fixture_uses_company_currency_not_user_currency(self) -> None:
		company_currency = frappe.get_cached_value("Company", self.masters["company"], "default_currency")
		other_currency = "USD" if company_currency != "USD" else "INR"
		item = ensure_item(f"_Joint_Currency_{frappe.generate_hash(length=6)}")
		template = frappe.new_doc("BOM").as_dict()
		template.update(currency=other_currency, conversion_rate=80)
		with patch.dict(frappe.local.new_doc_templates, {"BOM": template}):
			bom = frappe.get_doc("BOM", self._make_bom(item, scrap_qty=1.125))

		self.assertEqual(bom.currency, company_currency)
		self.assertEqual(bom.conversion_rate, 1)
		self.assertGreater(bom.total_cost, 0)

	def test_builds_one_rm_two_side_outputs_rejection_and_joint_scrap(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"purpose": "Repack",
				"company": self.masters["company"],
				"branch": self.masters["branch"],
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
		# Cost these additional BOMs from actual RM stock, not an empty-bin fallback.
		ensure_stock(
			self.rm_item,
			self.masters["wip_warehouse"],
			self.masters["company"],
			target_qty=100,
		)
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

	def test_bom_quantity_one_preserves_joint_calculations_through_submit_and_cancel(self) -> None:
		lh_bom = self._make_bom(
			self.lh_item,
			bom_quantity=1,
			rm_qty=0.5,
			scrap_qty=0.1,
		)
		rh_bom = self._make_bom(
			self.rh_item,
			bom_quantity=1,
			rm_qty=0.5,
			scrap_qty=0.2,
		)
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift, lh_bom=lh_bom, rh_bom=rh_bom)
		doc.custom_pea_lh_gross_qty = 4
		doc.custom_pea_lh_rejection_qty = 1
		doc.custom_pea_rh_gross_qty = 5
		doc.custom_pea_rh_rejection_qty = 0
		doc.custom_pea_total_strokes = 5
		doc.set("items", get_joint_production_items(json.dumps(doc.as_dict(), default=str)))
		rm_row = next(row for row in doc.items if row.s_warehouse)
		rm_row.basic_rate = 50
		rm_row.basic_amount = rm_row.qty * rm_row.conversion_factor * rm_row.basic_rate

		doc.insert(ignore_permissions=True)

		self.assertAlmostEqual(doc.custom_pea_total_rm_consumption, 4.5, places=6)
		scrap_row = next(row for row in doc.items if _is_scrap_row(row))
		self.assertAlmostEqual(scrap_row.qty, 1.4, places=6)
		self.assertAlmostEqual(scrap_row.basic_amount, 14, places=6)
		output_rows = [row for row in doc.items if row.t_warehouse and not _is_scrap_row(row)]
		self.assertEqual(sum(row.qty for row in output_rows), 9)
		self.assertTrue(all(row.basic_rate > 0 for row in output_rows))

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

	def test_joint_items_api_fails_cleanly_when_an_item_cannot_be_loaded(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		doc.set("items", [])
		original_get_list = frappe.get_list

		def omit_rh_item(doctype: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
			rows = original_get_list(doctype, *args, **kwargs)
			if doctype == "Item":
				return [row for row in rows if row.get("name") != self.rh_item]
			return rows

		with patch(
			"production_entry_app.production_entry_app.joint_production.frappe.get_list",
			side_effect=omit_rh_item,
		):
			with self.assertRaisesRegex(frappe.ValidationError, "Unable to load Item"):
				get_joint_production_items(json.dumps(doc.as_dict(), default=str))

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

	def test_joint_rm_consumption_api_requires_both_boms(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "Select both LH and RH BOMs"):
			get_joint_rm_consumption(
				lh_bom=self.lh_bom,
				rh_bom="",
				lh_gross_qty=40,
				rh_gross_qty=41,
			)

	def test_joint_valuation_rejects_scrap_value_above_consumed_rm_value(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_joint_entry(shift)
		rm_row = next(row for row in doc.items if row.s_warehouse)
		rm_row.basic_rate = 0
		rm_row.basic_amount = 0

		with self.assertRaisesRegex(frappe.ValidationError, "scrap value cannot exceed"):
			validate_and_apply_joint_production(doc)

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
			zero_values = {}
			for fieldname in ("rate", "cost", "base_amount", "amount"):
				if scrap_rows[0].meta.has_field(fieldname):
					zero_values[fieldname] = 0
			frappe.db.set_value(
				scrap_rows[0].doctype,
				scrap_rows[0].name,
				zero_values,
				update_modified=False,
			)
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
		scrap_row.secondary_item_type = None
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
				rm_row = next(row for row in doc.items if row.s_warehouse)
				rm_row.basic_rate = 50
				rm_row.basic_amount = rm_row.qty * rm_row.conversion_factor * rm_row.basic_rate

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
		fg_item_map, _item_labels = get_finished_item_maps([doc.name])
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
		rm_row = next(row for row in doc.items if row.s_warehouse)
		rm_row.basic_rate = 50
		rm_row.basic_amount = rm_row.qty * rm_row.conversion_factor * rm_row.basic_rate
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
		return ensure_joint_test_bom(
			item_code=item_code,
			rm_item=self.rm_item,
			scrap_items=scrap_items,
			company=self.masters["company"],
			bom_quantity=bom_quantity,
			rm_qty=rm_qty,
		)
