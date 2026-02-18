from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.overrides.test_stock_entry_hooks import (
	_create_manufacture_stock_entry,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	bootstrap_manufacturing_test_context,
	cleanup_running_shifts,
	ensure_item,
	ensure_operator,
	ensure_workstation,
)


class TestGetShiftTimelineData(FrappeTestCase):
	def setUp(self) -> None:
		cleanup_running_shifts()
		self.ctx = bootstrap_manufacturing_test_context("TIMELINE")
		self.fg_item = ensure_item("_TIMELINE_FG")
		self.rm_item = ensure_item("_TIMELINE_RM")
		ensure_workstation("Timeline WS A", standard_spm=2)
		ensure_workstation("Timeline WS B", standard_spm=2)
		ensure_operator("Timeline OP A")
		ensure_operator("Timeline OP B")
		self.workstation_a = (
			frappe.db.get_value("Workstation", {"workstation_name": "Timeline WS A"}, "name")
			or "Timeline WS A"
		)
		self.workstation_b = (
			frappe.db.get_value("Workstation", {"workstation_name": "Timeline WS B"}, "name")
			or "Timeline WS B"
		)
		self.operator_a = (
			frappe.db.get_value("Operator", {"operator_name": "Timeline OP A"}, "name") or "Timeline OP A"
		)
		self.operator_b = (
			frappe.db.get_value("Operator", {"operator_name": "Timeline OP B"}, "name") or "Timeline OP B"
		)

	def tearDown(self) -> None:
		frappe.db.rollback()

	def _create_running_shift(self, shift_date: str = "2026-10-01", shift_label: str = "1"):
		name = f"SHIFT-{shift_date}.Shift-{shift_label}"
		if frappe.db.exists("Shift", name):
			frappe.delete_doc("Shift", name, force=True, ignore_permissions=True)
		shift = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": shift_label,
				"shift_duration": "8",
				"shift_date": shift_date,
				"planned_start_time": "08:00:00",
			}
		).insert()
		shift.start_shift()
		return shift

	def _create_submitted_like_entry(
		self,
		shift_name: str,
		*,
		workstation: str | None = None,
		operator: str | None = None,
		actual_start: str | None = "2026-10-01 09:00:00",
		actual_end: str | None = "2026-10-01 10:00:00",
		good_qty: float = 100,
		rejection_qty: float = 0,
		docstatus: int = 1,
	) -> str:
		entry = _create_manufacture_stock_entry(
			company=self.ctx["company"],
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=good_qty,
			rm_qty=good_qty,
			custom_shift=shift_name,
			custom_rejection_qty=rejection_qty,
			fg_warehouse=self.ctx["fg_warehouse"],
			rm_warehouse=self.ctx["rm_warehouse"],
		)
		entry.custom_workstation = workstation
		entry.custom_operator = operator
		entry.custom_actual_start_date = actual_start
		entry.custom_actual_end_date = actual_end
		entry.save()
		frappe.db.set_value("Stock Entry", entry.name, "docstatus", docstatus, update_modified=False)
		return entry.name

	def test_returns_empty_when_no_running_shift(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertIsNone(result["shift_name"])
		self.assertEqual(result["entries"], [])

	def test_returns_shift_window_for_running_shift(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-02")
		result = get_shift_timeline_data("Workstation", "Timeline WS A")
		self.assertEqual(result["shift_name"], shift.name)
		self.assertEqual(str(result["shift_start"]), "2026-10-02 08:00:00")
		self.assertEqual(str(result["shift_end"]), "2026-10-02 16:00:00")

	def test_returns_entries_for_workstation_in_running_shift(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-03")
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-03 09:00:00",
			actual_end="2026-10-03 10:00:00",
		)
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_b,
			operator=self.operator_a,
			actual_start="2026-10-03 10:00:00",
			actual_end="2026-10-03 11:00:00",
		)
		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertEqual(len(result["entries"]), 1)
		self.assertEqual(result["entries"][0]["actual_start"], "2026-10-03 09:00:00")

	def test_returns_entries_sorted_by_actual_start(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-08")
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-08 11:00:00",
			actual_end="2026-10-08 12:00:00",
		)
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-08 09:00:00",
			actual_end="2026-10-08 10:00:00",
		)
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-08 10:00:00",
			actual_end="2026-10-08 11:00:00",
		)
		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertEqual(len(result["entries"]), 3)
		self.assertEqual(
			[item["actual_start"] for item in result["entries"]],
			["2026-10-08 09:00:00", "2026-10-08 10:00:00", "2026-10-08 11:00:00"],
		)

	def test_returns_entries_for_operator_in_running_shift(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-04")
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-04 09:00:00",
			actual_end="2026-10-04 10:00:00",
		)
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_b,
			actual_start="2026-10-04 10:00:00",
			actual_end="2026-10-04 11:00:00",
		)
		result = get_shift_timeline_data("Operator", self.operator_a)
		self.assertEqual(len(result["entries"]), 1)
		self.assertEqual(result["entries"][0]["actual_start"], "2026-10-04 09:00:00")

	def test_entry_has_correct_qty_fields(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-05")
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			good_qty=120,
			rejection_qty=0,
			actual_start="2026-10-05 09:00:00",
			actual_end="2026-10-05 10:00:00",
		)
		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertEqual(len(result["entries"]), 1)
		entry = result["entries"][0]
		self.assertEqual(float(entry["fg_qty"]), 120.0)
		self.assertEqual(float(entry["rejection_qty"]), 0.0)
		self.assertEqual(float(entry["ok_qty"]), 120.0)

	def test_entry_has_fg_item_from_finished_items(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-06")
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-06 09:00:00",
			actual_end="2026-10-06 10:00:00",
		)
		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertEqual(result["entries"][0]["fg_item"], self.fg_item)

	def test_entries_without_actual_times_excluded(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-07")
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start=None,
			actual_end=None,
		)
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-07 10:00:00",
			actual_end="2026-10-07 11:00:00",
		)
		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertEqual(len(result["entries"]), 1)
		self.assertEqual(result["entries"][0]["actual_start"], "2026-10-07 10:00:00")

	def test_invalid_doctype_raises_error(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		with self.assertRaises(ValidationError):
			get_shift_timeline_data("Item", "_TIMELINE_FG")

	def test_raises_permission_error_when_target_doctype_not_readable(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		with patch(
			"production_entry_app.production_entry_app.api_timeline.frappe.has_permission",
			return_value=False,
		):
			with self.assertRaises(frappe.PermissionError):
				get_shift_timeline_data("Workstation", self.workstation_a)

	def test_raises_permission_error_when_running_shift_not_readable(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		self._create_running_shift("2026-10-09")
		with patch(
			"production_entry_app.production_entry_app.api_timeline.frappe.has_permission",
			side_effect=[True, False],
		):
			with self.assertRaises(frappe.PermissionError):
				get_shift_timeline_data("Workstation", self.workstation_a)
