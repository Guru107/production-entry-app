from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import access_control
from production_entry_app.production_entry_app.api import (
	bootstrap_e2e_context,
	cleanup_e2e_context,
	cleanup_reserved_e2e_artifacts,
	create_e2e_downtime_entry,
	create_e2e_full_shift_stock_entries,
	create_e2e_submitted_stock_entry,
	delete,
	get_access_control_state,
	get_die_tool_counter,
	get_items_with_rejection,
	get_shift_details_for_stock_entry,
	reset_die_tool_counter,
	set_e2e_system_float_precision,
)
from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data
from production_entry_app.production_entry_app.doctype.shift import shift as shift_module
from production_entry_app.production_entry_app.doctype.shift.shift import Shift


class TestAccessControlWhitelistedApi(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_denied_user_cannot_call_gated_whitelisted_apis(self) -> None:
		gated_calls = [
			("delete", lambda: delete("Shift", "SHIFT-00001")),
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

	def test_denied_user_not_blocked_by_app_gate_for_core_doctype_delete_path(self) -> None:
		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.api.frappe_client_delete_doc"
			) as delete_doc:
				delete("Stock Entry", "STE-00001")
		assert_app_access.assert_not_called()
		delete_doc.assert_called_once_with("Stock Entry", "STE-00001")

	def test_shift_details_checks_target_shift_read_permission(self) -> None:
		shift_doc = MagicMock()
		shift_doc.name = "SHIFT-B-00001"
		shift_doc.status = "Running"
		shift_doc.branch = "Branch B"
		shift_doc.shift_date = "2026-01-01"
		shift_doc.planned_start_time = "08:00:00"
		shift_doc.planned_end_time = "16:00:00"
		shift_doc.shift_end_date = "2026-01-01"
		shift_doc.work_in_progress_warehouse = "WIP-B"

		with patch("production_entry_app.production_entry_app.api.frappe.get_doc", return_value=shift_doc):
			with patch(
				"production_entry_app.production_entry_app.api.frappe.has_permission",
				return_value=False,
			) as has_permission:
				with patch.object(access_control, "assert_app_access") as assert_app_access:
					with self.assertRaises(frappe.PermissionError):
						get_shift_details_for_stock_entry("SHIFT-B-00001")
		assert_app_access.assert_not_called()
		has_permission.assert_called_once_with("Shift", "read", "SHIFT-B-00001")

	def test_shift_specific_endpoints_use_target_shift_read_permission(self) -> None:
		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.doctype.shift.shift.frappe.has_permission",
				return_value=False,
			) as has_permission:
				with self.assertRaises(frappe.PermissionError):
					shift_module.get_linked_downtime_entries("SHIFT-B-00001")
		assert_app_access.assert_not_called()
		has_permission.assert_called_once_with("Shift", "read", "SHIFT-B-00001")

		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.doctype.shift.shift.frappe.has_permission",
				return_value=False,
			) as has_permission:
				with self.assertRaises(frappe.PermissionError):
					shift_module.check_running_shift_conflict("SHIFT-B-00001")
		assert_app_access.assert_not_called()
		has_permission.assert_called_once_with("Shift", "read", "SHIFT-B-00001")

	def test_allowed_user_can_call_required_whitelisted_apis(self) -> None:
		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.api.frappe_client_delete_doc"
			) as delete_doc:
				delete("Shift", "SHIFT-00001")
		assert_app_access.assert_called_once()
		delete_doc.assert_called_once_with("Shift", "SHIFT-00001")

		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.api.frappe.db.exists",
				return_value=False,
			):
				result = get_die_tool_counter("ITEM-00001")
		assert_app_access.assert_called_once()
		self.assertEqual(result["die_tool_code"], "ITEM-00001")

		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.has_permission",
				return_value=True,
			):
				with patch(
					"production_entry_app.production_entry_app.api_timeline.frappe.get_all", return_value=[]
				):
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
