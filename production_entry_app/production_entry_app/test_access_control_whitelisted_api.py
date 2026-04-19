from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import access_control
from production_entry_app.production_entry_app.api import (
	delete,
	get_access_control_state,
	get_die_tool_counter,
	get_items_with_rejection,
	get_shift_details_for_stock_entry,
	reset_die_tool_counter,
)
from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data
from production_entry_app.production_entry_app.doctype.shift.shift import Shift
from production_entry_app.production_entry_app.doctype.shift.shift import (
	check_running_shift_conflict,
	get_linked_downtime_entries,
	get_planned_losses_for_duration,
	get_shift_aggregate_production_entries,
	get_shift_summary,
)
from production_entry_app.production_entry_app.api import (
	bootstrap_e2e_context,
	cleanup_e2e_context,
	cleanup_reserved_e2e_artifacts,
	create_e2e_downtime_entry,
	create_e2e_full_shift_stock_entries,
	create_e2e_submitted_stock_entry,
	set_e2e_system_float_precision,
)


class TestAccessControlWhitelistedApi(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_denied_user_cannot_call_gated_whitelisted_apis(self) -> None:
		gated_calls = [
			("delete", lambda: delete("Stock Entry", "STE-00001")),
			("get_shift_details_for_stock_entry", lambda: get_shift_details_for_stock_entry("SHIFT-00001")),
			("get_items_with_rejection", lambda: get_items_with_rejection("{}")),
			("get_die_tool_counter", lambda: get_die_tool_counter("ITEM-00001")),
			("reset_die_tool_counter", lambda: reset_die_tool_counter("ITEM-00001")),
			("bootstrap_e2e_context", lambda: bootstrap_e2e_context()),
			("set_e2e_system_float_precision", lambda: set_e2e_system_float_precision()),
			("cleanup_e2e_context", lambda: cleanup_e2e_context()),
			("cleanup_reserved_e2e_artifacts", lambda: cleanup_reserved_e2e_artifacts()),
			("create_e2e_submitted_stock_entry", lambda: create_e2e_submitted_stock_entry()),
			("create_e2e_full_shift_stock_entries", lambda: create_e2e_full_shift_stock_entries()),
			("create_e2e_downtime_entry", lambda: create_e2e_downtime_entry()),
			("get_planned_losses_for_duration", lambda: get_planned_losses_for_duration("8", "08:00:00", "2026-01-01")),
			("get_linked_downtime_entries", lambda: get_linked_downtime_entries("SHIFT-00001")),
			("check_running_shift_conflict", lambda: check_running_shift_conflict("SHIFT-00001")),
			("get_shift_summary", lambda: get_shift_summary("SHIFT-00001")),
			("get_shift_aggregate_production_entries", lambda: get_shift_aggregate_production_entries("SHIFT-00001")),
			("get_shift_timeline_data", lambda: get_shift_timeline_data("Workstation", "WS-00001")),
			("start_shift", lambda: Shift.start_shift(frappe._dict(name="SHIFT-00001"))),
			("end_shift", lambda: Shift.end_shift(frappe._dict(name="SHIFT-00001"))),
			("cancel_shift", lambda: Shift.cancel_shift(frappe._dict(name="SHIFT-00001"))),
		]

		for label, call in gated_calls:
			with self.subTest(label=label):
				with patch.object(access_control, "assert_app_access", side_effect=frappe.PermissionError):
					with self.assertRaises(frappe.PermissionError):
						call()

	def test_allowed_user_can_call_required_whitelisted_apis(self) -> None:
		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.api.frappe_client_delete_doc"
			) as delete_doc:
				delete("Stock Entry", "STE-00001")
		assert_app_access.assert_called_once()
		delete_doc.assert_called_once_with("Stock Entry", "STE-00001")

		shift_doc = MagicMock()
		shift_doc.name = "SHIFT-00001"
		shift_doc.status = "Running"
		shift_doc.branch = "Main"
		shift_doc.shift_date = "2026-01-01"
		shift_doc.planned_start_time = "08:00:00"
		shift_doc.planned_end_time = "16:00:00"
		shift_doc.shift_end_date = "2026-01-01"
		shift_doc.work_in_progress_warehouse = "WIP - TEST"

		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.api.frappe.get_doc",
				return_value=shift_doc,
			):
				with patch(
					"production_entry_app.production_entry_app.api.get_shift_planned_end_datetime",
					return_value="2026-01-01 16:00:00",
				):
					result = get_shift_details_for_stock_entry("SHIFT-00001")
		assert_app_access.assert_called_once()
		self.assertEqual(
			result,
			{
				"branch": "Main",
				"custom_planned_start_date": "2026-01-01 08:00:00",
				"custom_planned_end_date": "2026-01-01 16:00:00",
				"from_warehouse": "WIP - TEST",
				"to_warehouse": "WIP - TEST",
			},
		)

		planned_loss_doc = MagicMock()
		planned_loss_doc.planned_losses = [
			frappe._dict(downtime_reason="Tea Break", start_time="09:00:00", end_time="09:10:00")
		]

		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.doctype.shift.shift.frappe.new_doc",
				return_value=planned_loss_doc,
			):
				result = get_planned_losses_for_duration("8", "08:00:00", "2026-01-01")
		assert_app_access.assert_called_once()
		self.assertEqual(
			result,
			[
				{
					"downtime_reason": "Tea Break",
					"start_time": "09:00:00",
					"end_time": "09:10:00",
				}
			],
		)

		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch("production_entry_app.production_entry_app.api_timeline.frappe.has_permission", return_value=True):
				with patch("production_entry_app.production_entry_app.api_timeline.frappe.get_all", return_value=[]):
					with patch(
						"production_entry_app.production_entry_app.api_timeline.get_system_float_precision",
						return_value=3,
					):
						result = get_shift_timeline_data("Workstation", "WS-00001")
		assert_app_access.assert_called_once()
		self.assertEqual(
			result,
			{"shift_name": None, "entries": [], "float_precision": 3},
		)

	def test_allowlisted_endpoint_returns_current_access_state_without_guard(self) -> None:
		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch.object(access_control, "has_app_permission", return_value=False):
				result = get_access_control_state()
		assert_app_access.assert_not_called()
		self.assertEqual(result, {"enabled": False})

		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch.object(access_control, "has_app_permission", return_value=True):
				result = get_access_control_state()
		assert_app_access.assert_not_called()
		self.assertEqual(result, {"enabled": True})
