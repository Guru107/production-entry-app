from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.api_timeline import (
	get_shift_timeline_data,
	get_timeline_cache_prefix,
)
from production_entry_app.production_entry_app.doctype.shift.shift import (
	get_shift_aggregate_production_entries,
	get_shift_summary,
	invalidate_shift_summary_cache,
)
from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
	on_cancel_stock_entry,
	on_submit_stock_entry,
)
from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	iter_stock_entries_in_chunks,
)
from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
	bootstrap_manufacture_masters,
	make_running_shift,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import ensure_workstation


class TestReworkMetricsExclusion(FrappeTestCase):
	def setUp(self) -> None:
		frappe.db.rollback()
		self.rework_stock_entry_type = f"Rework Metrics {frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": self.rework_stock_entry_type,
				"purpose": "Material Transfer",
				"custom_pea_rework_entry": 1,
			}
		).insert(ignore_permissions=True)

	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_rework_submit_and_cancel_do_not_touch_production_counter_or_caches(self) -> None:
		shift_name = f"SHIFT-REWORK-CONTEXT-{frappe.generate_hash(length=8)}"
		workstation = f"Rework Cache WS {frappe.generate_hash(length=6)}"
		summary_key = f"pea:shift_summary:{shift_name}"
		timeline_key = f"{get_timeline_cache_prefix('Workstation', workstation, shift_name)}sentinel"
		cache = frappe.cache()
		cache.set_value(summary_key, "preserve-summary")
		cache.set_value(timeline_key, "preserve-timeline")
		counter_count = frappe.db.count("Die Tool Counter")
		doc = frappe.new_doc("Stock Entry")
		doc.stock_entry_type = self.rework_stock_entry_type
		doc.purpose = "Material Transfer"
		doc.custom_pea_shift = shift_name
		doc.custom_pea_workstation = workstation
		doc.custom_pea_total_strokes = 999

		try:
			on_submit_stock_entry(doc)
			self.assertEqual(cache.get_value(summary_key), "preserve-summary")
			self.assertEqual(cache.get_value(timeline_key), "preserve-timeline")
			self.assertEqual(frappe.db.count("Die Tool Counter"), counter_count)

			on_cancel_stock_entry(doc)
			self.assertEqual(cache.get_value(summary_key), "preserve-summary")
			self.assertEqual(cache.get_value(timeline_key), "preserve-timeline")
			self.assertEqual(frappe.db.count("Die Tool Counter"), counter_count)
		finally:
			cache.delete_value(summary_key)
			cache.delete_value(timeline_key)

	def test_non_rework_hook_payload_without_type_keeps_production_cache_invalidation(self) -> None:
		shift_name = f"SHIFT-PRODUCTION-CACHE-{frappe.generate_hash(length=8)}"
		cache_key = f"pea:shift_summary:{shift_name}"
		cache = frappe.cache()
		cache.set_value(cache_key, "stale-production-summary")

		try:
			on_submit_stock_entry(frappe._dict(custom_pea_shift=shift_name))

			self.assertIsNone(cache.get_value(cache_key))
		finally:
			cache.delete_value(cache_key)

	def test_submitted_rework_does_not_change_shift_summary_or_aggregate(self) -> None:
		shift = make_running_shift(bootstrap_manufacture_masters())
		self._insert_submitted_rework(shift.name)
		invalidate_shift_summary_cache(shift.name)

		summary = get_shift_summary(shift.name)

		self.assertEqual(summary["snapshot"]["entry_count"], 0)
		self.assertEqual(float(summary["snapshot"]["total_qty"]), 0)
		self.assertEqual(float(summary["snapshot"]["rejection_qty"]), 0)
		self.assertEqual(get_shift_aggregate_production_entries(shift.name), [])

	def test_submitted_rework_does_not_appear_in_workstation_timeline(self) -> None:
		shift = make_running_shift(bootstrap_manufacture_masters())
		workstation = f"Rework Metrics WS {frappe.generate_hash(length=6)}"
		ensure_workstation(workstation, standard_spm=2)
		self._insert_submitted_rework(shift.name, workstation=workstation)
		frappe.cache().delete_keys(get_timeline_cache_prefix("Workstation", workstation, shift.name))

		result = get_shift_timeline_data("Workstation", workstation)

		self.assertEqual(result["shift_name"], shift.name)
		self.assertEqual(result["entries"], [])

	def test_submitted_rework_does_not_produce_a_report_selection_row(self) -> None:
		shift = make_running_shift(bootstrap_manufacture_masters())
		rework_name = self._insert_submitted_rework(shift.name, operator="Report Operator")
		frappe.db.set_value("Shift", shift.name, "status", "Completed", update_modified=False)
		filters = build_stock_entry_filters(
			{"custom_pea_shift": shift.name},
			filter_keys=("custom_pea_shift",),
		)

		selected_names = [
			row["name"] for chunk in iter_stock_entries_in_chunks(filters, ["name"]) for row in chunk
		]

		self.assertNotIn(rework_name, selected_names)
		self.assertEqual(selected_names, [])

	def _insert_submitted_rework(
		self,
		shift_name: str,
		*,
		workstation: str | None = None,
		operator: str | None = None,
	) -> str:
		name = f"REWORK-METRICS-{frappe.generate_hash(length=10)}"
		frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"name": name,
				"docstatus": 1,
				"purpose": "Material Transfer",
				"stock_entry_type": self.rework_stock_entry_type,
				"custom_pea_shift": shift_name,
				"custom_pea_workstation": workstation,
				"custom_pea_operator": operator,
				"custom_pea_actual_start_date": "2026-09-01 09:00:00",
				"custom_pea_actual_end_date": "2026-09-01 10:00:00",
				"fg_completed_qty": 999,
				"custom_pea_rejection_qty": 99,
				"custom_pea_total_strokes": 999,
			}
		).db_insert()
		return name
