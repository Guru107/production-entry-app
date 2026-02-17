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
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()
		_ensure_item_die_tool_fields()

		cls.company = resolve_test_company()
		abbr = get_company_abbr(cls.company)
		cls.wip_warehouse = _get_or_create_warehouse(f"WIP Report - {abbr}", cls.company)
		cls.rm_warehouse = _get_or_create_warehouse(f"RM Report - {abbr}", cls.company)
		cls.fg_warehouse = _get_or_create_warehouse(f"FG Report - {abbr}", cls.company)
		cls.rejection_warehouse = _get_or_create_warehouse(f"RJ Report - {abbr}", cls.company)

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

	def test_production_oee_report_metrics(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		stock_entry = self._create_mock_submitted_entry(
			posting_date="2026-06-01",
			planned_start="2026-06-01 08:00:00",
			planned_end="2026-06-01 09:00:00",
			actual_start="2026-06-01 08:00:00",
			actual_end="2026-06-01 09:00:00",
			fg_qty=120,
			rejection_qty=0,
		)
		self.assertEqual(stock_entry.docstatus, 1)

		_, rows = execute({"from_date": "2026-06-01", "to_date": "2026-06-01"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(str(rows[0]["posting_date"]), "2026-06-01")
		self.assertEqual(float(rows[0]["availability_pct"]), 100.0)
		self.assertEqual(float(rows[0]["performance_pct"]), 100.0)
		self.assertEqual(float(rows[0]["quality_pct"]), 100.0)
		self.assertEqual(float(rows[0]["oee_pct"]), 100.0)

	def test_production_oee_report_caps_availability_at_100(self) -> None:
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute,
		)

		self._create_mock_submitted_entry(
			posting_date="2026-06-01",
			planned_start="2026-06-01 08:00:00",
			planned_end="2026-06-01 09:00:00",
			actual_start="2026-06-01 08:00:00",
			actual_end="2026-06-01 10:00:00",
			fg_qty=120,
			rejection_qty=0,
		)

		_, rows = execute({"from_date": "2026-06-01", "to_date": "2026-06-01"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["availability_pct"]), 100.0)
		self.assertEqual(float(rows[0]["oee_pct"]), 50.0)

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

	def test_reports_support_fg_item_filter(self) -> None:
		from production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report import (
			execute as operator_execute,
		)
		from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
			execute as oee_execute,
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
		_, oee_rows = oee_execute(filters)
		_, operator_rows = operator_execute(filters)
		_, workstation_rows = workstation_execute(filters)
		self.assertEqual(len(oee_rows), 1)
		self.assertEqual(oee_rows[0]["item_code"], self.fg_item)
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

		stock_entry.save()
		frappe.db.set_value(
			"Stock Entry", stock_entry.name, "posting_date", posting_date, update_modified=False
		)
		# Intentionally mark submitted in DB for report isolation; these tests
		# validate query/report logic, not full stock-entry submit side effects.
		frappe.db.set_value("Stock Entry", stock_entry.name, "docstatus", 1, update_modified=False)
		stock_entry.reload()
		return stock_entry
