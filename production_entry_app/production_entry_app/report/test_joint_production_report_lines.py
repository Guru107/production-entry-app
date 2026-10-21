from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.doctype.shift import shift as shift_module
from production_entry_app.production_entry_app.joint_production import (
	JOINT_PRODUCTION_LINES_FIELD,
	joint_production_line_side,
)
from production_entry_app.production_entry_app.report.report_utils import (
	_LH_RH_OUTPUT_SLOTS,
	_materialize_joint_production_line_slot_fields,
	attach_joint_production_lines_to_entries,
	get_entry_output_quantities,
	get_entry_total_strokes,
	get_item_bom_quality_facts,
	get_stock_entries_for_bom,
	paired_output_slots,
)


class TestJointProductionReportLines(FrappeTestCase):
	def _three_line_joint_entry(self) -> frappe._dict:
		lines = [
			{"bom_no": "BOM-LINE-1", "gross_qty": 10, "rejection_qty": 1},
			{"bom_no": "BOM-LINE-2", "gross_qty": 20, "rejection_qty": 2},
			{"bom_no": "BOM-LINE-3", "gross_qty": 30, "rejection_qty": 0},
		]
		entry = frappe._dict(
			name="STE-JOINT-3",
			purpose="Repack",
			custom_pea_joint_production=1,
			custom_pea_joint_lh_rh_production=0,
			custom_pea_total_strokes=99,
			custom_pea_production_time_mins=45,
		)
		entry[JOINT_PRODUCTION_LINES_FIELD] = lines
		_materialize_joint_production_line_slot_fields(entry)
		return entry

	def test_paired_output_slots_returns_one_slot_per_joint_production_line(self) -> None:
		entry = self._three_line_joint_entry()
		slots = paired_output_slots(entry)
		self.assertEqual(len(slots), 3)
		self.assertEqual(
			[slot.side for slot in slots],
			[joint_production_line_side(index) for index in range(3)],
		)
		self.assertEqual(
			(entry.get(slots[2].gross_field), entry.get(slots[2].rejection_field)),
			(30, 0),
		)

	def test_entry_output_quantities_sum_all_line_gross_and_rejections(self) -> None:
		entry = self._three_line_joint_entry()
		quantities = get_entry_output_quantities(entry)
		self.assertEqual(quantities.total_qty, 60)
		self.assertEqual(quantities.rejection_qty, 3)
		self.assertEqual(quantities.ok_qty, 57)

	def test_entry_strokes_count_once_for_three_line_joint_production(self) -> None:
		entry = self._three_line_joint_entry()
		strokes, rejection_qty = get_entry_total_strokes(entry, rejection_qty_map={"STE-JOINT-3": 3})
		self.assertEqual(strokes, 99)
		self.assertEqual(rejection_qty, 3)

	def test_item_bom_quality_facts_emit_one_row_per_line(self) -> None:
		entry = self._three_line_joint_entry()
		with (
			patch(
				"production_entry_app.production_entry_app.report.report_utils.get_parent_quantity_metrics",
				return_value={},
			),
			patch(
				"production_entry_app.production_entry_app.report.report_utils.get_finished_item_maps",
				return_value=({}, {}),
			),
			patch(
				"production_entry_app.production_entry_app.report.report_utils.get_parent_breakup_reason_rows",
				return_value=[],
			),
			patch(
				"production_entry_app.production_entry_app.report.report_utils._get_joint_output_item_map",
				return_value={
					("STE-JOINT-3", joint_production_line_side(0)): "FG-A",
					("STE-JOINT-3", joint_production_line_side(1)): "FG-B",
					("STE-JOINT-3", joint_production_line_side(2)): "FG-C",
				},
			),
		):
			facts = get_item_bom_quality_facts([entry], is_rework=False)

		self.assertEqual(len(facts), 3)
		self.assertEqual(
			[(fact["bom_no"], fact["item_code"], fact["total_qty"]) for fact in facts],
			[
				("BOM-LINE-1", "FG-A", 10),
				("BOM-LINE-2", "FG-B", 20),
				("BOM-LINE-3", "FG-C", 30),
			],
		)

	def test_shift_item_bom_rows_use_each_line_finished_item(self) -> None:
		entry = self._three_line_joint_entry()
		with patch.object(
			shift_module.frappe,
			"get_list",
			return_value=[
				{"name": "BOM-LINE-1", "item": "FG-A"},
				{"name": "BOM-LINE-2", "item": "FG-B"},
				{"name": "BOM-LINE-3", "item": "FG-C"},
			],
		):
			rows = shift_module._build_item_bom_rows([entry])

		labels = {row["label"] for row in rows}
		self.assertEqual(
			labels,
			{"FG-A / BOM-LINE-1", "FG-B / BOM-LINE-2", "FG-C / BOM-LINE-3"},
		)

	def test_attach_joint_production_lines_batches_child_rows_for_a_chunk(self) -> None:
		entries = [
			frappe._dict(name="STE-1", custom_pea_joint_production=1),
			frappe._dict(name="STE-2", custom_pea_joint_production=1),
			frappe._dict(name="STE-3", purpose="Manufacture"),
		]
		child_rows = [
			{"parent": "STE-1", "bom_no": "BOM-A", "gross_qty": 1, "rejection_qty": 0, "idx": 1},
			{"parent": "STE-2", "bom_no": "BOM-B", "gross_qty": 2, "rejection_qty": 0, "idx": 1},
			{"parent": "STE-2", "bom_no": "BOM-C", "gross_qty": 3, "rejection_qty": 0, "idx": 2},
		]
		with patch("production_entry_app.production_entry_app.report.report_utils.frappe.qb.from_") as from_:
			query = from_.return_value.select.return_value.where.return_value.orderby
			query.return_value.run.return_value = child_rows
			attach_joint_production_lines_to_entries(entries)

		from_.assert_called_once()
		self.assertEqual(len(entries[0][JOINT_PRODUCTION_LINES_FIELD]), 1)
		self.assertEqual(len(entries[1][JOINT_PRODUCTION_LINES_FIELD]), 2)
		self.assertNotIn(JOINT_PRODUCTION_LINES_FIELD, entries[2])

	def test_same_item_joint_aggregate_attributes_full_strokes_to_each_line_bom(self) -> None:
		entry = self._three_line_joint_entry()
		aggregates: dict[str, dict[str, float | str]] = {}
		item_by_bom = {
			"BOM-LINE-1": "FG-A",
			"BOM-LINE-2": "FG-B",
			"BOM-LINE-3": "FG-C",
		}
		shift_module._add_same_item_joint_aggregate(aggregates, entry, item_by_bom)
		self.assertEqual(set(aggregates), {"BOM-LINE-1", "BOM-LINE-2", "BOM-LINE-3"})
		for bom_no in item_by_bom:
			aggregate = aggregates[bom_no]
			self.assertEqual(aggregate["total_strokes"], 99)
			self.assertEqual(aggregate["mins"], 45)

	def test_joint_lh_rh_output_slots_remain_static(self) -> None:
		entry = frappe._dict(
			purpose="Repack",
			custom_pea_joint_production=0,
			custom_pea_joint_lh_rh_production=1,
		)
		self.assertEqual(paired_output_slots(entry), _LH_RH_OUTPUT_SLOTS)

	def test_paired_output_slots_returns_none_for_joint_without_lines(self) -> None:
		entry = frappe._dict(
			purpose="Repack",
			stock_entry_type="Joint Production",
			custom_pea_joint_production=1,
			custom_pea_joint_lh_rh_production=0,
		)
		self.assertIsNone(paired_output_slots(entry))

	def test_entry_output_quantities_reads_joint_lines_without_materialized_slots(self) -> None:
		entry = frappe._dict(
			purpose="Repack",
			stock_entry_type="Joint Production",
			custom_pea_joint_production=1,
			custom_pea_joint_lh_rh_production=0,
			custom_pea_joint_production_lines=[
				{"bom_no": "BOM-1", "gross_qty": 10, "rejection_qty": 1},
				{"bom_no": "BOM-2", "gross_qty": 20, "rejection_qty": 2},
			],
		)
		quantities = get_entry_output_quantities(entry)
		self.assertEqual(quantities.total_qty, 30)
		self.assertEqual(quantities.rejection_qty, 3)
		self.assertEqual(quantities.ok_qty, 27)

	def test_get_stock_entries_for_bom_includes_joint_production_line_bom(self) -> None:
		run_results = [[{"parent": "STE-LINE"}], []]

		def _query_builder() -> MagicMock:
			query = MagicMock()
			for name in ("select", "distinct", "where", "limit", "inner_join", "on"):
				setattr(query, name, MagicMock(return_value=query))
			query.run.side_effect = lambda **_: run_results.pop(0) if run_results else []
			return query

		def _report_rows(
			_doctype: str, *, filters: dict | None = None, or_filters=None, **_: object
		) -> list[dict]:
			if or_filters:
				return [{"name": "STE-HEADER"}]
			names = (filters or {}).get("name", ["", []])[1]
			return [{"name": name} for name in names]

		with (
			patch(
				"production_entry_app.production_entry_app.report.report_utils.get_report_rows",
				side_effect=_report_rows,
			),
			patch(
				"production_entry_app.production_entry_app.report.report_utils.frappe.qb.from_",
				side_effect=lambda _table: _query_builder(),
			),
		):
			names = get_stock_entries_for_bom("BOM-LINE-3", filters={"docstatus": 1})

		self.assertEqual(set(names), {"STE-HEADER", "STE-LINE"})
