from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.report import report_utils


class TestReportUtilsPerformance(FrappeTestCase):
	def test_build_stock_entry_filters_handles_single_sided_dates_and_fg_item(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.report.report_utils.get_stock_entries_for_fg_item",
			return_value=["STE-001"],
		):
			from_filters = report_utils.build_stock_entry_filters(
				{"from_date": "2026-01-01", "fg_item": "FG-001", "custom_pea_operator": "OP-1"},
				("custom_pea_operator",),
			)
			to_filters = report_utils.build_stock_entry_filters({"to_date": "2026-01-31"}, ())

		self.assertEqual(from_filters["posting_date"], [">=", "2026-01-01"])
		self.assertEqual(from_filters["custom_pea_operator"], "OP-1")
		self.assertEqual(from_filters["name"], ["in", ["STE-001"]])
		self.assertEqual(to_filters["posting_date"], ["<=", "2026-01-31"])

	def test_new_interactive_report_timeout_guard_allows_within_budget(self) -> None:
		frappe.local.request = object()
		frappe.local.form_dict = frappe._dict(ignore_prepared_report=1)
		try:
			with patch(
				"production_entry_app.production_entry_app.report.report_utils.time.perf_counter",
				side_effect=[0.0, 4.9],
			):
				timeout_guard = report_utils.new_interactive_report_timeout_guard(
					"Production OEE Report",
					timeout_sec=5.0,
				)
				timeout_guard()
		finally:
			frappe.local.request = None
			frappe.local.form_dict = frappe._dict()

	def test_get_stock_entries_for_fg_item_throws_when_match_limit_exceeded(self) -> None:
		class _Query:
			def inner_join(self, *_args, **_kwargs):
				return self

			def on(self, *_args, **_kwargs):
				return self

			def select(self, *_args, **_kwargs):
				return self

			def distinct(self):
				return self

			def where(self, *_args, **_kwargs):
				return self

			def limit(self, *_args, **_kwargs):
				return self

			def run(self, **_kwargs):
				return [
					{"parent": f"STE-{index}"}
					for index in range(report_utils._MAX_FG_ITEM_PARENT_MATCHES + 1)
				]

		with patch(
			"production_entry_app.production_entry_app.report.report_utils.frappe.qb.from_",
			return_value=_Query(),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "FG Item filter matches more"):
				report_utils.get_stock_entries_for_fg_item("FG-001")

	def test_iter_stock_entries_in_chunks_throws_when_order_fields_are_missing(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "posting_date"):
			list(
				report_utils.iter_stock_entries_in_chunks(
					{"docstatus": 1},
					["name"],
					order_by="posting_date asc, name asc",
				)
			)

	def test_fetch_stock_entry_chunk_validates_last_row_keyset_fields(self) -> None:
		class _Query:
			def where(self, *_args, **_kwargs):
				return self

			def orderby(self, *_args, **_kwargs):
				return self

			def run(self, **_kwargs):
				return []

		with patch(
			"production_entry_app.production_entry_app.report.report_utils.frappe.qb.get_query",
			return_value=_Query(),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "Missing Stock Entry name"):
				report_utils._fetch_stock_entry_chunk(
					filters={"docstatus": 1},
					fields=["name"],
					order_by="name asc",
					chunk_size=10,
					last_row={"name": ""},
				)
			with self.assertRaisesRegex(frappe.ValidationError, "posting date or name"):
				report_utils._fetch_stock_entry_chunk(
					filters={"docstatus": 1},
					fields=["posting_date", "name"],
					order_by="posting_date asc, name asc",
					chunk_size=10,
					last_row={"posting_date": None, "name": "STE-001"},
				)

	def test_get_entry_qty_maps_includes_finished_item_map(self) -> None:
		class _Query:
			def select(self, *_args, **_kwargs):
				return self

			def where(self, *_args, **_kwargs):
				return self

			def groupby(self, *_args, **_kwargs):
				return self

			def run(self, **_kwargs):
				return [
					{"parent": "STE-001", "item_code": "FG-001", "qty": 10},
					{"parent": "", "item_code": "FG-SKIP", "qty": 1},
				]

		with patch(
			"production_entry_app.production_entry_app.report.report_utils.get_parent_quantity_metrics",
			return_value={"STE-001": {"good_qty": 8, "rejection_qty": 2}},
		):
			with patch(
				"production_entry_app.production_entry_app.report.report_utils.frappe.qb.from_",
				return_value=_Query(),
			):
				good_qty_map, rejection_qty_map, fg_item_map = report_utils.get_entry_qty_maps(
					["STE-001"],
					include_fg_item=True,
				)

		self.assertEqual(good_qty_map, {"STE-001": 8.0})
		self.assertEqual(rejection_qty_map, {"STE-001": 2.0})
		self.assertEqual(fg_item_map, {"STE-001": "FG-001"})

	def test_get_loss_time_maps_splits_setup_and_non_setup_minutes(self) -> None:
		rows = [
			{
				"parent": "STE-001",
				"downtime_reason": "Setup Time",
				"start_time": "2026-01-01 08:00:00",
				"end_time": "2026-01-01 08:15:00",
			},
			{
				"parent": "STE-001",
				"downtime_reason": "Tea Break",
				"start_time": "2026-01-01 09:00:00",
				"end_time": "2026-01-01 09:30:00",
			},
			{
				"parent": "",
				"downtime_reason": "Tea Break",
				"start_time": "2026-01-01 10:00:00",
				"end_time": "2026-01-01 10:15:00",
			},
		]
		with patch(
			"production_entry_app.production_entry_app.report.report_utils.frappe.get_all", return_value=rows
		):
			setup_map, loss_map = report_utils.get_loss_time_maps(["STE-001"])

		self.assertEqual(setup_map, {"STE-001": 15.0})
		self.assertEqual(loss_map, {"STE-001": 30.0})

	def test_entry_duration_and_stroke_helpers_cover_fallbacks(self) -> None:
		total_strokes, rejection_qty = report_utils.get_entry_total_strokes(
			{"name": "STE-001", "fg_completed_qty": 0, "custom_pea_rejection_qty": 9},
			good_qty_map={"STE-001": 11},
			rejection_qty_map={"STE-001": 3},
			total_rejected_qty_map={"STE-001": 4},
		)

		self.assertEqual(total_strokes, 15.0)
		self.assertEqual(rejection_qty, 3.0)
		self.assertEqual(
			report_utils.get_entry_production_minutes(
				{"custom_pea_actual_duration_mins": 90},
				setup_mins=20,
				loss_mins=10,
			),
			60.0,
		)
		self.assertEqual(
			report_utils.get_entry_production_minutes({"custom_pea_production_time_mins": -10}),
			0.0,
		)

	def test_precision_and_efficiency_helpers_cover_cached_and_zero_duration_paths(self) -> None:
		if hasattr(frappe.local, "_pea_report_float_precision"):
			delattr(frappe.local, "_pea_report_float_precision")

		with patch(
			"production_entry_app.production_entry_app.report.report_utils.get_system_float_precision",
			return_value=4,
		) as get_precision:
			columns = report_utils.apply_system_precision(
				[
					{"fieldname": "qty", "fieldtype": "Float"},
					{"fieldname": "label", "fieldtype": "Data"},
				]
			)
			self.assertEqual(report_utils.get_report_float_precision(), 4)

		self.assertEqual(columns[0]["precision"], 4)
		self.assertNotIn("precision", columns[1])
		get_precision.assert_called_once()

		aggregates = report_utils.aggregate_efficiency_by_field(
			[
				{
					"custom_pea_operator": "",
					"_good_qty": 5,
					"_rejection_qty": 1,
					"_rework_qty": 2,
					"_duration_mins": 0,
					"custom_pea_standard_spm": 2,
					"custom_pea_actual_spm": 3,
				}
			],
			"custom_pea_operator",
		)
		rows = report_utils.build_efficiency_rows(aggregates, "operator", "efficiency_pct")

		self.assertEqual(rows[0]["operator"], "Unassigned")
		self.assertEqual(rows[0]["actual_spm"], 3.0)
		self.assertEqual(rows[0]["efficiency_pct"], 150.0)

	def test_iter_stock_entries_in_chunks_pages_by_name_keyset(self) -> None:
		responses = [
			[{"name": "STE-1"}, {"name": "STE-2"}],
			[{"name": "STE-3"}],
		]
		with patch(
			"production_entry_app.production_entry_app.report.report_utils._fetch_stock_entry_chunk",
			side_effect=responses,
		) as fetch_chunk:
			chunks = list(
				report_utils.iter_stock_entries_in_chunks(
					{"docstatus": 1},
					["name"],
					chunk_size=2,
				)
			)

		self.assertEqual(chunks, [[{"name": "STE-1"}, {"name": "STE-2"}], [{"name": "STE-3"}]])
		self.assertEqual(fetch_chunk.call_count, 2)
		first_call = fetch_chunk.call_args_list[0].kwargs
		self.assertEqual(first_call["order_by"], "name asc")
		self.assertEqual(first_call["chunk_size"], 2)
		self.assertIsNone(first_call["last_row"])
		second_call = fetch_chunk.call_args_list[1].kwargs
		self.assertEqual(second_call["last_row"], {"name": "STE-2"})

	def test_iter_stock_entries_in_chunks_pages_by_posting_date_and_name_keyset(self) -> None:
		responses = [
			[
				{"name": "STE-1", "posting_date": "2026-01-01"},
				{"name": "STE-2", "posting_date": "2026-01-01"},
			],
			[
				{"name": "STE-3", "posting_date": "2026-01-02"},
			],
		]
		with patch(
			"production_entry_app.production_entry_app.report.report_utils._fetch_stock_entry_chunk",
			side_effect=responses,
		) as fetch_chunk:
			chunks = list(
				report_utils.iter_stock_entries_in_chunks(
					{"docstatus": 1},
					["name", "posting_date"],
					order_by="posting_date asc, name asc",
					chunk_size=2,
				)
			)

		self.assertEqual(
			chunks,
			[
				[
					{"name": "STE-1", "posting_date": "2026-01-01"},
					{"name": "STE-2", "posting_date": "2026-01-01"},
				],
				[
					{"name": "STE-3", "posting_date": "2026-01-02"},
				],
			],
		)
		second_call = fetch_chunk.call_args_list[1].kwargs
		self.assertEqual(
			second_call["last_row"],
			{"name": "STE-2", "posting_date": "2026-01-01"},
		)

	def test_iter_stock_entries_in_chunks_throws_for_unsupported_order_by(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			list(
				report_utils.iter_stock_entries_in_chunks(
					{"docstatus": 1},
					["name"],
					order_by="creation asc",
				)
			)

	def test_iter_stock_entries_in_chunks_throws_when_max_rows_exceeded(self) -> None:
		responses = [
			[{"name": "STE-1"}, {"name": "STE-2"}],
			[{"name": "STE-3"}],
		]
		with patch(
			"production_entry_app.production_entry_app.report.report_utils._fetch_stock_entry_chunk",
			side_effect=responses,
		):
			with self.assertRaises(frappe.ValidationError):
				list(
					report_utils.iter_stock_entries_in_chunks(
						{"docstatus": 1},
						["name"],
						chunk_size=2,
						max_rows=2,
					)
				)

	def test_new_interactive_report_timeout_guard_throws_after_budget(self) -> None:
		frappe.local.request = object()
		frappe.local.form_dict = frappe._dict(ignore_prepared_report=1)
		with patch(
			"production_entry_app.production_entry_app.report.report_utils.time.perf_counter",
			side_effect=[0.0, 6.1],
		):
			timeout_guard = report_utils.new_interactive_report_timeout_guard(
				"Operator Efficiency Report",
				timeout_sec=5.0,
			)
			with self.assertRaisesRegex(frappe.ValidationError, "Operator Efficiency Report"):
				timeout_guard()
		frappe.local.request = None
		frappe.local.form_dict = frappe._dict()

	def test_new_interactive_report_timeout_guard_allows_zero_budget_override(self) -> None:
		frappe.local.request = object()
		frappe.local.form_dict = frappe._dict(ignore_prepared_report=1)
		with patch(
			"production_entry_app.production_entry_app.report.report_utils.time.perf_counter",
			side_effect=[0.0, 100.0],
		):
			timeout_guard = report_utils.new_interactive_report_timeout_guard(
				"Production OEE Report",
				timeout_sec=0,
			)
			timeout_guard()
		frappe.local.request = None
		frappe.local.form_dict = frappe._dict()

	def test_new_interactive_report_timeout_guard_is_noop_for_prepared_reports(self) -> None:
		frappe.local.request = None
		frappe.local.form_dict = frappe._dict()
		with patch(
			"production_entry_app.production_entry_app.report.report_utils.time.perf_counter",
			side_effect=[0.0, 100.0],
		):
			timeout_guard = report_utils.new_interactive_report_timeout_guard(
				"Production OEE Report",
				timeout_sec=5.0,
			)
			timeout_guard()
