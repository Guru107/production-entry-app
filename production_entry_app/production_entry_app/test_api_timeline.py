from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.overrides.test_stock_entry_hooks import (
	_append_rejection_breakup_rows,
	_create_manufacture_stock_entry,
	_ensure_rejection_breakup_custom_field,
	_ensure_rejection_breakup_doctype,
	_ensure_rejection_reason_doctype,
	_ensure_rejection_reasons,
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

	def _ensure_rejection_breakup_fixtures(self) -> None:
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()

	def _create_running_shift(self, shift_date: str = "2026-10-01", shift_label: str = "1"):
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
				"company": self.ctx["company"],
				"department": department,
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
			custom_pea_shift=shift_name,
			custom_pea_rejection_qty=rejection_qty,
			fg_warehouse=self.ctx["fg_warehouse"],
			rm_warehouse=self.ctx["rm_warehouse"],
		)
		entry.custom_pea_workstation = workstation
		entry.custom_pea_operator = operator
		entry.custom_pea_actual_start_date = actual_start
		entry.custom_pea_actual_end_date = actual_end
		entry.save()
		frappe.db.set_value("Stock Entry", entry.name, "docstatus", docstatus, update_modified=False)
		return entry.name

	def _create_downtime_entry(
		self,
		*,
		workstation: str,
		from_time: str,
		to_time: str,
		stop_reason: str = "Other",
	) -> str:
		operator = frappe.db.get_value("Employee", {"employee_number": "TIMELINE-EMP"}, "name")
		if not operator:
			operator = (
				frappe.get_doc(
					{
						"doctype": "Employee",
						"first_name": "Timeline",
						"last_name": "Test",
						"gender": "Female",
						"date_of_birth": "1990-01-01",
						"date_of_joining": "2020-01-01",
						"company": self.ctx["company"],
						"status": "Active",
						"employee_number": "TIMELINE-EMP",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		doc = frappe.get_doc(
			{
				"doctype": "Downtime Entry",
				"workstation": workstation,
				"operator": operator,
				"from_time": from_time,
				"to_time": to_time,
				"stop_reason": stop_reason,
			}
		).insert(ignore_permissions=True)
		return doc.name

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

	def test_returns_float_precision_for_custom_timeline_rendering(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data
		from production_entry_app.production_entry_app.utils.system_precision import (
			get_system_float_precision,
		)

		shift = self._create_running_shift("2026-10-09")
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-09 09:00:00",
			actual_end="2026-10-09 10:00:00",
			good_qty=95,
			rejection_qty=0,
		)
		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertEqual(result["float_precision"], get_system_float_precision())
		self.assertIsInstance(result["entries"][0]["fg_qty"], float)
		self.assertIsInstance(result["entries"][0]["rejection_qty"], float)
		self.assertIsInstance(result["entries"][0]["ok_qty"], float)

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

	def test_entry_qty_fields_preserve_raw_decimal_values(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		self._ensure_rejection_breakup_fixtures()
		shift = self._create_running_shift("2026-10-14")
		frappe.db.set_value(
			"Shift", shift.name, "rejection_warehouse", self.ctx["rejection_warehouse"], update_modified=False
		)
		total_finished_qty_before_rejection = 120
		rejection_qty = 0.1235
		expected_fg_qty = 119.8765
		expected_ok_qty = 119.753
		derived_abs_tol = 1e-6
		entry = _create_manufacture_stock_entry(
			company=self.ctx["company"],
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=total_finished_qty_before_rejection,
			rm_qty=total_finished_qty_before_rejection,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=rejection_qty,
			fg_warehouse=self.ctx["fg_warehouse"],
			rm_warehouse=self.ctx["rm_warehouse"],
		)
		entry.custom_pea_workstation = self.workstation_a
		entry.custom_pea_operator = self.operator_a
		entry.custom_pea_actual_start_date = "2026-10-14 09:00:00"
		entry.custom_pea_actual_end_date = "2026-10-14 10:00:00"
		_append_rejection_breakup_rows(
			entry,
			[
				{
					"rejection_reason": "Burr",
					"qty": rejection_qty,
				}
			],
		)
		entry.save()
		frappe.db.set_value("Stock Entry", entry.name, "docstatus", 1, update_modified=False)

		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertEqual(len(result["entries"]), 1)
		entry = result["entries"][0]
		self.assertAlmostEqual(float(entry["fg_qty"]), expected_fg_qty, delta=derived_abs_tol)
		self.assertAlmostEqual(float(entry["rejection_qty"]), rejection_qty, delta=derived_abs_tol)
		self.assertAlmostEqual(float(entry["ok_qty"]), expected_ok_qty, delta=derived_abs_tol)

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

	def test_entry_keeps_link_safe_fg_item_and_exposes_combined_display_label(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-16")
		entry_name = self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-16 09:00:00",
			actual_end="2026-10-16 10:00:00",
		)
		second_item = ensure_item("_TIMELINE_FG_SECOND")
		frappe.get_doc(
			{
				"doctype": "Stock Entry Detail",
				"parent": entry_name,
				"parenttype": "Stock Entry",
				"parentfield": "items",
				"idx": 3,
				"item_code": second_item,
				"qty": 1,
				"transfer_qty": 1,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"t_warehouse": self.ctx["fg_warehouse"],
				"is_finished_item": 1,
			}
		).db_insert()

		result = get_shift_timeline_data("Workstation", self.workstation_a)

		self.assertEqual(result["entries"][0]["fg_item"], self.fg_item)
		self.assertEqual(result["entries"][0]["fg_item_label"], f"{self.fg_item} + {second_item}")

	def test_entry_quantity_falls_back_to_header_when_finished_rows_are_unavailable(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-17")
		entry_name = self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-17 09:00:00",
			actual_end="2026-10-17 10:00:00",
			good_qty=37,
		)
		frappe.db.delete("Stock Entry Detail", {"parent": entry_name})
		frappe.db.set_value("Stock Entry", entry_name, "fg_completed_qty", 37, update_modified=False)

		result = get_shift_timeline_data("Workstation", self.workstation_a)

		self.assertEqual(result["entries"][0]["fg_qty"], 37)

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

	def test_workstation_includes_overlapping_downtime_entries(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-11")
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-11 09:00:00",
			actual_end="2026-10-11 10:00:00",
		)
		downtime_name = self._create_downtime_entry(
			workstation=self.workstation_a,
			from_time="2026-10-11 10:00:00",
			to_time="2026-10-11 10:30:00",
		)
		self._create_downtime_entry(
			workstation=self.workstation_a,
			from_time="2026-10-11 18:00:00",
			to_time="2026-10-11 19:00:00",
		)

		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertEqual(len(result["entries"]), 2)
		self.assertEqual(
			[item["entry_type"] for item in result["entries"]],
			["production", "downtime"],
		)
		self.assertEqual(result["entries"][1]["name"], downtime_name)

	def test_operator_timeline_excludes_downtime_entries(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-12")
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-12 09:00:00",
			actual_end="2026-10-12 10:00:00",
		)
		self._create_downtime_entry(
			workstation=self.workstation_a,
			from_time="2026-10-12 10:00:00",
			to_time="2026-10-12 10:30:00",
		)

		result = get_shift_timeline_data("Operator", self.operator_a)
		self.assertEqual(len(result["entries"]), 1)
		self.assertEqual(result["entries"][0]["entry_type"], "production")

	def test_workstation_entries_with_downtime_are_sorted_by_actual_start(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-13")
		self._create_submitted_like_entry(
			shift.name,
			workstation=self.workstation_a,
			operator=self.operator_a,
			actual_start="2026-10-13 11:00:00",
			actual_end="2026-10-13 12:00:00",
		)
		self._create_downtime_entry(
			workstation=self.workstation_a,
			from_time="2026-10-13 09:30:00",
			to_time="2026-10-13 10:00:00",
		)

		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertEqual(
			[item["actual_start"] for item in result["entries"]],
			["2026-10-13 09:30:00", "2026-10-13 11:00:00"],
		)

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

		shift = self._create_running_shift("2026-10-09")
		with (
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.get_list",
				return_value=[{"name": shift.name}],
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.has_permission",
				side_effect=[True, False],
			),
		):
			with self.assertRaises(frappe.PermissionError):
				get_shift_timeline_data("Workstation", self.workstation_a)

	def test_raises_permission_error_when_stock_entries_not_readable(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data

		shift = self._create_running_shift("2026-10-09")
		with (
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.get_list",
				return_value=[{"name": shift.name}],
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.has_permission",
				side_effect=[True, True, False],
			),
		):
			with self.assertRaises(frappe.PermissionError):
				get_shift_timeline_data("Workstation", self.workstation_a)

	def test_returns_cached_timeline_without_querying_stock_entries(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data
		from production_entry_app.production_entry_app.utils.system_precision import (
			get_system_float_precision,
		)

		shift = self._create_running_shift("2026-10-10")
		cached = {
			"shift_name": shift.name,
			"shift_start": "2026-10-10 08:00:00",
			"shift_end": "2026-10-10 16:00:00",
			"entries": [{"name": "SE-CACHED-1"}],
		}
		running_shift = [
			{
				"name": shift.name,
				"shift_date": shift.shift_date,
				"planned_start_time": shift.planned_start_time,
				"shift_end_date": shift.shift_end_date,
				"planned_end_time": shift.planned_end_time,
			}
		]
		with (
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.get_list",
				return_value=running_shift,
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.get_system_float_precision",
				return_value=4,
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline._get_cached_timeline_data",
				return_value=cached,
			),
		):
			with patch("production_entry_app.production_entry_app.api_timeline.frappe.qb.from_") as qb_from:
				result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertEqual(result["shift_name"], cached["shift_name"])
		self.assertEqual(result["shift_start"], cached["shift_start"])
		self.assertEqual(result["shift_end"], cached["shift_end"])
		self.assertEqual(result["entries"], cached["entries"])
		self.assertEqual(result["float_precision"], 4)
		# Access control may query settings/shift metadata, but a cache hit must skip Stock Entry reads.
		self.assertFalse(
			any("tabStock Entry" in str(call) for call in qb_from.call_args_list),
			msg=f"Unexpected Stock Entry query calls: {qb_from.call_args_list}",
		)

	def test_timeline_payload_uses_updated_shift_end_after_duration_change(self) -> None:
		"""When a Running shift's duration changes, the timeline payload must use the
		updated shift_end rather than a stale value from before the change.

		This test primes the cache with data that has the old end time, then changes
		the shift's duration, then verifies the returned data has the NEW end time
		(proving the cache was bypassed and fresh data was computed)."""
		from production_entry_app.production_entry_app.api_timeline import (
			_get_cached_timeline_data,
			_get_timeline_cache_key,
			get_shift_timeline_data,
		)

		shift = self._create_running_shift("2026-10-15")
		# Shift is 8 hours (08:00 - 16:00)
		self.assertEqual(str(shift.planned_end_time), "16:00:00")

		# Prime the cache with data that has the OLD end time (16:00)
		result_before = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertIn("16:00", result_before["shift_end"])

		# Record the old modified timestamp before the change
		old_modified = frappe.db.get_value("Shift", shift.name, "modified")

		# Change shift duration to 10 hours (shift end becomes 18:00)
		frappe.db.set_value(
			"Shift",
			shift.name,
			{"shift_duration": "10", "planned_end_time": "18:00:00"},
		)

		# Verify the modified timestamp changed (cache key will be different)
		new_modified = frappe.db.get_value("Shift", shift.name, "modified")
		self.assertNotEqual(old_modified, new_modified)

		# Verify the cache is bypassed (returns None because the cache key changed
		# since the shift's modified timestamp is now different from when we cached)
		cached = _get_cached_timeline_data("Workstation", self.workstation_a, shift.name)
		self.assertIsNone(cached)

		# Verify fresh data is returned with the new shift end (not 16:00)
		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertIn("18:00", result["shift_end"])

	def test_timeline_cache_is_shared_after_permission_checks(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import (
			_get_cached_timeline_data,
			_set_cached_timeline_data,
		)

		cache = MagicMock()
		cache.get_value.return_value = {"entries": [{"name": "PRIVATE-ENTRY"}]}
		with (
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.session",
				frappe._dict(user="restricted@example.com"),
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.cache",
				return_value=cache,
			),
		):
			_set_cached_timeline_data("Workstation", self.workstation_a, "SHIFT-001", {"entries": []})
			cached = _get_cached_timeline_data("Workstation", self.workstation_a, "SHIFT-001")

		self.assertEqual(cached, {"entries": [{"name": "PRIVATE-ENTRY"}]})
		cache.get_value.assert_called_once()
		cache.set_value.assert_called_once()

	def test_stock_entry_invalidates_workstation_and_operator_timeline_caches(self) -> None:
		from production_entry_app.production_entry_app.api_timeline import (
			invalidate_timeline_cache_for_stock_entry,
		)

		cache = MagicMock()
		with patch(
			"production_entry_app.production_entry_app.api_timeline.frappe.cache",
			return_value=cache,
		):
			invalidate_timeline_cache_for_stock_entry(
				frappe._dict(
					custom_pea_shift="SHIFT-001",
					custom_pea_workstation="PRESS-001",
					custom_pea_operator="OP-001",
				)
			)

		self.assertEqual(cache.delete_keys.call_count, 2)
		cache.delete_keys.assert_any_call("pea:timeline:Workstation:PRESS-001:SHIFT-001:")
		cache.delete_keys.assert_any_call("pea:timeline:Operator:OP-001:SHIFT-001:")

	def test_timeline_cache_is_invalidated_when_running_shift_duration_changes(self) -> None:
		"""When a Running shift's duration is updated, the timeline cache must be
		invalidated so subsequent calls return fresh data."""
		from production_entry_app.production_entry_app.api_timeline import (
			_get_cached_timeline_data,
			_get_timeline_cache_key,
			get_shift_timeline_data,
		)

		shift = self._create_running_shift("2026-10-16")
		# Prime the cache
		_ = get_shift_timeline_data("Workstation", self.workstation_a)

		# Change shift duration to 12 hours (shift end becomes 20:00)
		frappe.db.set_value(
			"Shift",
			shift.name,
			{"shift_duration": "12", "planned_end_time": "20:00:00"},
		)

		# The cached data should now be considered stale (cache key changed because modified timestamp changed)
		cached = _get_cached_timeline_data("Workstation", self.workstation_a, shift.name)
		self.assertIsNone(cached)

		# And fresh data should be returned with the new shift end
		result = get_shift_timeline_data("Workstation", self.workstation_a)
		self.assertIn("20:00", result["shift_end"])
