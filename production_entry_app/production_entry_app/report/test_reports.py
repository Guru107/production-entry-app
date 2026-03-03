from __future__ import annotations

from unittest.mock import patch

import frappe
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
)


class TestProductionReports(FrappeTestCase):
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
					"custom_standard_spm": 2,
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
		frappe.db.set_value("Workstation", "Report Workstation", "custom_standard_spm", 2)
		_set_shift_buffers(start_mins=60, end_mins=60)

	def test_production_oee_report_columns_match_v2_schema(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		columns, _rows = execute({})
		fieldnames = [column.get("fieldname") for column in columns]
		self.assertEqual(
			fieldnames[0:18],
			[
				"day",
				"workstation",
				"stroke_required",
				"first_shift_strokes",
				"second_shift_strokes",
				"total_strokes",
				"rejection",
				"rework",
				"std_spm",
				"act_spm",
				"productivity_pct",
				"quality_pct",
				"availability_pct",
				"oee_avg_pct",
				"oee_mult_pct",
				"avl_hrs",
				"total_loss_time",
				"running_time",
			],
		)
		self.assertIn("setup_1st", fieldnames)
		self.assertIn("setup_2nd", fieldnames)
		self.assertIn("p_maint_1st", fieldnames)
		self.assertIn("p_maint_2nd", fieldnames)

	def test_production_oee_report_metrics(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-01", "1")
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

		_, rows = execute({"from_date": "2026-06-01", "to_date": "2026-06-01", "avl_hours_per_day": 24})
		self.assertEqual(len(rows), 1)
		self.assertEqual(str(rows[0]["day"]), "2026-06-01")
		self.assertEqual(float(rows[0]["availability_pct"]), 100.0)
		self.assertAlmostEqual(float(rows[0]["productivity_pct"]), 4.17, delta=0.05)
		self.assertEqual(float(rows[0]["quality_pct"]), 100.0)
		self.assertAlmostEqual(float(rows[0]["oee_mult_pct"]), 4.17, delta=0.05)
		self.assertEqual(float(rows[0]["first_shift_strokes"]), 120.0)
		self.assertEqual(float(rows[0]["second_shift_strokes"]), 0.0)
		self.assertEqual(float(rows[0]["running_time"]), 24.0)

	def test_production_oee_report_aggregates_by_day_and_workstation(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-01", "1")
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
		_, rows = execute({"from_date": "2026-06-01", "to_date": "2026-06-01", "avl_hours_per_day": 24})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["total_strokes"]), 180.0)
		self.assertEqual(float(rows[0]["rejection"]), 5.0)
		self.assertEqual(float(rows[0]["first_shift_strokes"]), 180.0)

	def test_production_oee_report_shift_split_and_loss_bucket_mapping(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift_1 = self._create_shift_for_label("2026-06-02", "1")
		shift_2 = self._create_shift_for_label("2026-06-02", "2")
		self._create_mock_submitted_entry(
			posting_date="2026-06-02",
			planned_start="2026-06-02 08:00:00",
			planned_end="2026-06-02 09:00:00",
			actual_start="2026-06-02 08:00:00",
			actual_end="2026-06-02 09:00:00",
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
			planned_end="2026-06-02 17:00:00",
			actual_start="2026-06-02 16:00:00",
			actual_end="2026-06-02 17:00:00",
			fg_qty=80,
			rejection_qty=10,
			shift_name=shift_2.name,
			unplanned_losses=[
				{"downtime_reason": "P. Maint", "start_time": "18:00:00", "end_time": "19:00:00"}
			],
		)
		_, rows = execute({"from_date": "2026-06-02", "to_date": "2026-06-02", "avl_hours_per_day": 24})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(float(row["first_shift_strokes"]), 100.0)
		self.assertEqual(float(row["second_shift_strokes"]), 80.0)
		self.assertEqual(float(row["setup_1st"]), 0.5)
		self.assertEqual(float(row["p_maint_2nd"]), 1.0)
		self.assertEqual(float(row["total_loss_time"]), 1.5)

	def test_production_oee_report_counts_cross_midnight_loss_for_second_shift(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift_2 = self._create_shift_for_label("2026-06-09", "2")
		self._create_mock_submitted_entry(
			posting_date="2026-06-09",
			planned_start="2026-06-09 16:00:00",
			planned_end="2026-06-09 23:00:00",
			actual_start="2026-06-09 16:00:00",
			actual_end="2026-06-09 23:00:00",
			fg_qty=100,
			rejection_qty=0,
			shift_name=shift_2.name,
			unplanned_losses=[{"downtime_reason": "Other", "start_time": "23:30:00", "end_time": "00:30:00"}],
		)

		_, rows = execute({"from_date": "2026-06-09", "to_date": "2026-06-09", "avl_hours_per_day": 24})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(float(row["other_2nd"]), 1.0)
		self.assertEqual(float(row["total_loss_time"]), 1.0)

	def test_production_oee_report_ignores_unmapped_loss_reasons(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-07", "1")
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
			planned_end="2026-06-07 09:00:00",
			actual_start="2026-06-07 08:00:00",
			actual_end="2026-06-07 09:00:00",
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

		_, rows = execute({"from_date": "2026-06-07", "to_date": "2026-06-07", "avl_hours_per_day": 24})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(float(row["setup_1st"]), 0.0)
		self.assertEqual(float(row["total_loss_time"]), 0.0)

	def test_production_oee_report_does_not_use_downtime_entry_for_losses(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-08", "1")
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

		_, rows = execute({"from_date": "2026-06-08", "to_date": "2026-06-08", "avl_hours_per_day": 24})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(float(row["other_1st"]), 0.0)
		self.assertEqual(float(row["total_loss_time"]), 0.0)

	def test_production_oee_report_availability_uses_filter_hours(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-03", "1")
		self._create_mock_submitted_entry(
			posting_date="2026-06-03",
			planned_start="2026-06-03 08:00:00",
			planned_end="2026-06-03 09:00:00",
			actual_start="2026-06-03 08:00:00",
			actual_end="2026-06-03 09:00:00",
			fg_qty=120,
			rejection_qty=0,
			shift_name=shift.name,
			unplanned_losses=[{"downtime_reason": "Other", "start_time": "12:00:00", "end_time": "14:00:00"}],
		)

		_, rows_24 = execute({"from_date": "2026-06-03", "to_date": "2026-06-03", "avl_hours_per_day": 24})
		_, rows_8 = execute({"from_date": "2026-06-03", "to_date": "2026-06-03", "avl_hours_per_day": 8})
		self.assertEqual(len(rows_24), 1)
		self.assertEqual(len(rows_8), 1)
		self.assertEqual(float(rows_24[0]["availability_pct"]), 91.67)
		self.assertEqual(float(rows_8[0]["availability_pct"]), 75.0)

	def test_production_oee_report_zero_duration_has_zero_std_and_productivity(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		shift = self._create_shift_for_label("2026-06-04", "1")
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
		_, rows = execute({"from_date": "2026-06-04", "to_date": "2026-06-04", "avl_hours_per_day": 24})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["std_spm"]), 0.0)
		self.assertEqual(float(rows[0]["productivity_pct"]), 0.0)

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

	def test_operator_efficiency_report_uses_duration_weighted_spm(self) -> None:
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			execute,
		)

		frappe.db.set_value("Workstation", "Report Workstation", "custom_standard_spm", 4)

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
		frappe.db.set_value("Workstation", "Report Workstation", "custom_standard_spm", 3)
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

	def test_aggregate_efficiency_ignores_raw_duration_when_production_time_is_zero(self) -> None:
		from production_entry_app.production_entry_app.report.report_utils import (
			aggregate_efficiency_by_field,
			build_efficiency_rows,
		)

		entries = [
			{
				"custom_operator": "Report Operator",
				"_good_qty": 0,
				"_rejection_qty": 0,
				"_rework_qty": 0,
				"_production_time_mins": 0,
				"_duration_mins": 60,
				"custom_standard_spm": 2,
				"custom_actual_spm": 0,
			},
			{
				"custom_operator": "Report Operator",
				"_good_qty": 60,
				"_rejection_qty": 0,
				"_rework_qty": 0,
				"_production_time_mins": 30,
				"_duration_mins": 30,
				"custom_standard_spm": 2,
				"custom_actual_spm": 2,
			},
		]

		aggregates = aggregate_efficiency_by_field(entries, "custom_operator")
		self.assertEqual(flt(aggregates["Report Operator"]["duration_mins"]), 30.0)

		rows = build_efficiency_rows(aggregates, "operator", "operator_efficiency_pct")
		self.assertEqual(len(rows), 1)
		self.assertAlmostEqual(float(rows[0]["actual_spm"]), 2.0, places=3)

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
		self._ensure_fiscal_year("2094", "2094-01-01", "2094-12-31")
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
			{"fiscal_year": "2094", "month": "June", "custom_operator": "Report Operator"}
		)

		self.assertIn("rework_qty", [c.get("fieldname") for c in operator_columns])
		self.assertIn("rework_qty", [c.get("fieldname") for c in workstation_columns])
		self.assertIn("rework", [c.get("fieldname") for c in daily_columns])
		self.assertEqual(float(operator_rows[0]["rework_qty"]), 3.0)
		self.assertEqual(float(workstation_rows[0]["rework_qty"]), 3.0)
		self.assertEqual(float(oee_rows[0]["rework"]), 3.0)
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
					"custom_standard_spm": 2,
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
				"custom_workstation": "Report Workstation",
			}
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["rejection_reason"], "Crack")
		self.assertEqual(float(rows[0]["rejection_qty"]), 5.0)

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
		self._create_mock_submitted_entry(
			posting_date="2026-06-29",
			planned_start="2026-06-29 08:00:00",
			planned_end="2026-06-29 09:00:00",
			actual_start="2026-06-29 08:00:00",
			actual_end="2026-06-29 09:00:00",
			fg_qty=100,
			rejection_qty=10,
			shift_name=shift_june.name,
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
		)

		_, rows, _, _chart = execute(
			{"from_date": "2026-06-01", "to_date": "2026-07-31", "time_grain": "Monthly"}
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
					"custom_standard_spm": 2,
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
				"custom_operator": "Report Operator",
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
		self.assertIn("Crack (6.0)", row_by_operator["Report Operator"]["top_3_reasons"])
		self.assertIn("Burr (2.0)", row_by_operator["Report Operator"]["top_3_reasons"])
		self.assertEqual(float(row_by_operator[operator_2]["rejection_rate_pct"]), 5.0)

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
					"custom_standard_spm": 2,
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
				"custom_workstation": workstation_2,
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
		self.assertIn("Crack (6.0)", rows[0]["dominant_reason"])
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
		self._create_mock_submitted_entry(
			posting_date="2026-06-30",
			planned_start="2026-06-30 08:00:00",
			planned_end="2026-06-30 09:00:00",
			actual_start="2026-06-30 08:00:00",
			actual_end="2026-06-30 09:00:00",
			fg_qty=100,
			rejection_qty=10,
			shift_name=shift.name,
		)

		_, rows, _, _ = execute({"from_date": "2026-06-30", "to_date": "2026-06-30"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["date"], "2026-06-30")
		self.assertEqual(float(rows[0]["total_qty"]), 100.0)
		self.assertEqual(float(rows[0]["rejection_qty"]), 10.0)
		# PPM = (10 / 100) * 1_000_000 = 100_000
		self.assertEqual(float(rows[0]["ppm"]), 100_000.0)

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

		_, rows, _, chart = execute({"from_date": "2026-07-03", "to_date": "2026-07-03"})
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

		_, rows = execute({"from_date": "2026-07-07", "to_date": "2026-07-07"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["rework_qty"]), 6.0)
		self.assertEqual(float(rows[0]["rework_rate_pct"]), 5.0)
		self.assertIn("Crack (6.0)", rows[0]["top_3_reasons"])

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
		self.assertIn("Crack (6.0)", rows[0]["dominant_reason"])

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

	# ── Daily Strokes SPM Monitor ─────────────────────────────────────

	def _ensure_fiscal_year(self, fy_name: str, start_date: str, end_date: str) -> None:
		if not frappe.db.exists("Fiscal Year", fy_name):
			frappe.get_doc(
				{
					"doctype": "Fiscal Year",
					"year": fy_name,
					"year_start_date": start_date,
					"year_end_date": end_date,
				}
			).insert(ignore_permissions=True)

	def test_daily_strokes_spm_monitor_columns_without_operator(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		self._ensure_fiscal_year("2090-2091", "2090-04-01", "2091-03-31")
		columns, _ = execute({"fiscal_year": "2090-2091", "month": "April"})
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

		self._ensure_fiscal_year("2090-2091", "2090-04-01", "2091-03-31")
		columns, _ = execute(
			{"fiscal_year": "2090-2091", "month": "April", "custom_operator": "Report Operator"}
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

		self._ensure_fiscal_year("2080-2081", "2080-04-01", "2081-03-31")
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

		_, rows = execute({"fiscal_year": "2080-2081", "month": "May", "custom_operator": "Report Operator"})
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
		# SPM = 100 / (0.25 * 60) ~= 6.667
		self.assertAlmostEqual(float(data_row["spm"]), 6.667, places=2)
		self.assertAlmostEqual(float(data_row["rejection"]), 10.0, places=2)
		self.assertAlmostEqual(float(data_row["rework"]), 0.0, places=2)

	def test_daily_strokes_spm_monitor_totals_row(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		self._ensure_fiscal_year("2081-2082", "2081-04-01", "2082-03-31")
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

		_, rows = execute({"fiscal_year": "2081-2082", "month": "June", "custom_operator": "Report Operator"})
		# 2 data rows + 1 totals
		self.assertEqual(len(rows), 3)
		totals = rows[-1]
		# Entry 1: good=90, rej=10 → total=100; Entry 2: good=180, rej=20 → total=200
		self.assertAlmostEqual(float(totals["total_strokes"]), 300.0, places=2)
		self.assertAlmostEqual(float(totals["rejection"]), 30.0, places=2)
		self.assertAlmostEqual(float(totals["rework"]), 0.0, places=2)
		self.assertAlmostEqual(float(totals["prod_time_hrs"]), 2.0, places=2)
		# weighted SPM = 300 / (2.0 * 60) = 2.5
		self.assertAlmostEqual(float(totals["spm"]), 2.5, places=2)

	def test_daily_strokes_spm_monitor_empty(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		self._ensure_fiscal_year("2099-2100", "2099-04-01", "2100-03-31")
		_, rows = execute({"fiscal_year": "2099-2100", "month": "April"})
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

		self._ensure_fiscal_year("2092", "2092-01-01", "2092-12-31")
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

		_, rows = execute({"fiscal_year": "2092", "month": "January", "custom_operator": "Report Operator"})
		self.assertEqual(rows[0]["date"], "2092-01-10")

	def test_daily_strokes_spm_monitor_date_range_supports_non_april_cross_year_fiscal_year(self) -> None:
		from production_entry_app.production_entry_app.report.daily_strokes_spm_monitor.daily_strokes_spm_monitor import (
			execute,
		)

		self._ensure_fiscal_year("2092-2093", "2092-10-01", "2093-09-30")
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
			{"fiscal_year": "2092-2093", "month": "September", "custom_operator": "Report Operator"}
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
		self.assertAlmostEqual(float(row["production_time_hrs"]), 2.5, places=3)
		self.assertAlmostEqual(float(row["total_strokes"]), 100.0, places=3)
		self.assertAlmostEqual(float(row["spm"]), 0.667, places=3)

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
					"custom_standard_spm": 2,
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
		# 1h + 1h actual runtime; must not include idle gap (09:00-16:00).
		self.assertAlmostEqual(float(row["production_time_hrs"]), 2.0, places=3)
		self.assertAlmostEqual(float(row["total_strokes"]), 200.0, places=3)
		self.assertAlmostEqual(float(row["spm"]), 1.667, places=3)

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
			custom_rejection_qty=rejection_qty,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		stock_entry.custom_operator = operator
		stock_entry.custom_workstation = workstation
		stock_entry.custom_shift = shift_name
		stock_entry.custom_standard_spm = standard_spm
		stock_entry.custom_planned_start_date = planned_start
		stock_entry.custom_planned_end_date = planned_end
		stock_entry.custom_actual_start_date = actual_start
		stock_entry.custom_actual_end_date = actual_end
		stock_entry.posting_date = posting_date
		stock_entry.posting_time = "09:00:00"

		if rejection_qty > 0:
			_append_rejection_breakup_rows(
				stock_entry,
				[{"rejection_reason": "Burr", "qty": rejection_qty, "remark": "Report test"}],
			)
		for row in unplanned_losses or []:
			stock_entry.append(
				"custom_unplanned_losses",
				{
					"downtime_reason": row.get("downtime_reason"),
					"start_time": row.get("start_time"),
					"end_time": row.get("end_time"),
					"remark": row.get("remark"),
					"shift": shift_name,
				},
			)

		stock_entry.save()
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
			custom_rejection_qty=rejection_qty,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		stock_entry.custom_operator = operator
		stock_entry.custom_workstation = workstation
		stock_entry.custom_shift = shift_name
		stock_entry.custom_standard_spm = 2
		stock_entry.custom_planned_start_date = planned_start
		stock_entry.custom_planned_end_date = planned_end
		stock_entry.custom_actual_start_date = actual_start
		stock_entry.custom_actual_end_date = actual_end
		stock_entry.posting_date = posting_date
		stock_entry.posting_time = "09:00:00"
		_append_rejection_breakup_rows(stock_entry, breakup_rows)
		stock_entry.save()
		frappe.db.set_value(
			"Stock Entry", stock_entry.name, "posting_date", posting_date, update_modified=False
		)
		# Intentionally mark submitted in DB for report isolation; these tests
		# validate query/report logic, not full stock-entry submit side effects.
		frappe.db.set_value("Stock Entry", stock_entry.name, "docstatus", 1, update_modified=False)
		stock_entry.reload()
		return stock_entry

	def _create_shift_for_label(self, shift_date: str, shift_label: str) -> frappe.Document:
		shift_name = f"SHIFT-{shift_date}.Shift-{shift_label}"
		if frappe.db.exists("Shift", shift_name):
			frappe.delete_doc("Shift", shift_name, force=True, ignore_permissions=True)
		shift = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": shift_label,
				"shift_duration": "8",
				"shift_date": shift_date,
				"planned_start_time": "08:00:00" if shift_label == "1" else "16:00:00",
				"rejection_warehouse": self.rejection_warehouse,
			}
		).insert(ignore_permissions=True)
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
					"shift": shift_name,
					"stop_reason": stop_reason,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
