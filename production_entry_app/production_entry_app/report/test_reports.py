from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.overrides.test_stock_entry_hooks import (
	_append_rejection_breakup_rows,
	_create_manufacture_stock_entry,
	_ensure_item_die_tool_fields,
	_ensure_rejection_breakup_custom_field,
	_ensure_rejection_breakup_doctype,
	_ensure_rejection_reason_doctype,
	_ensure_rejection_reasons,
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
		_ensure_item_die_tool_fields()
		for reason in (
			"Setup time",
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
			fieldnames[0:17],
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
				{"downtime_reason": "Setup time", "start_time": "10:00:00", "end_time": "10:30:00"}
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

		_, rows = execute({"from_date": "2026-06-10", "to_date": "2026-06-10"})
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

		_, rows = execute(
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

		_, rows = execute({"from_date": "2026-06-12", "to_date": "2026-06-13", "time_grain": "Daily"})
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["period"], "2026-06-12")
		self.assertEqual(float(rows[0]["total_qty"]), 100.0)
		self.assertEqual(float(rows[0]["rejection_qty"]), 10.0)
		self.assertEqual(float(rows[0]["ok_qty"]), 90.0)
		self.assertEqual(float(rows[0]["rejection_rate_pct"]), 10.0)
		self.assertEqual(rows[1]["period"], "2026-06-13")
		self.assertEqual(float(rows[1]["rejection_rate_pct"]), 10.0)

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

		_, rows = execute({"from_date": "2026-06-15", "to_date": "2026-06-22", "time_grain": "Weekly"})
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["period"], "2026-06-15 to 2026-06-21")
		self.assertEqual(float(rows[0]["total_qty"]), 160.0)
		self.assertEqual(float(rows[0]["rejection_qty"]), 8.0)
		self.assertEqual(float(rows[1]["total_qty"]), 90.0)
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

		columns, rows = execute(
			{"from_date": "2026-06-23", "to_date": "2026-06-23", "top_n_reasons": 2}
		)
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
			frappe.get_doc(
				{"doctype": "Operator", "operator_name": operator_2, "is_active": 1}
			).insert(ignore_permissions=True)
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
			frappe.get_doc(
				{"doctype": "Operator", "operator_name": operator_2, "is_active": 1}
			).insert(ignore_permissions=True)

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

		_, rows = execute(
			{"from_date": "2026-06-28", "to_date": "2026-06-28", "fg_item": self.fg_item}
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["item_code"], self.fg_item)
		self.assertEqual(float(rows[0]["rejection_qty"]), 5.0)

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
