from __future__ import annotations

import json
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.desk.query_report import run as run_query_report
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from production_entry_app.production_entry_app.overrides.test_stock_entry_hooks import (
	_append_rejection_breakup_rows,
	_create_manufacture_stock_entry,
	_ensure_item_die_tool_fields,
	_ensure_rejection_breakup_custom_field,
	_ensure_rejection_breakup_doctype,
	_ensure_rejection_reason_doctype,
	_ensure_rejection_reasons,
	_ensure_stock_entry_metric_fields,
	_get_or_create_item,
	_get_or_create_warehouse,
	_set_shift_buffers,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	get_company_abbr,
	resolve_test_company,
	save_test_user,
)


class TestProductionReports(FrappeTestCase):
	def test_report_access_metadata_is_source_controlled_not_runtime_synced(self) -> None:
		"""Report JSON should be the source of truth for report roles."""
		report_root = Path(__file__).parent
		for report_path in report_root.glob("*/*.json"):
			with self.subTest(report=report_path.parent.name):
				report_schema = json.loads(report_path.read_text())
				self.assertEqual(report_schema["ref_doctype"], "Shift")
				self.assertEqual(
					[role["role"] for role in report_schema.get("roles", [])],
					[
						"System Manager",
						"PEA User",
						"PEA Read Only",
					],
				)

	def test_report_metadata_keeps_prepared_report_source_value(self) -> None:
		report_root = Path(__file__).parent
		for report_path in report_root.glob("*/*.json"):
			with self.subTest(report=report_path.parent.name):
				report_schema = json.loads(report_path.read_text())
				self.assertEqual(report_schema["prepared_report"], 0)

	def _assert_column_precision(
		self, columns: list[dict], fieldnames: tuple[str, ...], expected_precision: int
	) -> None:
		columns_by_field = {column["fieldname"]: column for column in columns}
		for fieldname in fieldnames:
			self.assertEqual(columns_by_field[fieldname]["precision"], expected_precision)

	@classmethod
	def _ensure_base_fixtures(cls) -> None:
		if not frappe.get_meta("Loss Entry", cached=True).has_field("shift"):
			frappe.reload_doc("production_entry_app", "doctype", "loss_entry")
			frappe.clear_cache(doctype="Loss Entry")
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()
		_ensure_stock_entry_metric_fields()
		_ensure_item_die_tool_fields()
		for reason in (
			"Setup Time",
			"Trial",
			"Mtrl Handl",
			"No Operator",
			"No Mtrl",
			"Maint",
			"P. Maint",
			"Tool Break",
			"Other",
			"No Helper",
			"Power Off",
			"Tea Break",
			"Lunch Break",
		):
			if not frappe.db.exists("Downtime Reason", reason):
				frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": reason}).insert(
					ignore_permissions=True
				)

		cls.company = resolve_test_company()
		abbr = get_company_abbr(cls.company)
		cls.wip_warehouse = _get_or_create_warehouse(f"WIP Report - {abbr}", cls.company)
		cls.rm_warehouse = _get_or_create_warehouse(f"RM Report - {abbr}", cls.company)
		cls.fg_warehouse = _get_or_create_warehouse(f"FG Report - {abbr}", cls.company)
		cls.rejection_warehouse = _get_or_create_warehouse(f"RJ Report - {abbr}", cls.company)
		if frappe.get_meta("Warehouse", cached=True).has_field("is_rejected_warehouse"):
			frappe.db.set_value(
				"Warehouse", cls.rejection_warehouse, "is_rejected_warehouse", 1, update_modified=False
			)

		cls.fg_item = _get_or_create_item("_Test FG Item For Reports")
		cls.rm_item = _get_or_create_item("_Test RM Item For Reports")

		if not frappe.db.exists("Operator", "Report Operator"):
			frappe.get_doc(
				{"doctype": "Operator", "operator_name": "Report Operator", "is_active": 1}
			).insert(ignore_permissions=True)

		if not frappe.db.exists("Workstation", "Report Workstation"):
			frappe.get_doc(
				{
					"doctype": "Workstation",
					"workstation_name": "Report Workstation",
					"production_capacity": 1,
					"hour_rate": 100,
					"custom_pea_standard_spm": 2,
				}
			).insert(ignore_permissions=True)

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		if not frappe.db.exists("DocType", "Die Tool Counter"):
			frappe.reload_doc("production_entry_app", "doctype", "die_tool_counter")
		if not frappe.db.exists("DocType", "Die Tool Maintenance Log"):
			frappe.reload_doc("production_entry_app", "doctype", "die_tool_maintenance_log")
		cls._ensure_base_fixtures()

	def tearDown(self) -> None:
		frappe.db.rollback()

	def setUp(self) -> None:
		self._ensure_base_fixtures()
		frappe.db.set_value("Workstation", "Report Workstation", "custom_pea_standard_spm", 2)
		_set_shift_buffers(start_mins=60, end_mins=60)

	def test_pea_read_only_can_run_pea_report_through_query_report_runner(self) -> None:
		user_email = f"test_pea_report_read_only_{frappe.generate_hash(length=8)}@example.com"
		_ensure_user_with_exact_roles(user_email, ("PEA Read Only",))
		frappe.reload_doc("production_entry_app", "doctype", "shift")
		frappe.clear_cache(doctype="Shift")
		report_root = Path(__file__).parent
		report_names = []
		for report_path in sorted(report_root.glob("*/*.json")):
			report_schema = json.loads(report_path.read_text())
			report_names.append(report_schema["name"])
			frappe.reload_doc("production_entry_app", "report", report_path.parent.name)

		original_user = frappe.session.user
		try:
			frappe.set_user(user_email)
			for report_name in report_names:
				with self.subTest(report=report_name):
					result = run_query_report(
						report_name,
						filters=self._get_pea_read_only_report_filters(report_name),
						ignore_prepared_report=True,
					)
					self.assertIn("columns", result)
					self.assertIn("result", result)
		finally:
			frappe.set_user(original_user)

	def _get_pea_read_only_report_filters(self, report_name: str) -> dict:
		if report_name == "Daily Strokes SPM Monitor":
			fiscal_year = self._ensure_fiscal_year("2090-2091", "2090-04-01", "2091-03-31")
			return {"fiscal_year": fiscal_year, "month": "April"}
		return {}

	def test_manufacturing_user_cannot_run_pea_report_through_query_report_runner(self) -> None:
		user_email = f"test_pea_report_mfg_{frappe.generate_hash(length=8)}@example.com"
		_ensure_user_with_exact_roles(user_email, ("Manufacturing User",))
		frappe.reload_doc("production_entry_app", "doctype", "shift")
		frappe.reload_doc("production_entry_app", "report", "rejection_pareto_report")
		frappe.clear_cache(doctype="Shift")
		original_user = frappe.session.user
		try:
			frappe.set_user(user_email)
			with self.assertRaises(frappe.PermissionError):
				run_query_report(
					"Rejection Pareto Report",
					filters={},
					ignore_prepared_report=True,
				)
		finally:
			frappe.set_user(original_user)

	def test_production_oee_report_columns_match_v2_schema(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		columns, _rows = execute({})
		fieldnames = [column.get("fieldname") for column in columns]
		self.assertEqual(
			fieldnames,
			[
				"day",
				"workstation",
				"stroke_required",
				"first_shift_strokes",
				"second_shift_strokes",
				"total_strokes",
				"rejection",
				"std_spm",
				"act_spm",
				"productivity_pct",
				"quality_pct",
				"availability_pct",
				"oee",
				"oee_mult_pct",
				"avl_time_hrs",
				"setup_1st",
				"setup_2nd",
				"trial_1st",
				"trial_2nd",
				"mtrl_handl_1st",
				"mtrl_handl_2nd",
				"no_operator_1st",
				"no_operator_2nd",
				"no_mtrl_1st",
				"no_mtrl_2nd",
				"maint_1st",
				"maint_2nd",
				"p_maint_1st",
				"p_maint_2nd",
				"tool_break_1st",
				"tool_break_2nd",
				"other_1st",
				"other_2nd",
				"no_helper_1st",
				"no_helper_2nd",
				"power_off_1st",
				"power_off_2nd",
				"total_loss_time",
				"running_time",
			],
		)

	def test_report_metric_columns_follow_system_precision(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			_get_columns as get_daily_columns,
		)
		from production_entry_app.production_entry_app.report.die_tool_stroke_and_maintenance_report.die_tool_stroke_and_maintenance_report import (
			_get_columns as get_die_tool_columns,
		)
		from production_entry_app.production_entry_app.report.item_bom_rejection_hotspots.item_bom_rejection_hotspots import (
			_get_columns as get_rejection_hotspot_columns,
		)
		from production_entry_app.production_entry_app.report.item_bom_rework_hotspots.item_bom_rework_hotspots import (
			_get_columns as get_rework_hotspot_columns,
		)
		from production_entry_app.production_entry_app.report.operator_daily_spm_report.operator_daily_spm_report import (
			_get_columns as get_operator_daily_columns,
		)
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			_get_columns as get_operator_efficiency_columns,
		)
		from production_entry_app.production_entry_app.report.operator_rejection_performance.operator_rejection_performance import (
			_get_columns as get_operator_rejection_columns,
		)
		from production_entry_app.production_entry_app.report.operator_rework_performance.operator_rework_performance import (
			_get_columns as get_operator_rework_columns,
		)
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			_get_columns as get_oee_columns,
		)
		from production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report import (
			_get_columns as get_rejection_ppm_columns,
		)
		from production_entry_app.production_entry_app.report.rejection_trend_report.rejection_trend_report import (
			_get_columns as get_rejection_trend_columns,
		)
		from production_entry_app.production_entry_app.report.rework_ppm_report.rework_ppm_report import (
			_get_columns as get_rework_ppm_columns,
		)
		from production_entry_app.production_entry_app.report.rework_trend_report.rework_trend_report import (
			_get_columns as get_rework_trend_columns,
		)
		from production_entry_app.production_entry_app.report.workstation_efficiency_report.workstation_efficiency_report import (
			_get_columns as get_workstation_efficiency_columns,
		)
		from production_entry_app.production_entry_app.report.workstation_rejection_reason_matrix.workstation_rejection_reason_matrix import (
			_get_columns as get_workstation_rejection_matrix_columns,
		)
		from production_entry_app.production_entry_app.report.workstation_rework_reason_matrix.workstation_rework_reason_matrix import (
			_get_columns as get_workstation_rework_matrix_columns,
		)

		with ExitStack() as stack:
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.report.report_utils.get_report_float_precision",
					return_value=4,
				)
			)

			self._assert_column_precision(
				get_oee_columns(),
				("act_spm", "oee_mult_pct", "running_time"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_operator_efficiency_columns(),
				("good_qty", "actual_spm", "operator_efficiency_pct"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_workstation_efficiency_columns(),
				("good_qty", "actual_spm", "workstation_efficiency_pct"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_daily_columns({"fiscal_year": "2090-2091", "month": "April"}),
				("setup_time_hrs", "spm", "rejection"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_operator_daily_columns(),
				("working_hours", "production_time_hrs", "spm"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_rejection_hotspot_columns(),
				("total_qty", "rejection_rate_pct"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_rework_hotspot_columns(),
				("total_qty", "rework_rate_pct"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_rejection_ppm_columns(),
				("total_qty", "ppm"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_rework_ppm_columns(),
				("total_qty", "ppm"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_rejection_trend_columns(),
				("total_qty", "ok_qty", "rejection_rate_pct"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_rework_trend_columns(),
				("total_qty", "non_rework_rejection_qty", "rework_rate_pct"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_operator_rejection_columns(),
				("total_qty", "avg_actual_spm", "rejection_rate_pct"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_operator_rework_columns(),
				("total_qty", "avg_actual_spm", "rework_rate_pct"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_die_tool_columns(),
				("current_stroke_count", "utilization_pct", "warning_threshold_pct"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_workstation_rejection_matrix_columns(["Crack"]),
				("total_rejection_qty", "reason_crack"),
				expected_precision=4,
			)
			self._assert_column_precision(
				get_workstation_rework_matrix_columns(["Crack"]),
				("total_rework_qty", "reason_crack"),
				expected_precision=4,
			)

	def test_production_oee_report_metrics(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-01", "1", clear_planned_losses=True)
		stock_entry = self._create_mock_submitted_entry(
			posting_date="2026-06-01",
			planned_start="2026-06-01 08:00:00",
			planned_end="2026-06-01 09:00:00",
			actual_start="2026-06-01 08:00:00",
			actual_end="2026-06-01 09:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift.name,
		)
		self.assertEqual(stock_entry.docstatus, 1)

		_, rows = execute({"from_date": "2026-06-01", "to_date": "2026-06-01"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(str(rows[0]["day"]), "2026-06-01")
		self.assertEqual(float(rows[0]["availability_pct"]), 100.0)
		self.assertEqual(float(rows[0]["productivity_pct"]), 12.5)
		self.assertEqual(float(rows[0]["quality_pct"]), 100.0)
		self.assertEqual(float(rows[0]["oee_mult_pct"]), 12.5)
		self.assertEqual(float(rows[0]["first_shift_strokes"]), 120.0)
		self.assertEqual(float(rows[0]["second_shift_strokes"]), 0.0)
		self.assertEqual(float(rows[0]["running_time"]), 8.0)
		self.assertEqual(float(rows[0]["avl_time_hrs"]), 8.0)

	def test_production_oee_report_aggregates_by_day_and_workstation(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-01", "1", clear_planned_losses=True)
		self._create_mock_submitted_entry(
			posting_date="2026-06-01",
			planned_start="2026-06-01 08:00:00",
			planned_end="2026-06-01 08:30:00",
			actual_start="2026-06-01 08:00:00",
			actual_end="2026-06-01 08:30:00",
			fg_qty=60,
			rejection_qty=5,
			shift_name=shift.name,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-06-01",
			planned_start="2026-06-01 09:00:00",
			planned_end="2026-06-01 10:00:00",
			actual_start="2026-06-01 09:00:00",
			actual_end="2026-06-01 10:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift.name,
		)
		_, rows = execute({"from_date": "2026-06-01", "to_date": "2026-06-01"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["total_strokes"]), 180.0)
		self.assertEqual(float(rows[0]["rejection"]), 5.0)
		self.assertEqual(float(rows[0]["first_shift_strokes"]), 180.0)

	def test_production_oee_report_shift_split_and_loss_bucket_mapping(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift_1 = self._create_shift_for_label("2026-06-02", "1", clear_planned_losses=True)
		shift_2 = self._create_shift_for_label("2026-06-02", "2", clear_planned_losses=True)
		self._create_mock_submitted_entry(
			posting_date="2026-06-02",
			planned_start="2026-06-02 08:00:00",
			planned_end="2026-06-02 10:30:00",
			actual_start="2026-06-02 08:00:00",
			actual_end="2026-06-02 10:30:00",
			fg_qty=100,
			rejection_qty=0,
			shift_name=shift_1.name,
			unplanned_losses=[
				{"downtime_reason": "Setup Time", "start_time": "10:00:00", "end_time": "10:30:00"}
			],
		)
		self._create_mock_submitted_entry(
			posting_date="2026-06-02",
			planned_start="2026-06-02 16:00:00",
			planned_end="2026-06-02 19:00:00",
			actual_start="2026-06-02 16:00:00",
			actual_end="2026-06-02 19:00:00",
			fg_qty=80,
			rejection_qty=10,
			shift_name=shift_2.name,
			unplanned_losses=[
				{"downtime_reason": "P. Maint", "start_time": "18:00:00", "end_time": "19:00:00"}
			],
		)
		_, rows = execute({"from_date": "2026-06-02", "to_date": "2026-06-02"})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(float(row["first_shift_strokes"]), 100.0)
		self.assertEqual(float(row["second_shift_strokes"]), 80.0)
		self.assertEqual(float(row["setup_1st"]), 0.5)
		self.assertEqual(float(row["p_maint_2nd"]), 1.0)
		self.assertEqual(float(row["total_loss_time"]), 1.5)
		self.assertEqual(float(row["avl_time_hrs"]), 16.0)
		self.assertEqual(float(row["running_time"]), 14.5)

	def test_production_oee_report_counts_cross_midnight_loss_for_second_shift(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift_2 = self._create_shift_for_label("2026-06-09", "2", clear_planned_losses=True)
		self._create_mock_submitted_entry(
			posting_date="2026-06-09",
			planned_start="2026-06-09 16:00:00",
			planned_end="2026-06-10 00:30:00",
			actual_start="2026-06-09 16:00:00",
			actual_end="2026-06-10 00:30:00",
			fg_qty=100,
			rejection_qty=0,
			shift_name=shift_2.name,
			unplanned_losses=[{"downtime_reason": "Other", "start_time": "23:30:00", "end_time": "00:30:00"}],
		)

		_, rows = execute({"from_date": "2026-06-09", "to_date": "2026-06-09"})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(float(row["other_2nd"]), 1.0)
		self.assertEqual(float(row["total_loss_time"]), 1.0)

	def test_production_oee_report_ignores_unmapped_loss_reasons(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-07", "1", clear_planned_losses=True)
		if not frappe.db.exists("Downtime Reason", "Excessive machine set up time"):
			frappe.get_doc(
				{
					"doctype": "Downtime Reason",
					"downtime_reason_name": "Excessive machine set up time",
				}
			).insert(ignore_permissions=True)
		self._create_mock_submitted_entry(
			posting_date="2026-06-07",
			planned_start="2026-06-07 08:00:00",
			planned_end="2026-06-07 10:30:00",
			actual_start="2026-06-07 08:00:00",
			actual_end="2026-06-07 10:30:00",
			fg_qty=100,
			rejection_qty=0,
			shift_name=shift.name,
			unplanned_losses=[
				{
					"downtime_reason": "Excessive machine set up time",
					"start_time": "10:00:00",
					"end_time": "10:30:00",
				}
			],
		)

		_, rows = execute({"from_date": "2026-06-07", "to_date": "2026-06-07"})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(float(row["setup_1st"]), 0.0)
		self.assertEqual(float(row["trial_1st"]), 0.0)
		self.assertEqual(float(row["other_1st"]), 0.0)
		self.assertEqual(float(row["total_loss_time"]), 0.0)

	def test_production_oee_report_does_not_use_downtime_entry_for_losses(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-08", "1", clear_planned_losses=True)
		self._create_mock_submitted_entry(
			posting_date="2026-06-08",
			planned_start="2026-06-08 08:00:00",
			planned_end="2026-06-08 09:00:00",
			actual_start="2026-06-08 08:00:00",
			actual_end="2026-06-08 09:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift.name,
		)
		self._create_downtime_entry(
			workstation="Report Workstation",
			from_time="2026-06-08 12:00:00",
			to_time="2026-06-08 13:00:00",
			shift_name=shift.name,
			stop_reason="Other",
		)

		_, rows = execute({"from_date": "2026-06-08", "to_date": "2026-06-08"})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(float(row["other_1st"]), 0.0)
		self.assertEqual(float(row["total_loss_time"]), 0.0)

	def test_production_oee_report_availability_uses_shift_duration_hours(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-03", "1", clear_planned_losses=True)
		self._create_shift_for_label("2026-06-03", "2", clear_planned_losses=True)
		# Shift-2 is intentionally left without linked stock entries for this workstation group,
		# so availability must include only linked shift hours (Shift-1 => 8h).
		self._create_mock_submitted_entry(
			posting_date="2026-06-03",
			planned_start="2026-06-03 08:00:00",
			planned_end="2026-06-03 14:00:00",
			actual_start="2026-06-03 08:00:00",
			actual_end="2026-06-03 14:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift.name,
			unplanned_losses=[{"downtime_reason": "Other", "start_time": "12:00:00", "end_time": "14:00:00"}],
		)

		_, rows = execute({"from_date": "2026-06-03", "to_date": "2026-06-03"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["avl_time_hrs"]), 8.0)
		self.assertEqual(float(rows[0]["running_time"]), 6.0)
		self.assertEqual(float(rows[0]["availability_pct"]), 75.0)

	def test_production_oee_report_preserves_raw_runtime_values(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-13", "1", clear_planned_losses=True)
		self._create_mock_submitted_entry(
			posting_date="2026-06-13",
			planned_start="2026-06-13 08:00:00",
			planned_end="2026-06-13 10:00:20",
			actual_start="2026-06-13 08:00:00",
			actual_end="2026-06-13 10:00:20",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift.name,
			unplanned_losses=[{"downtime_reason": "Other", "start_time": "10:00:00", "end_time": "10:00:20"}],
		)

		_, rows = execute({"from_date": "2026-06-13", "to_date": "2026-06-13"})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		expected_total_loss_time = (20 / 60) / 60
		expected_running_time = 8 - expected_total_loss_time
		expected_availability_pct = (expected_running_time / 8) * 100
		derived_abs_tol = 1e-6
		self.assertAlmostEqual(float(row["total_loss_time"]), expected_total_loss_time, delta=derived_abs_tol)
		self.assertAlmostEqual(float(row["running_time"]), expected_running_time, delta=derived_abs_tol)
		self.assertAlmostEqual(
			float(row["availability_pct"]), expected_availability_pct, delta=derived_abs_tol
		)

	def test_production_oee_report_availability_includes_all_linked_shifts_for_a_workstation(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift_1 = self._create_shift_for_label("2026-08-10", "1", clear_planned_losses=True)
		shift_2 = self._create_shift_for_label("2026-08-10", "2", clear_planned_losses=True)
		self._create_mock_submitted_entry(
			posting_date="2026-08-10",
			planned_start="2026-08-10 08:00:00",
			planned_end="2026-08-10 09:00:00",
			actual_start="2026-08-10 08:00:00",
			actual_end="2026-08-10 09:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift_1.name,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-08-10",
			planned_start="2026-08-10 16:00:00",
			planned_end="2026-08-10 17:00:00",
			actual_start="2026-08-10 16:00:00",
			actual_end="2026-08-10 17:00:00",
			fg_qty=100,
			rejection_qty=0,
			shift_name=shift_2.name,
		)

		_, rows = execute({"from_date": "2026-08-10", "to_date": "2026-08-10"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["avl_time_hrs"]), 16.0)

	def test_production_oee_report_availability_scopes_to_workstation_linked_shifts(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		other_workstation = "Report Workstation OEE Alt"
		if not frappe.db.exists("Workstation", other_workstation):
			frappe.get_doc(
				{
					"doctype": "Workstation",
					"workstation_name": other_workstation,
					"production_capacity": 1,
					"hour_rate": 100,
					"custom_pea_standard_spm": 2,
				}
			).insert(ignore_permissions=True)

		shift_1 = self._create_shift_for_label("2026-08-11", "1", clear_planned_losses=True)
		shift_2 = self._create_shift_for_label("2026-08-11", "2", clear_planned_losses=True)
		self._create_mock_submitted_entry(
			posting_date="2026-08-11",
			planned_start="2026-08-11 08:00:00",
			planned_end="2026-08-11 09:00:00",
			actual_start="2026-08-11 08:00:00",
			actual_end="2026-08-11 09:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift_1.name,
			workstation="Report Workstation",
		)
		self._create_mock_submitted_entry(
			posting_date="2026-08-11",
			planned_start="2026-08-11 16:00:00",
			planned_end="2026-08-11 17:00:00",
			actual_start="2026-08-11 16:00:00",
			actual_end="2026-08-11 17:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift_2.name,
			workstation=other_workstation,
		)

		_, rows = execute({"from_date": "2026-08-11", "to_date": "2026-08-11"})
		self.assertEqual(len(rows), 2)
		by_workstation = {row["workstation"]: row for row in rows}
		self.assertEqual(float(by_workstation["Report Workstation"]["avl_time_hrs"]), 8.0)
		self.assertEqual(float(by_workstation[other_workstation]["avl_time_hrs"]), 8.0)

	def test_production_oee_report_planned_loss_does_not_leak_from_unlinked_shift(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift_1 = self._create_shift_for_label("2026-08-12", "1", clear_planned_losses=True)
		self._create_shift_for_label("2026-08-12", "2")
		self._create_mock_submitted_entry(
			posting_date="2026-08-12",
			planned_start="2026-08-12 08:00:00",
			planned_end="2026-08-12 09:00:00",
			actual_start="2026-08-12 08:00:00",
			actual_end="2026-08-12 09:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift_1.name,
		)

		_, rows = execute({"from_date": "2026-08-12", "to_date": "2026-08-12"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["avl_time_hrs"]), 8.0)

	def test_production_oee_report_deducts_shift_planned_losses_from_availability(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-12", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-06-12",
			planned_start="2026-06-12 08:00:00",
			planned_end="2026-06-12 09:00:00",
			actual_start="2026-06-12 08:00:00",
			actual_end="2026-06-12 09:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift.name,
		)

		_, rows = execute({"from_date": "2026-06-12", "to_date": "2026-06-12"})
		self.assertEqual(len(rows), 1)
		# 8-hour shift with default planned losses totaling 30 minutes.
		self.assertAlmostEqual(float(rows[0]["avl_time_hrs"]), 7.5, places=2)
		self.assertAlmostEqual(float(rows[0]["running_time"]), 7.5, places=2)
		self.assertAlmostEqual(float(rows[0]["availability_pct"]), 100.0, places=2)

	def test_production_oee_report_availability_ignores_draft_shifts(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-10", "1", clear_planned_losses=True)
		draft_shift = self._create_shift_for_label("2026-06-10", "2", clear_planned_losses=True)
		frappe.db.set_value("Shift", draft_shift.name, "status", "Draft", update_modified=False)
		self._create_mock_submitted_entry(
			posting_date="2026-06-10",
			planned_start="2026-06-10 08:00:00",
			planned_end="2026-06-10 09:00:00",
			actual_start="2026-06-10 08:00:00",
			actual_end="2026-06-10 09:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift.name,
		)

		_, rows = execute({"from_date": "2026-06-10", "to_date": "2026-06-10"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["avl_time_hrs"]), 8.0)

	def test_production_oee_report_uses_zero_availability_when_no_shift_exists(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		self._create_mock_submitted_entry(
			posting_date="2026-06-11",
			planned_start="2026-06-11 08:00:00",
			planned_end="2026-06-11 09:00:00",
			actual_start="2026-06-11 08:00:00",
			actual_end="2026-06-11 09:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name="",
		)

		_, rows = execute({"from_date": "2026-06-11", "to_date": "2026-06-11"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["avl_time_hrs"]), 0.0)
		self.assertEqual(float(rows[0]["availability_pct"]), 0.0)
		self.assertEqual(float(rows[0]["running_time"]), 0.0)

	def test_production_oee_report_zero_duration_still_uses_fixed_standard_spm(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-04", "1", clear_planned_losses=True)
		self._create_mock_submitted_entry(
			posting_date="2026-06-04",
			planned_start="2026-06-04 08:00:00",
			planned_end="2026-06-04 08:00:00",
			actual_start="2026-06-04 08:00:00",
			actual_end="2026-06-04 08:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift.name,
		)
		_, rows = execute({"from_date": "2026-06-04", "to_date": "2026-06-04"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["std_spm"]), 2.0)
		self.assertEqual(float(rows[0]["productivity_pct"]), 12.5)

	def test_production_oee_report_uses_single_group_standard_spm(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-12", "1", clear_planned_losses=True)
		self._create_mock_submitted_entry(
			posting_date="2026-06-12",
			planned_start="2026-06-12 08:00:00",
			planned_end="2026-06-12 08:30:00",
			actual_start="2026-06-12 08:00:00",
			actual_end="2026-06-12 08:30:00",
			fg_qty=60,
			rejection_qty=0,
			standard_spm=2,
			shift_name=shift.name,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-06-12",
			planned_start="2026-06-12 09:00:00",
			planned_end="2026-06-12 09:30:00",
			actual_start="2026-06-12 09:00:00",
			actual_end="2026-06-12 09:30:00",
			fg_qty=60,
			rejection_qty=0,
			standard_spm=9,
			shift_name=shift.name,
		)

		_, rows = execute({"from_date": "2026-06-12", "to_date": "2026-06-12"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["std_spm"]), 2.0)

	def test_production_oee_report_availability_changes_after_running_shift_extension(self) -> None:
		"""Extending a Running shift's duration changes report availability and planned-loss deduction."""
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-07-01", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-07-01",
			planned_start="2026-07-01 08:00:00",
			planned_end="2026-07-01 09:00:00",
			actual_start="2026-07-01 08:00:00",
			actual_end="2026-07-01 09:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift.name,
		)

		_, rows = execute({"from_date": "2026-07-01", "to_date": "2026-07-01"})
		self.assertEqual(len(rows), 1)
		initial_avl_time_hrs = float(rows[0]["avl_time_hrs"])

		running_doc = frappe.get_doc("Shift", shift.name)
		running_doc.shift_duration = "10"
		running_doc.flags.ignore_links = True
		running_doc.save()
		running_doc.reload()

		_, rows = execute({"from_date": "2026-07-01", "to_date": "2026-07-01"})
		self.assertEqual(len(rows), 1)
		extended_avl_time_hrs = float(rows[0]["avl_time_hrs"])

		self.assertNotEqual(
			initial_avl_time_hrs,
			extended_avl_time_hrs,
			"Availability hours must change after shift extension",
		)
		self.assertGreater(
			extended_avl_time_hrs, initial_avl_time_hrs, "Extended shift should have more availability hours"
		)

	def test_production_oee_shift_label_cache_reuses_loaded_shift_labels(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			_get_shift_labels,
		)

		shift_label_cache = {"SHIFT-1": "1"}
		with patch(
			"production_entry_app.production_entry_app.report.production_oee_report.production_oee_report.frappe.get_list",
			return_value=[{"name": "SHIFT-2", "shift_label": "2"}],
		) as get_list:
			labels = _get_shift_labels(["SHIFT-1", "SHIFT-2"], shift_label_cache)

		self.assertEqual(labels, {"SHIFT-1": "1", "SHIFT-2": "2"})
		get_list.assert_called_once_with(
			"Shift",
			filters={"name": ["in", ["SHIFT-2"]]},
			fields=["name", "shift_label"],
			limit_page_length=0,
		)

		with patch(
			"production_entry_app.production_entry_app.report.production_oee_report.production_oee_report.frappe.get_list",
		) as get_list:
			labels = _get_shift_labels(["SHIFT-1", "SHIFT-2"], shift_label_cache)

		self.assertEqual(labels, {"SHIFT-1": "1", "SHIFT-2": "2"})
		get_list.assert_not_called()

	def test_operator_efficiency_report_groups_by_operator(self) -> None:
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			execute,
		)

		self._create_mock_submitted_entry(
			posting_date="2026-06-02",
			planned_start="2026-06-02 08:00:00",
			planned_end="2026-06-02 09:00:00",
			actual_start="2026-06-02 08:00:00",
			actual_end="2026-06-02 09:00:00",
			fg_qty=120,
			rejection_qty=0,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-06-02",
			planned_start="2026-06-02 10:00:00",
			planned_end="2026-06-02 11:00:00",
			actual_start="2026-06-02 10:00:00",
			actual_end="2026-06-02 11:00:00",
			fg_qty=120,
			rejection_qty=0,
		)

		_, rows = execute({"from_date": "2026-06-02", "to_date": "2026-06-02"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["operator"], "Report Operator")
		self.assertEqual(int(rows[0]["entries"]), 2)
		self.assertEqual(float(rows[0]["total_units"]), 240.0)
		self.assertEqual(float(rows[0]["operator_efficiency_pct"]), 100.0)

	def test_operator_efficiency_report_uses_fixed_group_standard_spm(self) -> None:
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			execute,
		)

		frappe.db.set_value("Workstation", "Report Workstation", "custom_pea_standard_spm", 4)

		self._create_mock_submitted_entry(
			posting_date="2026-06-02",
			planned_start="2026-06-02 08:00:00",
			planned_end="2026-06-02 08:10:00",
			actual_start="2026-06-02 08:00:00",
			actual_end="2026-06-02 08:10:00",
			fg_qty=100,
			rejection_qty=0,
			standard_spm=4,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-06-02",
			planned_start="2026-06-02 09:00:00",
			planned_end="2026-06-02 09:50:00",
			actual_start="2026-06-02 09:00:00",
			actual_end="2026-06-02 09:50:00",
			fg_qty=100,
			rejection_qty=0,
			standard_spm=4,
		)

		_, rows = execute({"from_date": "2026-06-02", "to_date": "2026-06-02"})
		self.assertEqual(len(rows), 1)
		self.assertAlmostEqual(float(rows[0]["actual_spm"]), 3.333, places=3)
		self.assertEqual(float(rows[0]["standard_spm"]), 4.0)
		self.assertAlmostEqual(float(rows[0]["operator_efficiency_pct"]), 83.33, delta=0.02)

	def test_operator_efficiency_report_subtracts_setup_and_loss_time(self) -> None:
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			execute,
		)

		self._create_shift_for_label("2026-06-14", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-06-14",
			planned_start="2026-06-14 08:00:00",
			planned_end="2026-06-14 09:00:00",
			actual_start="2026-06-14 08:00:00",
			actual_end="2026-06-14 09:00:00",
			fg_qty=60,
			rejection_qty=0,
			standard_spm=2,
			unplanned_losses=[
				{"downtime_reason": "Setup Time", "start_time": "08:00:00", "end_time": "08:30:00"},
				{"downtime_reason": "Maint", "start_time": "08:30:00", "end_time": "08:45:00"},
			],
		)

		_, rows = execute({"from_date": "2026-06-14", "to_date": "2026-06-14"})
		self.assertEqual(len(rows), 1)
		# 60 strokes over 15 minutes production time => 4 SPM, standard=2 => 200% efficiency.
		self.assertAlmostEqual(float(rows[0]["actual_spm"]), 4.0, places=3)
		self.assertAlmostEqual(float(rows[0]["standard_spm"]), 2.0, places=3)
		self.assertAlmostEqual(float(rows[0]["operator_efficiency_pct"]), 200.0, places=2)

	def test_operator_efficiency_report_uses_shift_planned_break_deduction(self) -> None:
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-14", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-06-14",
			planned_start="2026-06-14 08:00:00",
			planned_end="2026-06-14 16:00:00",
			actual_start="2026-06-14 08:50:00",
			actual_end="2026-06-14 09:20:00",
			fg_qty=30,
			rejection_qty=0,
			standard_spm=1,
			shift_name=shift.name,
		)

		_, rows = execute({"from_date": "2026-06-14", "to_date": "2026-06-14"})
		self.assertEqual(len(rows), 1)
		# Tea Break (09:00-09:10) is deducted from the 30 min window => 20 min production.
		self.assertAlmostEqual(float(rows[0]["actual_spm"]), 1.5, places=3)

	def test_workstation_efficiency_report_groups_by_workstation(self) -> None:
		from production_entry_app.production_entry_app.report.workstation_efficiency_report.workstation_efficiency_report import (
			execute,
		)

		self._create_mock_submitted_entry(
			posting_date="2026-06-03",
			planned_start="2026-06-03 08:00:00",
			planned_end="2026-06-03 09:00:00",
			actual_start="2026-06-03 08:00:00",
			actual_end="2026-06-03 09:00:00",
			fg_qty=120,
			rejection_qty=0,
		)

		_, rows = execute({"from_date": "2026-06-03", "to_date": "2026-06-03"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["workstation"], "Report Workstation")
		self.assertEqual(int(rows[0]["entries"]), 1)
		self.assertEqual(float(rows[0]["actual_spm"]), 2.0)
		self.assertEqual(float(rows[0]["workstation_efficiency_pct"]), 100.0)

	def test_workstation_efficiency_report_subtracts_setup_and_loss_time(self) -> None:
		from production_entry_app.production_entry_app.report.workstation_efficiency_report.workstation_efficiency_report import (
			execute,
		)

		self._create_shift_for_label("2026-06-15", "1")
		frappe.db.set_value("Workstation", "Report Workstation", "custom_pea_standard_spm", 3)
		self._create_mock_submitted_entry(
			posting_date="2026-06-15",
			planned_start="2026-06-15 08:00:00",
			planned_end="2026-06-15 09:00:00",
			actual_start="2026-06-15 08:00:00",
			actual_end="2026-06-15 09:00:00",
			fg_qty=90,
			rejection_qty=0,
			standard_spm=3,
			unplanned_losses=[
				{"downtime_reason": "Setup Time", "start_time": "08:00:00", "end_time": "08:20:00"},
				{"downtime_reason": "Maint", "start_time": "08:20:00", "end_time": "08:30:00"},
			],
		)

		_, rows = execute({"from_date": "2026-06-15", "to_date": "2026-06-15"})
		self.assertEqual(len(rows), 1)
		# 90 strokes over 30 minutes production time => 3 SPM, standard=3 => 100% efficiency.
		self.assertAlmostEqual(float(rows[0]["actual_spm"]), 3.0, places=3)
		self.assertAlmostEqual(float(rows[0]["standard_spm"]), 3.0, places=3)
		self.assertAlmostEqual(float(rows[0]["workstation_efficiency_pct"]), 100.0, places=2)

	def test_workstation_efficiency_report_uses_fixed_group_standard_spm(self) -> None:
		from production_entry_app.production_entry_app.report.workstation_efficiency_report.workstation_efficiency_report import (
			execute,
		)

		frappe.db.set_value("Workstation", "Report Workstation", "custom_pea_standard_spm", 4)
		self._create_mock_submitted_entry(
			posting_date="2026-06-15",
			planned_start="2026-06-15 08:00:00",
			planned_end="2026-06-15 08:10:00",
			actual_start="2026-06-15 08:00:00",
			actual_end="2026-06-15 08:10:00",
			fg_qty=100,
			rejection_qty=0,
			standard_spm=4,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-06-15",
			planned_start="2026-06-15 09:00:00",
			planned_end="2026-06-15 09:50:00",
			actual_start="2026-06-15 09:00:00",
			actual_end="2026-06-15 09:50:00",
			fg_qty=100,
			rejection_qty=0,
			standard_spm=4,
		)

		_, rows = execute({"from_date": "2026-06-15", "to_date": "2026-06-15"})
		self.assertEqual(len(rows), 1)
		self.assertAlmostEqual(float(rows[0]["actual_spm"]), 3.333, places=3)
		self.assertEqual(float(rows[0]["standard_spm"]), 4.0)
		self.assertAlmostEqual(float(rows[0]["workstation_efficiency_pct"]), 83.33, delta=0.02)

	def test_aggregate_efficiency_ignores_raw_duration_when_production_time_is_zero(self) -> None:
		from production_entry_app.production_entry_app.report.report_utils import (
			aggregate_efficiency_by_field,
			build_efficiency_rows,
		)

		entries = [
			{
				"custom_pea_operator": "Report Operator",
				"_good_qty": 0,
				"_rejection_qty": 0,
				"_rework_qty": 0,
				"_production_time_mins": 0,
				"_duration_mins": 60,
				"custom_pea_standard_spm": 2,
				"custom_pea_actual_spm": 0,
			},
			{
				"custom_pea_operator": "Report Operator",
				"_good_qty": 60,
				"_rejection_qty": 0,
				"_rework_qty": 0,
				"_production_time_mins": 30,
				"_duration_mins": 30,
				"custom_pea_standard_spm": 2,
				"custom_pea_actual_spm": 2,
			},
		]

		aggregates = aggregate_efficiency_by_field(entries, "custom_pea_operator")
		self.assertEqual(flt(aggregates["Report Operator"]["duration_mins"]), 30.0)

		rows = build_efficiency_rows(aggregates, "operator", "operator_efficiency_pct")
		self.assertEqual(len(rows), 1)
		self.assertAlmostEqual(float(rows[0]["actual_spm"]), 2.0, places=3)
		self.assertAlmostEqual(float(rows[0]["standard_spm"]), 2.0, places=3)

	def test_aggregate_efficiency_uses_first_positive_standard_spm(self) -> None:
		from production_entry_app.production_entry_app.report.report_utils import (
			aggregate_efficiency_by_field,
			build_efficiency_rows,
		)

		entries = [
			{
				"custom_pea_operator": "Report Operator",
				"_good_qty": 40,
				"_rejection_qty": 0,
				"_rework_qty": 0,
				"_production_time_mins": 10,
				"_duration_mins": 10,
				"custom_pea_standard_spm": 4,
				"custom_pea_actual_spm": 4,
			},
			{
				"custom_pea_operator": "Report Operator",
				"_good_qty": 200,
				"_rejection_qty": 0,
				"_rework_qty": 0,
				"_production_time_mins": 50,
				"_duration_mins": 50,
				"custom_pea_standard_spm": 9,
				"custom_pea_actual_spm": 4,
			},
		]

		aggregates = aggregate_efficiency_by_field(entries, "custom_pea_operator")
		rows = build_efficiency_rows(aggregates, "operator", "operator_efficiency_pct")
		self.assertEqual(len(rows), 1)
		self.assertAlmostEqual(float(rows[0]["standard_spm"]), 4.0, places=3)
		self.assertAlmostEqual(float(rows[0]["operator_efficiency_pct"]), 100.0, places=2)

	def test_parent_quantity_metrics_split_rejection_and_rework(self) -> None:
		from production_entry_app.production_entry_app.report.report_utils import get_parent_quantity_metrics

		shift = self._create_shift_for_label("2094-06-06", "1")
		entry = self._create_mock_submitted_entry_with_breakup(
			posting_date="2094-06-06",
			planned_start="2094-06-06 08:00:00",
			planned_end="2094-06-06 09:00:00",
			actual_start="2094-06-06 08:00:00",
			actual_end="2094-06-06 09:00:00",
			fg_qty=100,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Burr", "qty": 3, "is_rework": 1},
				{"rejection_reason": "Crack", "qty": 2, "is_rework": 0},
			],
		)

		metrics = get_parent_quantity_metrics([entry.name], include_rework=True)[entry.name]
		self.assertEqual(float(metrics["good_qty"]), 95.0)
		self.assertEqual(float(metrics["rejection_qty"]), 2.0)
		self.assertEqual(float(metrics["rework_qty"]), 3.0)
		self.assertEqual(float(metrics["total_rejected_qty"]), 5.0)

	def test_get_entry_raw_duration_minutes_falls_back_to_datetime_delta(self) -> None:
		from production_entry_app.production_entry_app.report.report_utils import (
			get_entry_raw_duration_minutes,
		)

		entry = {
			"custom_pea_actual_duration_mins": 0,
			"custom_pea_actual_start_date": "2026-08-20 08:00:00",
			"custom_pea_actual_end_date": "2026-08-20 08:45:00",
		}
		self.assertEqual(float(get_entry_raw_duration_minutes(entry)), 45.0)

	def test_efficiency_oee_and_daily_reports_include_rework_values(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute as daily_execute,
		)
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			execute as operator_execute,
		)
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute as oee_execute,
		)
		from production_entry_app.production_entry_app.report.workstation_efficiency_report.workstation_efficiency_report import (
			execute as workstation_execute,
		)

		shift = self._create_shift_for_label("2094-06-07", "1")
		fiscal_year = self._ensure_fiscal_year("2094", "2094-01-01", "2094-12-31")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2094-06-07",
			planned_start="2094-06-07 08:00:00",
			planned_end="2094-06-07 09:00:00",
			actual_start="2094-06-07 08:00:00",
			actual_end="2094-06-07 09:00:00",
			fg_qty=100,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Burr", "qty": 3, "is_rework": 1},
				{"rejection_reason": "Crack", "qty": 2, "is_rework": 0},
			],
		)

		operator_columns, operator_rows = operator_execute(
			{"from_date": "2094-06-07", "to_date": "2094-06-07"}
		)
		workstation_columns, workstation_rows = workstation_execute(
			{"from_date": "2094-06-07", "to_date": "2094-06-07"}
		)
		_, oee_rows = oee_execute({"from_date": "2094-06-07", "to_date": "2094-06-07"})
		daily_columns, daily_rows = daily_execute(
			{"fiscal_year": fiscal_year, "month": "June", "custom_pea_operator": "Report Operator"}
		)

		self.assertIn("rework_qty", [c.get("fieldname") for c in operator_columns])
		self.assertIn("rework_qty", [c.get("fieldname") for c in workstation_columns])
		self.assertIn("rework", [c.get("fieldname") for c in daily_columns])
		self.assertEqual(float(operator_rows[0]["rejection_qty"]), 2.0)
		self.assertEqual(float(operator_rows[0]["rework_qty"]), 3.0)
		self.assertEqual(float(workstation_rows[0]["rejection_qty"]), 2.0)
		self.assertEqual(float(workstation_rows[0]["rework_qty"]), 3.0)
		self.assertEqual(float(oee_rows[0]["rejection"]), 2.0)
		self.assertEqual(float(daily_rows[0]["rejection"]), 2.0)
		self.assertEqual(float(daily_rows[0]["rework"]), 3.0)

	def test_die_tool_stroke_report_uses_counter_and_maintenance(self) -> None:
		from production_entry_app.production_entry_app.report.die_tool_stroke_and_maintenance_report.die_tool_stroke_and_maintenance_report import (
			execute,
		)

		frappe.get_doc(
			{
				"doctype": "Die Tool Counter",
				"die_tool_item": self.fg_item,
				"current_stroke_count": 500,
				"stroke_capacity": 1000,
				"warning_threshold_pct": 90,
			}
		).insert(ignore_permissions=True)

		maintenance = frappe.get_doc(
			{
				"doctype": "Die Tool Maintenance Log",
				"die_tool_item": self.fg_item,
				"maintenance_date": "2026-06-04 12:00:00",
				"remarks": "Routine maintenance",
			}
		).insert(ignore_permissions=True)
		maintenance.submit()

		_, rows = execute({"item_code": self.fg_item})
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["die_tool_item"], self.fg_item)
		self.assertEqual(float(rows[0]["current_stroke_count"]), 0.0)
		self.assertEqual(float(rows[0]["stroke_capacity"]), 1000.0)
		self.assertEqual(float(rows[0]["utilization_pct"]), 0.0)
		self.assertEqual(int(rows[0]["maintenance_due"]), 0)
		self.assertEqual(str(rows[0]["last_maintenance_date"]), "2026-06-04 12:00:00")
		self.assertEqual(int(rows[0]["maintenance_count"]), 1)

	def test_die_tool_stroke_report_preserves_raw_health_metrics(self) -> None:
		from production_entry_app.production_entry_app.report.die_tool_stroke_and_maintenance_report.die_tool_stroke_and_maintenance_report import (
			execute,
		)

		item_code = _get_or_create_item("_Test FG Item For Reports Die Tool Raw")
		frappe.get_doc(
			{
				"doctype": "Die Tool Counter",
				"die_tool_item": item_code,
				"current_stroke_count": 1,
				"stroke_capacity": 3,
				"warning_threshold_pct": 100 / 3,
			}
		).insert(ignore_permissions=True)

		_, rows = execute({"item_code": item_code})
		self.assertEqual(len(rows), 1)
		derived_abs_tol = 1e-6
		self.assertAlmostEqual(float(rows[0]["utilization_pct"]), 100 / 3, delta=derived_abs_tol)
		# warning_threshold_pct is read from DB where field precision may round it;
		# the report no longer rewrites this value — it stays at the stored value.
		db_threshold = float(
			frappe.db.get_value("Die Tool Counter", {"die_tool_item": item_code}, "warning_threshold_pct")
			or 0
		)
		self.assertAlmostEqual(float(rows[0]["warning_threshold_pct"]), db_threshold, delta=derived_abs_tol)
		self.assertEqual(int(rows[0]["maintenance_due"]), 1)

	def test_reports_return_empty_when_no_matching_entries(self) -> None:
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			execute as operator_execute,
		)
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute as oee_execute,
		)
		from production_entry_app.production_entry_app.report.workstation_efficiency_report.workstation_efficiency_report import (
			execute as workstation_execute,
		)

		_, oee_rows = oee_execute({"from_date": "2026-07-01", "to_date": "2026-07-01"})
		_, operator_rows = operator_execute({"from_date": "2026-07-01", "to_date": "2026-07-01"})
		_, workstation_rows = workstation_execute({"from_date": "2026-07-01", "to_date": "2026-07-01"})
		self.assertEqual(oee_rows, [])
		self.assertEqual(operator_rows, [])
		self.assertEqual(workstation_rows, [])

	def test_reports_execute_without_filters_returns_rows_or_empty(self) -> None:
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			execute as operator_execute,
		)
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute as oee_execute,
		)
		from production_entry_app.production_entry_app.report.workstation_efficiency_report.workstation_efficiency_report import (
			execute as workstation_execute,
		)

		_, oee_rows = oee_execute({})
		_, operator_rows = operator_execute({})
		_, workstation_rows = workstation_execute({})
		self.assertIsInstance(oee_rows, list)
		self.assertIsInstance(operator_rows, list)
		self.assertIsInstance(workstation_rows, list)

	def test_reports_support_fg_item_filter_for_operator_and_workstation(self) -> None:
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			execute as operator_execute,
		)
		from production_entry_app.production_entry_app.report.workstation_efficiency_report.workstation_efficiency_report import (
			execute as workstation_execute,
		)

		other_fg_item = _get_or_create_item("_Test FG Item For Reports Filter")
		self._create_mock_submitted_entry(
			posting_date="2026-06-05",
			planned_start="2026-06-05 08:00:00",
			planned_end="2026-06-05 09:00:00",
			actual_start="2026-06-05 08:00:00",
			actual_end="2026-06-05 09:00:00",
			fg_qty=100,
			rejection_qty=0,
			fg_item=self.fg_item,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-06-05",
			planned_start="2026-06-05 10:00:00",
			planned_end="2026-06-05 11:00:00",
			actual_start="2026-06-05 10:00:00",
			actual_end="2026-06-05 11:00:00",
			fg_qty=100,
			rejection_qty=0,
			fg_item=other_fg_item,
		)

		filters = {"from_date": "2026-06-05", "to_date": "2026-06-05", "fg_item": self.fg_item}
		_, operator_rows = operator_execute(filters)
		_, workstation_rows = workstation_execute(filters)
		self.assertEqual(len(operator_rows), 1)
		self.assertEqual(float(operator_rows[0]["total_units"]), 100.0)
		self.assertEqual(len(workstation_rows), 1)
		self.assertEqual(float(workstation_rows[0]["total_units"]), 100.0)

	def test_operator_and_workstation_reports_group_unassigned(self) -> None:
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			execute as operator_execute,
		)
		from production_entry_app.production_entry_app.report.workstation_efficiency_report.workstation_efficiency_report import (
			execute as workstation_execute,
		)

		self._create_mock_submitted_entry(
			posting_date="2026-06-06",
			planned_start="2026-06-06 08:00:00",
			planned_end="2026-06-06 09:00:00",
			actual_start="2026-06-06 08:00:00",
			actual_end="2026-06-06 09:00:00",
			fg_qty=100,
			rejection_qty=0,
			operator="",
			workstation="",
		)

		filters = {"from_date": "2026-06-06", "to_date": "2026-06-06"}
		_, operator_rows = operator_execute(filters)
		_, workstation_rows = workstation_execute(filters)
		self.assertEqual(len(operator_rows), 1)
		self.assertEqual(operator_rows[0]["operator"], "Unassigned")
		self.assertEqual(len(workstation_rows), 1)
		self.assertEqual(workstation_rows[0]["workstation"], "Unassigned")

	def test_rejection_pareto_report_aggregates_and_sorts_reasons(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_pareto_report.rejection_pareto_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-10", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-10",
			planned_start="2026-06-10 08:00:00",
			planned_end="2026-06-10 09:00:00",
			actual_start="2026-06-10 08:00:00",
			actual_end="2026-06-10 09:00:00",
			fg_qty=120,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 4},
				{"rejection_reason": "Burr", "qty": 1},
			],
		)
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-10",
			planned_start="2026-06-10 10:00:00",
			planned_end="2026-06-10 11:00:00",
			actual_start="2026-06-10 10:00:00",
			actual_end="2026-06-10 11:00:00",
			fg_qty=100,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 2},
				{"rejection_reason": "Blank Cut", "qty": 3},
			],
		)

		_, rows, _, chart = execute({"from_date": "2026-06-10", "to_date": "2026-06-10"})
		self.assertEqual([row["rejection_reason"] for row in rows], ["Crack", "Blank Cut", "Burr"])
		self.assertEqual(float(rows[0]["rejection_qty"]), 6.0)
		self.assertEqual(float(rows[1]["rejection_qty"]), 3.0)
		self.assertEqual(float(rows[2]["rejection_qty"]), 1.0)
		self.assertEqual(float(rows[0]["rejection_pct"]), 60.0)
		self.assertEqual(float(rows[0]["cumulative_pct"]), 60.0)
		self.assertEqual(float(rows[1]["cumulative_pct"]), 90.0)
		self.assertEqual(float(rows[2]["cumulative_pct"]), 100.0)
		self.assertEqual(int(rows[0]["entries"]), 2)
		self.assertEqual(int(rows[0]["shifts"]), 1)
		self.assertEqual(chart.get("type"), "axis-mixed")
		self.assertEqual(chart.get("data", {}).get("labels"), ["Crack", "Blank Cut", "Burr"])

	def test_rejection_pareto_report_filters_workstation(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_pareto_report.rejection_pareto_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-11", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-11",
			planned_start="2026-06-11 08:00:00",
			planned_end="2026-06-11 09:00:00",
			actual_start="2026-06-11 08:00:00",
			actual_end="2026-06-11 09:00:00",
			fg_qty=80,
			workstation="Report Workstation",
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Crack", "qty": 5}],
		)
		other_workstation = "Report Workstation 2"
		if not frappe.db.exists("Workstation", other_workstation):
			frappe.get_doc(
				{
					"doctype": "Workstation",
					"workstation_name": other_workstation,
					"production_capacity": 1,
					"hour_rate": 100,
					"custom_pea_standard_spm": 2,
				}
			).insert(ignore_permissions=True)
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-11",
			planned_start="2026-06-11 10:00:00",
			planned_end="2026-06-11 11:00:00",
			actual_start="2026-06-11 10:00:00",
			actual_end="2026-06-11 11:00:00",
			fg_qty=80,
			workstation=other_workstation,
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Burr", "qty": 4}],
		)

		_, rows, _, _chart = execute(
			{
				"from_date": "2026-06-11",
				"to_date": "2026-06-11",
				"custom_pea_workstation": "Report Workstation",
			}
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["rejection_reason"], "Crack")
		self.assertEqual(float(rows[0]["rejection_qty"]), 5.0)

	def test_rejection_pareto_report_merges_duplicate_reason_rows_per_entry(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_pareto_report.rejection_pareto_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-11", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-11",
			planned_start="2026-06-11 12:00:00",
			planned_end="2026-06-11 13:00:00",
			actual_start="2026-06-11 12:00:00",
			actual_end="2026-06-11 13:00:00",
			fg_qty=90,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 2},
				{"rejection_reason": "Crack", "qty": 3},
				{"rejection_reason": "Burr", "qty": 1},
			],
		)

		_, rows, _, _chart = execute({"from_date": "2026-06-11", "to_date": "2026-06-11"})
		self.assertEqual([row["rejection_reason"] for row in rows], ["Crack", "Burr"])
		self.assertEqual(float(rows[0]["rejection_qty"]), 5.0)
		self.assertEqual(int(rows[0]["entries"]), 1)

	def test_rejection_pareto_report_preserves_raw_cumulative_pct_until_final_clamp(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_pareto_report.rejection_pareto_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-12", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-12",
			planned_start="2026-06-12 14:00:00",
			planned_end="2026-06-12 15:00:00",
			actual_start="2026-06-12 14:00:00",
			actual_end="2026-06-12 15:00:00",
			fg_qty=30,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 1},
				{"rejection_reason": "Blank Cut", "qty": 1},
				{"rejection_reason": "Burr", "qty": 1},
			],
		)

		_, rows, _, chart = execute({"from_date": "2026-06-12", "to_date": "2026-06-12"})
		expected_pct = 100 / 3
		derived_abs_tol = 1e-6
		self.assertEqual([row["rejection_reason"] for row in rows], ["Blank Cut", "Burr", "Crack"])
		self.assertAlmostEqual(float(rows[0]["rejection_pct"]), expected_pct, delta=derived_abs_tol)
		self.assertAlmostEqual(float(rows[0]["cumulative_pct"]), expected_pct, delta=derived_abs_tol)
		self.assertAlmostEqual(float(rows[1]["cumulative_pct"]), expected_pct * 2, delta=derived_abs_tol)
		self.assertEqual(float(rows[2]["cumulative_pct"]), 100.0)
		self.assertEqual(chart.get("type"), "axis-mixed")
		self.assertAlmostEqual(
			float(chart["data"]["datasets"][1]["values"][0]), expected_pct, delta=derived_abs_tol
		)
		self.assertAlmostEqual(
			float(chart["data"]["datasets"][1]["values"][1]), expected_pct * 2, delta=derived_abs_tol
		)
		self.assertEqual(float(chart["data"]["datasets"][1]["values"][2]), 100.0)

	def test_rejection_reports_exclude_rework_rows(self) -> None:
		from production_entry_app.production_entry_app.report.item_bom_rejection_hotspots.item_bom_rejection_hotspots import (
			execute as rejection_hotspots_execute,
		)
		from production_entry_app.production_entry_app.report.operator_rejection_performance.operator_rejection_performance import (
			execute as operator_rejection_execute,
		)
		from production_entry_app.production_entry_app.report.rejection_pareto_report.rejection_pareto_report import (
			execute as rejection_pareto_execute,
		)
		from production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report import (
			execute as rejection_ppm_execute,
		)
		from production_entry_app.production_entry_app.report.rejection_trend_report.rejection_trend_report import (
			execute as rejection_trend_execute,
		)
		from production_entry_app.production_entry_app.report.workstation_rejection_reason_matrix.workstation_rejection_reason_matrix import (
			execute as rejection_matrix_execute,
		)

		shift = self._create_shift_for_label("2026-07-10", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-07-10",
			planned_start="2026-07-10 08:00:00",
			planned_end="2026-07-10 09:00:00",
			actual_start="2026-07-10 08:00:00",
			actual_end="2026-07-10 09:00:00",
			fg_qty=100,
			operator="Report Operator",
			workstation="Report Workstation",
			fg_item=self.fg_item,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 4, "is_rework": 0},
				{"rejection_reason": "Burr", "qty": 6, "is_rework": 1},
			],
		)

		_, pareto_rows, _, _ = rejection_pareto_execute({"from_date": "2026-07-10", "to_date": "2026-07-10"})
		_, trend_rows, _, _ = rejection_trend_execute({"from_date": "2026-07-10", "to_date": "2026-07-10"})
		_, ppm_rows, _, _ = rejection_ppm_execute({"from_date": "2026-07-10", "to_date": "2026-07-10"})
		_, operator_rows = operator_rejection_execute({"from_date": "2026-07-10", "to_date": "2026-07-10"})
		_, hotspot_rows = rejection_hotspots_execute({"from_date": "2026-07-10", "to_date": "2026-07-10"})
		_, matrix_rows = rejection_matrix_execute({"from_date": "2026-07-10", "to_date": "2026-07-10"})

		self.assertEqual(len(pareto_rows), 1)
		self.assertEqual(pareto_rows[0]["rejection_reason"], "Crack")
		self.assertEqual(float(pareto_rows[0]["rejection_qty"]), 4.0)
		self.assertEqual(float(trend_rows[0]["rejection_qty"]), 4.0)
		self.assertEqual(float(trend_rows[0]["ok_qty"]), 96.0)
		self.assertEqual(float(ppm_rows[0]["rejection_qty"]), 4.0)
		self.assertEqual(float(ppm_rows[0]["ppm"]), 40_000.0)
		self.assertEqual(float(operator_rows[0]["rejection_qty"]), 4.0)
		self.assertIn("Crack (4", operator_rows[0]["top_3_reasons"])
		self.assertNotIn("Burr", operator_rows[0]["top_3_reasons"])
		self.assertEqual(float(hotspot_rows[0]["rejection_qty"]), 4.0)
		self.assertIn("Crack (4", hotspot_rows[0]["dominant_reason"])
		self.assertEqual(float(matrix_rows[0]["total_rejection_qty"]), 4.0)
		self.assertEqual(float(matrix_rows[0]["reason_crack"]), 4.0)

	def test_rejection_trend_report_daily_aggregation(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_trend_report.rejection_trend_report import (
			execute,
		)

		shift_day_1 = self._create_shift_for_label("2026-06-12", "1")
		shift_day_2 = self._create_shift_for_label("2026-06-13", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-06-12",
			planned_start="2026-06-12 08:00:00",
			planned_end="2026-06-12 09:00:00",
			actual_start="2026-06-12 08:00:00",
			actual_end="2026-06-12 09:00:00",
			fg_qty=100,
			rejection_qty=10,
			shift_name=shift_day_1.name,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-06-13",
			planned_start="2026-06-13 08:00:00",
			planned_end="2026-06-13 09:00:00",
			actual_start="2026-06-13 08:00:00",
			actual_end="2026-06-13 09:00:00",
			fg_qty=80,
			rejection_qty=8,
			shift_name=shift_day_2.name,
		)

		_, rows, _, chart = execute(
			{"from_date": "2026-06-12", "to_date": "2026-06-13", "time_grain": "Daily"}
		)
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["period"], "2026-06-12")
		self.assertEqual(float(rows[0]["total_qty"]), 100.0)
		self.assertEqual(float(rows[0]["rejection_qty"]), 10.0)
		self.assertEqual(float(rows[0]["ok_qty"]), 90.0)
		self.assertEqual(float(rows[0]["rejection_rate_pct"]), 10.0)
		self.assertEqual(rows[1]["period"], "2026-06-13")
		self.assertEqual(float(rows[1]["rejection_rate_pct"]), 10.0)
		self.assertEqual(chart.get("type"), "axis-mixed")
		self.assertEqual(chart.get("data", {}).get("labels"), ["2026-06-12", "2026-06-13"])

	def test_rejection_trend_report_chart_preserves_raw_rate_values(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_trend_report.rejection_trend_report import (
			execute,
		)

		shift_day_1 = self._create_shift_for_label("2026-06-14", "1")
		shift_day_2 = self._create_shift_for_label("2026-06-15", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-06-14",
			planned_start="2026-06-14 08:00:00",
			planned_end="2026-06-14 09:00:00",
			actual_start="2026-06-14 08:00:00",
			actual_end="2026-06-14 09:00:00",
			fg_qty=3,
			rejection_qty=1,
			shift_name=shift_day_1.name,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-06-15",
			planned_start="2026-06-15 08:00:00",
			planned_end="2026-06-15 09:00:00",
			actual_start="2026-06-15 08:00:00",
			actual_end="2026-06-15 09:00:00",
			fg_qty=6,
			rejection_qty=2,
			shift_name=shift_day_2.name,
		)

		_, rows, _, chart = execute(
			{"from_date": "2026-06-14", "to_date": "2026-06-15", "time_grain": "Daily"}
		)
		expected_rate = 100 / 3
		derived_abs_tol = 1e-6
		self.assertEqual(len(rows), 2)
		self.assertAlmostEqual(float(rows[0]["rejection_rate_pct"]), expected_rate, delta=derived_abs_tol)
		self.assertAlmostEqual(float(rows[1]["rejection_rate_pct"]), expected_rate, delta=derived_abs_tol)
		self.assertEqual(chart.get("type"), "axis-mixed")
		self.assertAlmostEqual(
			float(chart["data"]["datasets"][1]["values"][0]), expected_rate, delta=derived_abs_tol
		)
		self.assertAlmostEqual(
			float(chart["data"]["datasets"][1]["values"][1]), expected_rate, delta=derived_abs_tol
		)

	def test_rejection_trend_report_weekly_aggregation(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_trend_report.rejection_trend_report import (
			execute,
		)

		shift_day_1 = self._create_shift_for_label("2026-06-15", "1")
		shift_day_2 = self._create_shift_for_label("2026-06-16", "1")
		shift_day_3 = self._create_shift_for_label("2026-06-22", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-06-15",
			planned_start="2026-06-15 08:00:00",
			planned_end="2026-06-15 09:00:00",
			actual_start="2026-06-15 08:00:00",
			actual_end="2026-06-15 09:00:00",
			fg_qty=100,
			rejection_qty=5,
			shift_name=shift_day_1.name,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-06-16",
			planned_start="2026-06-16 08:00:00",
			planned_end="2026-06-16 09:00:00",
			actual_start="2026-06-16 08:00:00",
			actual_end="2026-06-16 09:00:00",
			fg_qty=60,
			rejection_qty=3,
			shift_name=shift_day_2.name,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-06-22",
			planned_start="2026-06-22 08:00:00",
			planned_end="2026-06-22 09:00:00",
			actual_start="2026-06-22 08:00:00",
			actual_end="2026-06-22 09:00:00",
			fg_qty=90,
			rejection_qty=9,
			shift_name=shift_day_3.name,
		)

		_, rows, _, _chart = execute(
			{"from_date": "2026-06-15", "to_date": "2026-06-22", "time_grain": "Weekly"}
		)
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["period"], "2026-06-15 to 2026-06-21")
		self.assertEqual(float(rows[0]["total_qty"]), 160.0)
		self.assertEqual(float(rows[0]["rejection_qty"]), 8.0)
		self.assertEqual(float(rows[1]["total_qty"]), 90.0)
		self.assertEqual(float(rows[1]["rejection_rate_pct"]), 10.0)

	def test_rejection_trend_report_monthly_aggregation(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_trend_report.rejection_trend_report import (
			execute,
		)

		shift_june = self._create_shift_for_label("2026-06-29", "1")
		shift_july = self._create_shift_for_label("2026-07-02", "1")
		fg_item = _get_or_create_item(f"_Test FG Item For Rejection Trend {frappe.generate_hash(length=8)}")
		self._create_mock_submitted_entry(
			posting_date="2026-06-29",
			planned_start="2026-06-29 08:00:00",
			planned_end="2026-06-29 09:00:00",
			actual_start="2026-06-29 08:00:00",
			actual_end="2026-06-29 09:00:00",
			fg_qty=100,
			rejection_qty=10,
			shift_name=shift_june.name,
			fg_item=fg_item,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-07-02",
			planned_start="2026-07-02 08:00:00",
			planned_end="2026-07-02 09:00:00",
			actual_start="2026-07-02 08:00:00",
			actual_end="2026-07-02 09:00:00",
			fg_qty=80,
			rejection_qty=8,
			shift_name=shift_july.name,
			fg_item=fg_item,
		)

		_, rows, _, _chart = execute(
			{
				"from_date": "2026-06-01",
				"to_date": "2026-07-31",
				"time_grain": "Monthly",
				"fg_item": fg_item,
			}
		)
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["period"], "2026-06")
		self.assertEqual(float(rows[0]["rejection_rate_pct"]), 10.0)
		self.assertEqual(rows[1]["period"], "2026-07")
		self.assertEqual(float(rows[1]["rejection_rate_pct"]), 10.0)

	def test_workstation_rejection_reason_matrix_aggregates_top_reasons(self) -> None:
		from production_entry_app.production_entry_app.report.workstation_rejection_reason_matrix.workstation_rejection_reason_matrix import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-23", "1")
		workstation_2 = "Report Workstation 3"
		if not frappe.db.exists("Workstation", workstation_2):
			frappe.get_doc(
				{
					"doctype": "Workstation",
					"workstation_name": workstation_2,
					"production_capacity": 1,
					"hour_rate": 100,
					"custom_pea_standard_spm": 2,
				}
			).insert(ignore_permissions=True)

		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-23",
			planned_start="2026-06-23 08:00:00",
			planned_end="2026-06-23 09:00:00",
			actual_start="2026-06-23 08:00:00",
			actual_end="2026-06-23 09:00:00",
			fg_qty=100,
			workstation="Report Workstation",
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 5},
				{"rejection_reason": "Burr", "qty": 2},
			],
		)
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-23",
			planned_start="2026-06-23 10:00:00",
			planned_end="2026-06-23 11:00:00",
			actual_start="2026-06-23 10:00:00",
			actual_end="2026-06-23 11:00:00",
			fg_qty=80,
			workstation=workstation_2,
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Blank Cut", "qty": 4}],
		)

		columns, rows = execute({"from_date": "2026-06-23", "to_date": "2026-06-23", "top_n_reasons": 2})
		column_labels = [col.get("label") for col in columns]
		self.assertIn("Crack", column_labels)
		self.assertIn("Blank Cut", column_labels)
		self.assertNotIn("Burr", column_labels)
		self.assertEqual(len(rows), 2)
		row_by_workstation = {row["workstation"]: row for row in rows}
		self.assertEqual(float(row_by_workstation["Report Workstation"]["reason_crack"]), 5.0)
		self.assertEqual(float(row_by_workstation[workstation_2]["reason_blank_cut"]), 4.0)
		self.assertEqual(float(row_by_workstation["Report Workstation"]["total_rejection_qty"]), 7.0)

	def test_workstation_rejection_reason_matrix_filters_operator(self) -> None:
		from production_entry_app.production_entry_app.report.workstation_rejection_reason_matrix.workstation_rejection_reason_matrix import (
			execute,
		)

		operator_2 = "Report Operator 2"
		if not frappe.db.exists("Operator", operator_2):
			frappe.get_doc({"doctype": "Operator", "operator_name": operator_2, "is_active": 1}).insert(
				ignore_permissions=True
			)
		shift = self._create_shift_for_label("2026-06-24", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-24",
			planned_start="2026-06-24 08:00:00",
			planned_end="2026-06-24 09:00:00",
			actual_start="2026-06-24 08:00:00",
			actual_end="2026-06-24 09:00:00",
			fg_qty=100,
			operator="Report Operator",
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Crack", "qty": 5}],
		)
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-24",
			planned_start="2026-06-24 10:00:00",
			planned_end="2026-06-24 11:00:00",
			actual_start="2026-06-24 10:00:00",
			actual_end="2026-06-24 11:00:00",
			fg_qty=90,
			operator=operator_2,
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Burr", "qty": 3}],
		)

		_, rows = execute(
			{
				"from_date": "2026-06-24",
				"to_date": "2026-06-24",
				"custom_pea_operator": "Report Operator",
			}
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["workstation"], "Report Workstation")
		self.assertEqual(float(rows[0]["total_rejection_qty"]), 5.0)

	def test_operator_rejection_performance_metrics_and_top_reasons(self) -> None:
		from production_entry_app.production_entry_app.report.operator_rejection_performance.operator_rejection_performance import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-25", "1")
		operator_2 = "Report Operator 2"
		if not frappe.db.exists("Operator", operator_2):
			frappe.get_doc({"doctype": "Operator", "operator_name": operator_2, "is_active": 1}).insert(
				ignore_permissions=True
			)

		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-25",
			planned_start="2026-06-25 08:00:00",
			planned_end="2026-06-25 09:00:00",
			actual_start="2026-06-25 08:00:00",
			actual_end="2026-06-25 09:00:00",
			fg_qty=100,
			operator="Report Operator",
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 6},
				{"rejection_reason": "Burr", "qty": 2},
			],
		)
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-25",
			planned_start="2026-06-25 10:00:00",
			planned_end="2026-06-25 11:00:00",
			actual_start="2026-06-25 10:00:00",
			actual_end="2026-06-25 11:00:00",
			fg_qty=80,
			operator=operator_2,
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Blank Cut", "qty": 4}],
		)

		_, rows = execute({"from_date": "2026-06-25", "to_date": "2026-06-25"})
		self.assertEqual(len(rows), 2)
		row_by_operator = {row["operator"]: row for row in rows}
		self.assertEqual(float(row_by_operator["Report Operator"]["total_qty"]), 100.0)
		self.assertEqual(float(row_by_operator["Report Operator"]["rejection_qty"]), 8.0)
		self.assertEqual(float(row_by_operator["Report Operator"]["rejection_rate_pct"]), 8.0)
		self.assertIn("Crack (6", row_by_operator["Report Operator"]["top_3_reasons"])
		self.assertIn("Burr (2", row_by_operator["Report Operator"]["top_3_reasons"])
		self.assertEqual(float(row_by_operator[operator_2]["rejection_rate_pct"]), 5.0)

	def test_operator_rejection_performance_preserves_raw_rate_and_string_summary_contract(self) -> None:
		from production_entry_app.production_entry_app.report.operator_rejection_performance.operator_rejection_performance import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-25", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-25",
			planned_start="2026-06-25 12:00:00",
			planned_end="2026-06-25 13:00:00",
			actual_start="2026-06-25 12:00:00",
			actual_end="2026-06-25 13:00:00",
			fg_qty=3,
			operator="Report Operator",
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Crack", "qty": 1}],
		)

		_, rows = execute(
			{
				"from_date": "2026-06-25",
				"to_date": "2026-06-25",
				"custom_pea_operator": "Report Operator",
			}
		)
		self.assertEqual(len(rows), 1)
		derived_abs_tol = 1e-6
		self.assertAlmostEqual(float(rows[0]["rejection_rate_pct"]), 100 / 3, delta=derived_abs_tol)
		self.assertIsInstance(rows[0]["top_3_reasons"], str)
		self.assertIn("Crack (1", rows[0]["top_3_reasons"])

	def test_operator_rejection_performance_filters_workstation(self) -> None:
		from production_entry_app.production_entry_app.report.operator_rejection_performance.operator_rejection_performance import (
			execute,
		)

		workstation_2 = "Report Workstation 4"
		if not frappe.db.exists("Workstation", workstation_2):
			frappe.get_doc(
				{
					"doctype": "Workstation",
					"workstation_name": workstation_2,
					"production_capacity": 1,
					"hour_rate": 100,
					"custom_pea_standard_spm": 2,
				}
			).insert(ignore_permissions=True)
		shift = self._create_shift_for_label("2026-06-26", "1")

		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-26",
			planned_start="2026-06-26 08:00:00",
			planned_end="2026-06-26 09:00:00",
			actual_start="2026-06-26 08:00:00",
			actual_end="2026-06-26 09:00:00",
			fg_qty=100,
			workstation="Report Workstation",
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Crack", "qty": 3}],
		)
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-26",
			planned_start="2026-06-26 10:00:00",
			planned_end="2026-06-26 11:00:00",
			actual_start="2026-06-26 10:00:00",
			actual_end="2026-06-26 11:00:00",
			fg_qty=100,
			workstation=workstation_2,
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Burr", "qty": 6}],
		)

		_, rows = execute(
			{
				"from_date": "2026-06-26",
				"to_date": "2026-06-26",
				"custom_pea_workstation": workstation_2,
			}
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["rejection_qty"]), 6.0)

	def test_item_bom_rejection_hotspots_aggregates_and_sorts(self) -> None:
		from production_entry_app.production_entry_app.report.item_bom_rejection_hotspots.item_bom_rejection_hotspots import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-27", "1")
		item_2 = _get_or_create_item("_Test FG Item For Reports 2")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-27",
			planned_start="2026-06-27 08:00:00",
			planned_end="2026-06-27 09:00:00",
			actual_start="2026-06-27 08:00:00",
			actual_end="2026-06-27 09:00:00",
			fg_qty=100,
			fg_item=self.fg_item,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 6},
				{"rejection_reason": "Burr", "qty": 2},
			],
		)
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-27",
			planned_start="2026-06-27 10:00:00",
			planned_end="2026-06-27 11:00:00",
			actual_start="2026-06-27 10:00:00",
			actual_end="2026-06-27 11:00:00",
			fg_qty=80,
			fg_item=item_2,
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Blank Cut", "qty": 4}],
		)

		_, rows = execute({"from_date": "2026-06-27", "to_date": "2026-06-27"})
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["item_code"], self.fg_item)
		self.assertEqual(float(rows[0]["total_qty"]), 100.0)
		self.assertEqual(float(rows[0]["rejection_qty"]), 8.0)
		self.assertEqual(float(rows[0]["rejection_rate_pct"]), 8.0)
		self.assertIn("Crack (6", rows[0]["dominant_reason"])
		self.assertEqual(float(rows[1]["rejection_qty"]), 4.0)

	def test_item_bom_rejection_hotspots_filters_fg_item(self) -> None:
		from production_entry_app.production_entry_app.report.item_bom_rejection_hotspots.item_bom_rejection_hotspots import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-28", "1")
		item_2 = _get_or_create_item("_Test FG Item For Reports 3")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-28",
			planned_start="2026-06-28 08:00:00",
			planned_end="2026-06-28 09:00:00",
			actual_start="2026-06-28 08:00:00",
			actual_end="2026-06-28 09:00:00",
			fg_qty=100,
			fg_item=self.fg_item,
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Crack", "qty": 5}],
		)
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-06-28",
			planned_start="2026-06-28 10:00:00",
			planned_end="2026-06-28 11:00:00",
			actual_start="2026-06-28 10:00:00",
			actual_end="2026-06-28 11:00:00",
			fg_qty=100,
			fg_item=item_2,
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Burr", "qty": 9}],
		)

		_, rows = execute({"from_date": "2026-06-28", "to_date": "2026-06-28", "fg_item": self.fg_item})
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["item_code"], self.fg_item)
		self.assertEqual(float(rows[0]["rejection_qty"]), 5.0)

	# ── Rejection PPM Report ──────────────────────────────────────────

	def test_rejection_ppm_report_columns(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report import (
			execute,
		)

		columns, _, _, _ = execute({})
		fieldnames = [c["fieldname"] for c in columns]
		self.assertEqual(fieldnames, ["date", "entries", "total_qty", "rejection_qty", "ppm"])

	def test_rejection_ppm_report_data(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-30", "1")
		fg_item = _get_or_create_item(f"_Test FG Item For Rejection PPM {frappe.generate_hash(length=8)}")
		self._create_mock_submitted_entry(
			posting_date="2026-06-30",
			planned_start="2026-06-30 08:00:00",
			planned_end="2026-06-30 09:00:00",
			actual_start="2026-06-30 08:00:00",
			actual_end="2026-06-30 09:00:00",
			fg_qty=100,
			rejection_qty=10,
			shift_name=shift.name,
			fg_item=fg_item,
		)

		_, rows, _, _ = execute({"from_date": "2026-06-30", "to_date": "2026-06-30", "fg_item": fg_item})
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["date"], "2026-06-30")
		self.assertEqual(float(rows[0]["total_qty"]), 100.0)
		self.assertEqual(float(rows[0]["rejection_qty"]), 10.0)
		# PPM = (10 / 100) * 1_000_000 = 100_000
		self.assertEqual(float(rows[0]["ppm"]), 100_000.0)

	def test_rejection_ppm_report_prefers_parent_rejection_field_when_present(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report import (
			_get_rows,
		)

		entry_rows = [
			[
				{
					"name": "MAT-STE-TEST-0001",
					"posting_date": "2026-06-30",
					"fg_completed_qty": 100,
					"custom_pea_rejection_qty": 9,
				}
			]
		]
		with (
			patch(
				"production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report.iter_stock_entries_in_chunks",
				return_value=entry_rows,
			),
			patch(
				"production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report.get_parent_quantity_metrics",
				return_value={"MAT-STE-TEST-0001": {"rejection_qty": 2}},
			),
		):
			rows = _get_rows({"from_date": "2026-06-30", "to_date": "2026-06-30"})

		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["rejection_qty"]), 9.0)
		self.assertEqual(float(rows[0]["ppm"]), 90_000.0)

	def test_rejection_ppm_report_keeps_parent_zero_rejection_qty(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report import (
			_get_rows,
		)

		entry_rows = [
			[
				{
					"name": "MAT-STE-TEST-0002",
					"posting_date": "2026-06-30",
					"fg_completed_qty": 100,
					"custom_pea_rejection_qty": 0,
				}
			]
		]
		with (
			patch(
				"production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report.iter_stock_entries_in_chunks",
				return_value=entry_rows,
			),
			patch(
				"production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report.get_parent_quantity_metrics",
				return_value={"MAT-STE-TEST-0002": {"rejection_qty": 7}},
			),
		):
			rows = _get_rows({"from_date": "2026-06-30", "to_date": "2026-06-30"})

		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["rejection_qty"]), 0.0)
		self.assertEqual(float(rows[0]["ppm"]), 0.0)

	def test_rejection_ppm_report_chart(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-07-03", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-07-03",
			planned_start="2026-07-03 08:00:00",
			planned_end="2026-07-03 09:00:00",
			actual_start="2026-07-03 08:00:00",
			actual_end="2026-07-03 09:00:00",
			fg_qty=200,
			rejection_qty=5,
			shift_name=shift.name,
		)

		_, _, _, chart = execute({"from_date": "2026-07-03", "to_date": "2026-07-03"})
		self.assertIsNotNone(chart)
		self.assertEqual(chart.get("type"), "bar")
		self.assertEqual(chart.get("height"), 280)
		self.assertEqual(chart["data"]["labels"], ["2026-07-03"])
		# PPM = (5 / 200) * 1_000_000 = 25_000
		self.assertEqual(chart["data"]["datasets"][0]["values"], [25_000.0])

	def test_rejection_ppm_report_empty(self) -> None:
		from production_entry_app.production_entry_app.report.rejection_ppm_report.rejection_ppm_report import (
			execute,
		)

		_, rows, _, chart = execute({"from_date": "2099-01-01", "to_date": "2099-01-31"})
		self.assertEqual(rows, [])
		self.assertIsNone(chart)

	def test_rework_pareto_report_counts_only_rework_rows(self) -> None:
		from production_entry_app.production_entry_app.report.rework_pareto_report.rework_pareto_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-07-04", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-07-04",
			planned_start="2026-07-04 08:00:00",
			planned_end="2026-07-04 09:00:00",
			actual_start="2026-07-04 08:00:00",
			actual_end="2026-07-04 09:00:00",
			fg_qty=100,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 5, "is_rework": 1},
				{"rejection_reason": "Burr", "qty": 2, "is_rework": 0},
			],
		)

		_, rows, _, _chart = execute({"from_date": "2026-07-04", "to_date": "2026-07-04"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["rejection_reason"], "Crack")
		self.assertEqual(float(rows[0]["rework_qty"]), 5.0)

	def test_rework_trend_report_returns_rework_and_non_rework_quantities(self) -> None:
		from production_entry_app.production_entry_app.report.rework_trend_report.rework_trend_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-07-05", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-07-05",
			planned_start="2026-07-05 08:00:00",
			planned_end="2026-07-05 09:00:00",
			actual_start="2026-07-05 08:00:00",
			actual_end="2026-07-05 09:00:00",
			fg_qty=100,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 6, "is_rework": 1},
				{"rejection_reason": "Burr", "qty": 4, "is_rework": 0},
			],
		)

		_, rows, _, _chart = execute({"from_date": "2026-07-05", "to_date": "2026-07-05"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["rework_qty"]), 6.0)
		self.assertEqual(float(rows[0]["non_rework_rejection_qty"]), 4.0)
		self.assertEqual(float(rows[0]["rework_rate_pct"]), 6.0)

	def test_rework_ppm_report_data(self) -> None:
		from production_entry_app.production_entry_app.report.rework_ppm_report.rework_ppm_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-07-06", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-07-06",
			planned_start="2026-07-06 08:00:00",
			planned_end="2026-07-06 09:00:00",
			actual_start="2026-07-06 08:00:00",
			actual_end="2026-07-06 09:00:00",
			fg_qty=200,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 5, "is_rework": 1},
				{"rejection_reason": "Burr", "qty": 5, "is_rework": 0},
			],
		)

		_, rows, _, _chart = execute({"from_date": "2026-07-06", "to_date": "2026-07-06"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["rework_qty"]), 5.0)
		self.assertEqual(float(rows[0]["ppm"]), 25_000.0)

	def test_operator_rework_performance_metrics(self) -> None:
		from production_entry_app.production_entry_app.report.operator_rework_performance.operator_rework_performance import (
			execute,
		)

		shift = self._create_shift_for_label("2026-07-07", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-07-07",
			planned_start="2026-07-07 08:00:00",
			planned_end="2026-07-07 09:00:00",
			actual_start="2026-07-07 08:00:00",
			actual_end="2026-07-07 09:00:00",
			fg_qty=120,
			operator="Report Operator",
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 6, "is_rework": 1},
				{"rejection_reason": "Burr", "qty": 2, "is_rework": 0},
			],
		)

		_, rows = execute(
			{
				"from_date": "2026-07-07",
				"to_date": "2026-07-07",
				"custom_pea_operator": "Report Operator",
			}
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["rework_qty"]), 6.0)
		self.assertEqual(float(rows[0]["rework_rate_pct"]), 5.0)
		self.assertIn("Crack (6", rows[0]["top_3_reasons"])

	def test_operator_rework_performance_preserves_raw_rate_and_string_summary_contract(self) -> None:
		from production_entry_app.production_entry_app.report.operator_rework_performance.operator_rework_performance import (
			execute,
		)

		shift = self._create_shift_for_label("2026-07-07", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-07-07",
			planned_start="2026-07-07 12:00:00",
			planned_end="2026-07-07 13:00:00",
			actual_start="2026-07-07 12:00:00",
			actual_end="2026-07-07 13:00:00",
			fg_qty=3,
			operator="Report Operator",
			shift_name=shift.name,
			breakup_rows=[{"rejection_reason": "Crack", "qty": 1, "is_rework": 1}],
		)

		_, rows = execute(
			{
				"from_date": "2026-07-07",
				"to_date": "2026-07-07",
				"custom_pea_operator": "Report Operator",
			}
		)
		self.assertEqual(len(rows), 1)
		derived_abs_tol = 1e-6
		self.assertAlmostEqual(float(rows[0]["rework_rate_pct"]), 100 / 3, delta=derived_abs_tol)
		self.assertIsInstance(rows[0]["top_3_reasons"], str)
		self.assertIn("Crack (1", rows[0]["top_3_reasons"])

	def test_item_bom_rework_hotspots_data(self) -> None:
		from production_entry_app.production_entry_app.report.item_bom_rework_hotspots.item_bom_rework_hotspots import (
			execute,
		)

		shift = self._create_shift_for_label("2026-07-08", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-07-08",
			planned_start="2026-07-08 08:00:00",
			planned_end="2026-07-08 09:00:00",
			actual_start="2026-07-08 08:00:00",
			actual_end="2026-07-08 09:00:00",
			fg_qty=120,
			fg_item=self.fg_item,
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 6, "is_rework": 1},
				{"rejection_reason": "Burr", "qty": 2, "is_rework": 0},
			],
		)

		_, rows = execute({"from_date": "2026-07-08", "to_date": "2026-07-08"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["item_code"], self.fg_item)
		self.assertEqual(float(rows[0]["rework_qty"]), 6.0)
		self.assertIn("Crack (6", rows[0]["dominant_reason"])

	def test_workstation_rework_reason_matrix_aggregates_top_reasons(self) -> None:
		from production_entry_app.production_entry_app.report.workstation_rework_reason_matrix.workstation_rework_reason_matrix import (
			execute,
		)

		shift = self._create_shift_for_label("2026-07-09", "1")
		self._create_mock_submitted_entry_with_breakup(
			posting_date="2026-07-09",
			planned_start="2026-07-09 08:00:00",
			planned_end="2026-07-09 09:00:00",
			actual_start="2026-07-09 08:00:00",
			actual_end="2026-07-09 09:00:00",
			fg_qty=100,
			workstation="Report Workstation",
			shift_name=shift.name,
			breakup_rows=[
				{"rejection_reason": "Crack", "qty": 5, "is_rework": 1},
				{"rejection_reason": "Burr", "qty": 2, "is_rework": 0},
			],
		)

		columns, rows = execute({"from_date": "2026-07-09", "to_date": "2026-07-09", "top_n_reasons": 3})
		self.assertIn("Crack", [col.get("label") for col in columns])
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["total_rework_qty"]), 5.0)
		self.assertEqual(float(rows[0]["reason_crack"]), 5.0)

	def test_workstation_rework_reason_matrix_translates_unassigned_label(self) -> None:
		from production_entry_app.production_entry_app.report.workstation_rework_reason_matrix import (
			workstation_rework_reason_matrix as report,
		)

		with (
			patch.object(
				report,
				"iter_stock_entries_in_chunks",
				return_value=[[{"name": "STE-UNASSIGNED", "custom_pea_workstation": ""}]],
			),
			patch.object(
				report,
				"get_parent_breakup_reason_rows",
				return_value=[
					{"parent": "STE-UNASSIGNED", "rejection_reason": "Crack", "qty": 4},
				],
			),
			patch.object(report, "apply_system_precision", side_effect=lambda columns: columns),
			patch.object(report, "_", side_effect=lambda text: f"translated:{text}"),
		):
			_rows, rows = report.execute({"from_date": "2026-07-10", "to_date": "2026-07-10"})

		self.assertEqual(rows[0]["workstation"], "translated:Unassigned")

	def test_workstation_rework_reason_matrix_uses_legacy_workstation_fallback(self) -> None:
		from production_entry_app.production_entry_app.report.workstation_rework_reason_matrix import (
			workstation_rework_reason_matrix as report,
		)

		with (
			patch.object(
				report,
				"iter_stock_entries_in_chunks",
				return_value=[
					[
						{
							"name": "STE-LEGACY",
							"custom_pea_workstation": "",
							"custom_workstation": "Legacy Workstation",
						},
						{
							"name": "STE-OTHER",
							"custom_pea_workstation": "Other Workstation",
							"custom_workstation": "",
						},
					]
				],
			),
			patch.object(
				report,
				"get_parent_breakup_reason_rows",
				return_value=[{"parent": "STE-LEGACY", "rejection_reason": "Crack", "qty": 4}],
			),
			patch.object(report, "apply_system_precision", side_effect=lambda columns: columns),
		):
			_columns, rows = report.execute({"custom_pea_workstation": "Legacy Workstation"})

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["workstation"], "Legacy Workstation")
		self.assertEqual(float(rows[0]["total_rework_qty"]), 4.0)

	# ── Daily Strokes SPM Monitor ─────────────────────────────────────

	def _ensure_fiscal_year(self, fy_name: str, start_date: str, end_date: str) -> str:
		meta = frappe.get_meta("Fiscal Year", cached=True)
		if frappe.db.exists("Fiscal Year", fy_name):
			if meta.has_field("companies"):
				doc = frappe.get_doc("Fiscal Year", fy_name)
				if not any((row.company or "") == self.company for row in (doc.get("companies") or [])):
					doc.append("companies", {"company": self.company})
					doc.flags.ignore_validate_update_after_submit = True
					doc.save(ignore_permissions=True)
			return fy_name

		covering_fiscal_year = frappe.get_all(
			"Fiscal Year",
			filters=[
				["year_start_date", "<=", start_date],
				["year_end_date", ">=", end_date],
			],
			pluck="name",
			limit=1,
		)
		if covering_fiscal_year:
			doc = frappe.get_doc("Fiscal Year", covering_fiscal_year[0])
			if meta.has_field("companies") and not any(
				(row.company or "") == self.company for row in (doc.get("companies") or [])
			):
				doc.append("companies", {"company": self.company})
				doc.flags.ignore_validate_update_after_submit = True
				doc.save(ignore_permissions=True)
			return doc.name

		payload = {
			"doctype": "Fiscal Year",
			"year": fy_name,
			"year_start_date": start_date,
			"year_end_date": end_date,
		}
		if meta.has_field("companies"):
			payload["companies"] = [{"company": self.company}]
		doc = frappe.get_doc(payload).insert(ignore_permissions=True)
		return doc.name

	def test_daily_strokes_spm_monitor_columns_without_operator(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		fiscal_year = self._ensure_fiscal_year("2090-2091", "2090-04-01", "2091-03-31")
		columns, _ = execute({"fiscal_year": fiscal_year, "month": "April"})
		fieldnames = [c["fieldname"] for c in columns]
		self.assertIn("operator", fieldnames)
		self.assertEqual(
			fieldnames,
			[
				"date",
				"operator",
				"setup_time_hrs",
				"loss_time_hrs",
				"prod_time_hrs",
				"total_strokes",
				"spm",
				"rejection",
				"rework",
			],
		)

	def test_daily_strokes_spm_monitor_columns_with_operator(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		fiscal_year = self._ensure_fiscal_year("2090-2091", "2090-04-01", "2091-03-31")
		columns, _ = execute(
			{"fiscal_year": fiscal_year, "month": "April", "custom_pea_operator": "Report Operator"}
		)
		fieldnames = [c["fieldname"] for c in columns]
		self.assertNotIn("operator", fieldnames)
		self.assertEqual(
			fieldnames,
			[
				"date",
				"setup_time_hrs",
				"loss_time_hrs",
				"prod_time_hrs",
				"total_strokes",
				"spm",
				"rejection",
				"rework",
			],
		)

	def test_daily_strokes_spm_monitor_data(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		fiscal_year = self._ensure_fiscal_year("2080-2081", "2080-04-01", "2081-03-31")
		shift = self._create_shift_for_label("2080-05-10", "1")
		# actual_duration = 60 mins = 1 hour; fg_qty=100, rejection_qty=10
		# After rejection hook: FG row=90, rejection row=10 → good_qty_map=90
		# total_strokes = 90 + 10 = 100; production_time = 1 - 0.5 - 0.25 = 0.25 h
		# SPM = 100 / (0.25 * 60) ~= 6.667
		self._create_mock_submitted_entry(
			posting_date="2080-05-10",
			planned_start="2080-05-10 08:00:00",
			planned_end="2080-05-10 09:00:00",
			actual_start="2080-05-10 08:00:00",
			actual_end="2080-05-10 09:00:00",
			fg_qty=100,
			rejection_qty=10,
			shift_name=shift.name,
			unplanned_losses=[
				{
					"downtime_reason": "Setup Time",
					"start_time": "08:00:00",
					"end_time": "08:30:00",
					"remark": "setup",
				},
				{
					"downtime_reason": "Maint",
					"start_time": "08:30:00",
					"end_time": "08:45:00",
					"remark": "maint",
				},
			],
		)

		_, rows = execute(
			{"fiscal_year": fiscal_year, "month": "May", "custom_pea_operator": "Report Operator"}
		)
		# Should have 1 data row + 1 totals row
		self.assertEqual(len(rows), 2)
		data_row = rows[0]
		self.assertEqual(data_row["date"], "2080-05-10")
		# setup = 30 mins = 0.5 hrs
		self.assertAlmostEqual(float(data_row["setup_time_hrs"]), 0.5, places=2)
		# loss = 15 mins = 0.25 hrs
		self.assertAlmostEqual(float(data_row["loss_time_hrs"]), 0.25, places=2)
		# prod_time = (60 - 30 - 15) / 60 = 0.25
		self.assertAlmostEqual(float(data_row["prod_time_hrs"]), 0.25, places=2)
		# total_strokes = good_qty(90) + rejection(10) = 100
		self.assertAlmostEqual(float(data_row["total_strokes"]), 100.0, places=2)
		expected_spm = 100 / (0.25 * 60)
		derived_abs_tol = 1e-6
		self.assertAlmostEqual(float(data_row["spm"]), expected_spm, delta=derived_abs_tol)
		self.assertAlmostEqual(float(data_row["rejection"]), 10.0, places=2)
		self.assertAlmostEqual(float(data_row["rework"]), 0.0, places=2)

	def test_daily_strokes_spm_monitor_preserves_raw_group_values(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		fiscal_year = self._ensure_fiscal_year("2082-2083", "2082-04-01", "2083-03-31")
		shift = self._create_shift_for_label("2082-05-11", "1")
		self._create_mock_submitted_entry(
			posting_date="2082-05-11",
			planned_start="2082-05-11 08:00:00",
			planned_end="2082-05-11 08:01:00",
			actual_start="2082-05-11 08:00:00",
			actual_end="2082-05-11 08:01:00",
			fg_qty=1,
			rejection_qty=0,
			shift_name=shift.name,
			unplanned_losses=[
				{
					"downtime_reason": "Setup Time",
					"start_time": "08:00:00",
					"end_time": "08:00:20",
				},
				{
					"downtime_reason": "Maint",
					"start_time": "08:00:20",
					"end_time": "08:00:40",
				},
			],
		)

		_, rows = execute(
			{"fiscal_year": fiscal_year, "month": "May", "custom_pea_operator": "Report Operator"}
		)
		self.assertEqual(len(rows), 2)
		data_row = rows[0]
		expected_setup = 20 / 3600
		expected_loss = 20 / 3600
		expected_prod = 20 / 3600
		expected_spm = 1 / ((20 / 3600) * 60)
		derived_abs_tol = 1e-6
		self.assertAlmostEqual(float(data_row["setup_time_hrs"]), expected_setup, delta=derived_abs_tol)
		self.assertAlmostEqual(float(data_row["loss_time_hrs"]), expected_loss, delta=derived_abs_tol)
		self.assertAlmostEqual(float(data_row["prod_time_hrs"]), expected_prod, delta=derived_abs_tol)
		self.assertAlmostEqual(float(data_row["spm"]), expected_spm, delta=derived_abs_tol)

	def test_daily_strokes_spm_monitor_totals_row(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		fiscal_year = self._ensure_fiscal_year("2081-2082", "2081-04-01", "2082-03-31")
		shift1 = self._create_shift_for_label("2081-06-01", "1")
		shift2 = self._create_shift_for_label("2081-06-02", "1")
		self._create_mock_submitted_entry(
			posting_date="2081-06-01",
			planned_start="2081-06-01 08:00:00",
			planned_end="2081-06-01 09:00:00",
			actual_start="2081-06-01 08:00:00",
			actual_end="2081-06-01 09:00:00",
			fg_qty=100,
			rejection_qty=10,
			shift_name=shift1.name,
		)
		self._create_mock_submitted_entry(
			posting_date="2081-06-02",
			planned_start="2081-06-02 08:00:00",
			planned_end="2081-06-02 09:00:00",
			actual_start="2081-06-02 08:00:00",
			actual_end="2081-06-02 09:00:00",
			fg_qty=200,
			rejection_qty=20,
			shift_name=shift2.name,
		)

		_, rows = execute(
			{"fiscal_year": fiscal_year, "month": "June", "custom_pea_operator": "Report Operator"}
		)
		# 2 data rows + 1 totals
		self.assertEqual(len(rows), 3)
		totals = rows[-1]
		# Entry 1: good=90, rej=10 → total=100; Entry 2: good=180, rej=20 → total=200
		self.assertAlmostEqual(float(totals["total_strokes"]), 300.0, places=2)
		self.assertAlmostEqual(float(totals["rejection"]), 30.0, places=2)
		self.assertAlmostEqual(float(totals["rework"]), 0.0, places=2)
		self.assertAlmostEqual(float(totals["prod_time_hrs"]), 100 / 60, places=2)
		# Only Shift Start Up (10 min) overlaps each 08:00-09:00 entry; JH Activity (10:00) is outside.
		self.assertAlmostEqual(float(totals["spm"]), 3.0, places=2)

	def test_daily_strokes_spm_monitor_empty(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		fiscal_year = self._ensure_fiscal_year("2079", "2079-01-01", "2079-12-31")
		_, rows = execute({"fiscal_year": fiscal_year, "month": "April"})
		self.assertEqual(rows, [])

	def test_daily_strokes_spm_monitor_throws_for_invalid_fiscal_year(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		with self.assertRaises(frappe.ValidationError) as exc:
			execute({"fiscal_year": "DOES-NOT-EXIST", "month": "April"})
		self.assertIn("Fiscal Year", str(exc.exception))
		self.assertIn("not found", str(exc.exception))

	def test_daily_strokes_spm_monitor_throws_when_fiscal_year_dates_missing(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		with patch(
			"production_entry_app.production_entry_app.report.daily_strokes_spm_monitor."
			"daily_strokes_spm_monitor.frappe.db.get_value",
			return_value={"year_start_date": None, "year_end_date": None},
		):
			with self.assertRaises(frappe.ValidationError) as exc:
				execute({"fiscal_year": "2090-2091", "month": "April"})
		self.assertIn("Fiscal Year", str(exc.exception))
		self.assertIn("not found", str(exc.exception))

	def test_daily_strokes_spm_monitor_date_range_supports_jan_dec_fiscal_year(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		fiscal_year = self._ensure_fiscal_year("2092", "2092-01-01", "2092-12-31")
		shift = self._create_shift_for_label("2092-01-10", "1")
		self._create_mock_submitted_entry(
			posting_date="2092-01-10",
			planned_start="2092-01-10 08:00:00",
			planned_end="2092-01-10 09:00:00",
			actual_start="2092-01-10 08:00:00",
			actual_end="2092-01-10 09:00:00",
			fg_qty=50,
			rejection_qty=5,
			shift_name=shift.name,
		)

		_, rows = execute(
			{"fiscal_year": fiscal_year, "month": "January", "custom_pea_operator": "Report Operator"}
		)
		self.assertEqual(rows[0]["date"], "2092-01-10")

	def test_daily_strokes_spm_monitor_date_range_supports_non_april_cross_year_fiscal_year(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		fiscal_year = self._ensure_fiscal_year("2092-2093", "2092-10-01", "2093-09-30")
		shift = self._create_shift_for_label("2093-09-15", "1")
		self._create_mock_submitted_entry(
			posting_date="2093-09-15",
			planned_start="2093-09-15 08:00:00",
			planned_end="2093-09-15 09:00:00",
			actual_start="2093-09-15 08:00:00",
			actual_end="2093-09-15 09:00:00",
			fg_qty=60,
			rejection_qty=6,
			shift_name=shift.name,
		)

		_, rows = execute(
			{"fiscal_year": fiscal_year, "month": "September", "custom_pea_operator": "Report Operator"}
		)
		self.assertEqual(rows[0]["date"], "2093-09-15")

	def test_operator_daily_spm_report_columns(self) -> None:
		from production_entry_app.production_entry_app.report.operator_daily_spm_report.operator_daily_spm_report import (
			execute,
		)

		columns, _rows = execute({"from_date": "2026-08-01", "to_date": "2026-08-01"})
		fieldnames = [column.get("fieldname") for column in columns]
		self.assertEqual(
			fieldnames,
			[
				"date",
				"operator",
				"workstation",
				"working_hours",
				"setting_time_hrs",
				"loss_time_hrs",
				"production_time_hrs",
				"total_strokes",
				"spm",
			],
		)

	def test_operator_daily_spm_report_empty(self) -> None:
		from production_entry_app.production_entry_app.report.operator_daily_spm_report.operator_daily_spm_report import (
			execute,
		)

		_, rows = execute({"from_date": "2026-08-01", "to_date": "2026-08-01"})
		self.assertEqual(rows, [])

	def test_operator_daily_spm_report_basic_data(self) -> None:
		from production_entry_app.production_entry_app.report.operator_daily_spm_report.operator_daily_spm_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-08-02", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-08-02",
			planned_start="2026-08-02 08:00:00",
			planned_end="2026-08-02 12:00:00",
			actual_start="2026-08-02 08:00:00",
			actual_end="2026-08-02 12:00:00",
			fg_qty=100,
			rejection_qty=10,
			shift_name=shift.name,
			unplanned_losses=[
				{
					"downtime_reason": "Setup Time",
					"start_time": "08:00:00",
					"end_time": "08:30:00",
					"remark": "setup",
				},
				{
					"downtime_reason": "Maint",
					"start_time": "09:00:00",
					"end_time": "10:00:00",
					"remark": "maint",
				},
			],
		)

		_, rows = execute({"from_date": "2026-08-02", "to_date": "2026-08-02"})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row["date"], "2026-08-02")
		self.assertEqual(row["operator"], "Report Operator")
		self.assertEqual(row["workstation"], "Report Workstation")
		self.assertAlmostEqual(float(row["working_hours"]), 8.0, places=3)
		self.assertAlmostEqual(float(row["setting_time_hrs"]), 0.5, places=3)
		self.assertAlmostEqual(float(row["loss_time_hrs"]), 1.0, places=3)
		# 240 min - 100 min deducted (setup 30 + maint 60 + JH Activity 10) = 140 min
		self.assertAlmostEqual(float(row["production_time_hrs"]), 140 / 60, places=3)
		self.assertAlmostEqual(float(row["total_strokes"]), 100.0, places=3)
		expected_spm = 100 / (140 / 60 * 60)
		derived_abs_tol = 1e-6
		self.assertAlmostEqual(float(row["spm"]), expected_spm, delta=derived_abs_tol)

	def test_operator_daily_spm_report_preserves_raw_group_values(self) -> None:
		from production_entry_app.production_entry_app.report.operator_daily_spm_report.operator_daily_spm_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-08-05", "1", clear_planned_losses=True)
		self._create_mock_submitted_entry(
			posting_date="2026-08-05",
			planned_start="2026-08-05 08:00:00",
			planned_end="2026-08-05 08:01:00",
			actual_start="2026-08-05 08:00:00",
			actual_end="2026-08-05 08:01:00",
			fg_qty=1,
			rejection_qty=0,
			shift_name=shift.name,
			unplanned_losses=[
				{"downtime_reason": "Setup Time", "start_time": "08:00:00", "end_time": "08:00:20"},
				{"downtime_reason": "Maint", "start_time": "08:00:20", "end_time": "08:00:40"},
			],
		)

		_, rows = execute({"from_date": "2026-08-05", "to_date": "2026-08-05"})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		expected_setup = 20 / 3600
		expected_loss = 20 / 3600
		expected_prod = 20 / 3600
		expected_spm = 1 / ((20 / 3600) * 60)
		derived_abs_tol = 1e-6
		self.assertAlmostEqual(float(row["setting_time_hrs"]), expected_setup, delta=derived_abs_tol)
		self.assertAlmostEqual(float(row["loss_time_hrs"]), expected_loss, delta=derived_abs_tol)
		self.assertAlmostEqual(float(row["production_time_hrs"]), expected_prod, delta=derived_abs_tol)
		self.assertAlmostEqual(float(row["spm"]), expected_spm, delta=derived_abs_tol)

	def test_operator_daily_spm_report_multiple_workstations_same_day(self) -> None:
		from production_entry_app.production_entry_app.report.operator_daily_spm_report.operator_daily_spm_report import (
			execute,
		)

		if not frappe.db.exists("Workstation", "Report Workstation 2"):
			frappe.get_doc(
				{
					"doctype": "Workstation",
					"workstation_name": "Report Workstation 2",
					"production_capacity": 1,
					"hour_rate": 100,
					"custom_pea_standard_spm": 2,
				}
			).insert(ignore_permissions=True)

		shift_1 = self._create_shift_for_label("2026-08-03", "1")
		shift_2 = self._create_shift_for_label("2026-08-03", "2")
		self._create_mock_submitted_entry(
			posting_date="2026-08-03",
			planned_start="2026-08-03 08:00:00",
			planned_end="2026-08-03 09:00:00",
			actual_start="2026-08-03 08:00:00",
			actual_end="2026-08-03 09:00:00",
			fg_qty=100,
			rejection_qty=0,
			workstation="Report Workstation",
			shift_name=shift_1.name,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-08-03",
			planned_start="2026-08-03 16:00:00",
			planned_end="2026-08-03 17:00:00",
			actual_start="2026-08-03 16:00:00",
			actual_end="2026-08-03 17:00:00",
			fg_qty=120,
			rejection_qty=0,
			workstation="Report Workstation 2",
			shift_name=shift_2.name,
		)

		_, rows = execute({"from_date": "2026-08-03", "to_date": "2026-08-03"})
		self.assertEqual(len(rows), 2)
		self.assertEqual(
			{row["workstation"] for row in rows},
			{"Report Workstation", "Report Workstation 2"},
		)
		self.assertTrue(all(float(row["working_hours"]) == 8.0 for row in rows))

	def test_operator_daily_spm_report_sums_non_contiguous_entry_durations(self) -> None:
		from production_entry_app.production_entry_app.report.operator_daily_spm_report.operator_daily_spm_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-08-04", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-08-04",
			planned_start="2026-08-04 08:00:00",
			planned_end="2026-08-04 09:00:00",
			actual_start="2026-08-04 08:00:00",
			actual_end="2026-08-04 09:00:00",
			fg_qty=100,
			rejection_qty=0,
			shift_name=shift.name,
		)
		self._create_mock_submitted_entry(
			posting_date="2026-08-04",
			planned_start="2026-08-04 16:00:00",
			planned_end="2026-08-04 17:00:00",
			actual_start="2026-08-04 16:00:00",
			actual_end="2026-08-04 17:00:00",
			fg_qty=100,
			rejection_qty=0,
			shift_name=shift.name,
		)

		_, rows = execute({"from_date": "2026-08-04", "to_date": "2026-08-04"})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		# Sum per-entry durations and deduct planned losses where overlapped.
		# Only Shift Start Up (08:00-08:10) overlaps; JH Activity (10:00) is outside both entries.
		expected_production_time_hrs = 110 / 60
		derived_abs_tol = 1e-6
		self.assertAlmostEqual(
			float(row["production_time_hrs"]), expected_production_time_hrs, delta=derived_abs_tol
		)
		self.assertAlmostEqual(float(row["total_strokes"]), 200.0, places=3)
		expected_spm = 200 / (expected_production_time_hrs * 60)
		self.assertAlmostEqual(float(row["spm"]), expected_spm, delta=derived_abs_tol)

	def test_operator_daily_spm_report_working_hours_change_after_running_shift_extension(self) -> None:
		"""Extending a Running shift's duration changes the working_hours denominator in the operator report."""
		from production_entry_app.production_entry_app.report.operator_daily_spm_report.operator_daily_spm_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-08-06", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-08-06",
			planned_start="2026-08-06 08:00:00",
			planned_end="2026-08-06 12:00:00",
			actual_start="2026-08-06 08:00:00",
			actual_end="2026-08-06 12:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift.name,
		)

		_, rows = execute({"from_date": "2026-08-06", "to_date": "2026-08-06"})
		self.assertEqual(len(rows), 1)
		initial_working_hours = float(rows[0]["working_hours"])

		running_doc = frappe.get_doc("Shift", shift.name)
		running_doc.shift_duration = "10"
		running_doc.flags.ignore_links = True
		running_doc.save()
		running_doc.reload()

		_, rows = execute({"from_date": "2026-08-06", "to_date": "2026-08-06"})
		self.assertEqual(len(rows), 1)
		extended_working_hours = float(rows[0]["working_hours"])

		self.assertNotEqual(
			initial_working_hours, extended_working_hours, "Working hours must change after shift extension"
		)
		self.assertGreater(
			extended_working_hours, initial_working_hours, "Extended shift should have more working hours"
		)

	def _create_mock_submitted_entry(
		self,
		posting_date: str,
		planned_start: str,
		planned_end: str,
		actual_start: str,
		actual_end: str,
		fg_qty: float,
		rejection_qty: float,
		standard_spm: float = 2,
		fg_item: str | None = None,
		operator: str | None = "Report Operator",
		workstation: str | None = "Report Workstation",
		shift_name: str | None = None,
		unplanned_losses: list[dict] | None = None,
	):
		entry_fg_item = fg_item or self.fg_item
		stock_entry = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=entry_fg_item,
			rm_item=self.rm_item,
			fg_qty=fg_qty,
			rm_qty=fg_qty,
			custom_pea_rejection_qty=rejection_qty,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		stock_entry.custom_pea_operator = operator
		stock_entry.custom_pea_workstation = workstation
		stock_entry.custom_pea_shift = shift_name
		stock_entry.custom_pea_standard_spm = standard_spm
		stock_entry.custom_pea_planned_start_date = planned_start
		stock_entry.custom_pea_planned_end_date = planned_end
		stock_entry.custom_pea_actual_start_date = actual_start
		stock_entry.custom_pea_actual_end_date = actual_end
		stock_entry.posting_date = posting_date
		stock_entry.posting_time = "09:00:00"

		if rejection_qty > 0:
			_append_rejection_breakup_rows(
				stock_entry,
				[{"rejection_reason": "Burr", "qty": rejection_qty, "remark": "Report test"}],
			)
		for row in unplanned_losses or []:
			stock_entry.append(
				"custom_pea_unplanned_losses",
				{
					"downtime_reason": row.get("downtime_reason"),
					"start_time": row.get("start_time"),
					"end_time": row.get("end_time"),
					"remark": row.get("remark"),
					"shift": shift_name,
				},
			)

		self._save_with_deadlock_retry(stock_entry)
		frappe.db.set_value(
			"Stock Entry", stock_entry.name, "posting_date", posting_date, update_modified=False
		)
		# Intentionally mark submitted in DB for report isolation; these tests
		# validate query/report logic, not full stock-entry submit side effects.
		frappe.db.set_value("Stock Entry", stock_entry.name, "docstatus", 1, update_modified=False)
		stock_entry.reload()
		return stock_entry

	def _create_mock_submitted_entry_with_breakup(
		self,
		*,
		posting_date: str,
		planned_start: str,
		planned_end: str,
		actual_start: str,
		actual_end: str,
		fg_qty: float,
		breakup_rows: list[dict],
		fg_item: str | None = None,
		operator: str | None = "Report Operator",
		workstation: str | None = "Report Workstation",
		shift_name: str | None = None,
	):
		rejection_qty = sum(float(row.get("qty") or 0) for row in breakup_rows)
		stock_entry = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=fg_item or self.fg_item,
			rm_item=self.rm_item,
			fg_qty=fg_qty,
			rm_qty=fg_qty,
			custom_pea_rejection_qty=rejection_qty,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		stock_entry.custom_pea_operator = operator
		stock_entry.custom_pea_workstation = workstation
		stock_entry.custom_pea_shift = shift_name
		stock_entry.custom_pea_standard_spm = 2
		stock_entry.custom_pea_planned_start_date = planned_start
		stock_entry.custom_pea_planned_end_date = planned_end
		stock_entry.custom_pea_actual_start_date = actual_start
		stock_entry.custom_pea_actual_end_date = actual_end
		stock_entry.posting_date = posting_date
		stock_entry.posting_time = "09:00:00"
		_append_rejection_breakup_rows(stock_entry, breakup_rows)
		self._save_with_deadlock_retry(stock_entry)
		frappe.db.set_value(
			"Stock Entry", stock_entry.name, "posting_date", posting_date, update_modified=False
		)
		# Intentionally mark submitted in DB for report isolation; these tests
		# validate query/report logic, not full stock-entry submit side effects.
		frappe.db.set_value("Stock Entry", stock_entry.name, "docstatus", 1, update_modified=False)
		stock_entry.reload()
		return stock_entry

	def _save_with_deadlock_retry(self, stock_entry: frappe.Document) -> None:
		for attempt in range(5):
			try:
				stock_entry.save()
				return
			except frappe.QueryDeadlockError:
				if attempt == 4:
					raise
				frappe.db.rollback()
				# Deadlock retries need a tiny backoff to avoid immediate lock contention.
				time.sleep(0.1)

	def _create_shift_for_label(
		self, shift_date: str, shift_label: str, clear_planned_losses: bool = False
	) -> frappe.Document:
		from production_entry_app.production_entry_app.utils.test_bootstrap import ensure_department

		department = ensure_department("Test Department")
		for existing_name in frappe.get_all(
			"Shift",
			filters={"department": department, "shift_date": shift_date, "shift_label": shift_label},
			pluck="name",
		):
			frappe.delete_doc("Shift", existing_name, force=True, ignore_permissions=True)
		shift = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": department,
				"shift_label": shift_label,
				"shift_duration": "8",
				"shift_date": shift_date,
				"planned_start_time": "08:00:00" if shift_label == "1" else "16:00:00",
				"rejection_warehouse": self.rejection_warehouse,
			}
		).insert(ignore_permissions=True)
		if clear_planned_losses:
			frappe.db.delete("Loss Entry", {"parenttype": "Shift", "parent": shift.name})
		# Report tests link Stock Entries to these shifts; keep them Running so
		# stock-entry validation matches production constraints.
		frappe.db.set_value("Shift", shift.name, "status", "Running", update_modified=False)
		shift.reload()
		return shift

	def _create_downtime_entry(
		self,
		*,
		workstation: str,
		from_time: str,
		to_time: str,
		shift_name: str,
		stop_reason: str,
	) -> str:
		operator = frappe.db.get_value("Employee", {"employee_number": "REPORT-EMP"}, "name")
		if not operator:
			operator = (
				frappe.get_doc(
					{
						"doctype": "Employee",
						"first_name": "Report",
						"last_name": "E2E",
						"gender": "Female",
						"date_of_birth": "1990-01-01",
						"date_of_joining": "2020-01-01",
						"company": self.company,
						"status": "Active",
						"employee_number": "REPORT-EMP",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		return (
			frappe.get_doc(
				{
					"doctype": "Downtime Entry",
					"workstation": workstation,
					"operator": operator,
					"from_time": from_time,
					"to_time": to_time,
					"custom_pea_shift": shift_name,
					"stop_reason": stop_reason,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)


def _ensure_user_with_exact_roles(email: str, roles: tuple[str, ...]) -> None:
	for role in roles:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = email.split("@", 1)[0]
		user.user_type = "System User"
	user.set("roles", [])
	for role in roles:
		user.append("roles", {"role": role})
	save_test_user(user)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - role changes must be visible to permission checks
	frappe.clear_cache(user=email)
