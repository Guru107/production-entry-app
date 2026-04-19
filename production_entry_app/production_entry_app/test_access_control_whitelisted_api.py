from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

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
			("get_shift_timeline_data", lambda: get_shift_timeline_data("Workstation", "WS-00001")),
		]

		for label, gated_call in gated_calls:
			with self.subTest(label=label):
				with patch.object(access_control, "assert_app_access", side_effect=frappe.PermissionError):
					with self.assertRaises(frappe.PermissionError):
						gated_call()

	def test_denied_user_cannot_call_shift_specific_gated_apis(self) -> None:
		gated_calls = [
			("get_linked_downtime_entries", lambda: shift_module.get_linked_downtime_entries("SHIFT-00001")),
			(
				"check_running_shift_conflict",
				lambda: shift_module.check_running_shift_conflict("SHIFT-00001"),
			),
			("get_shift_summary", lambda: shift_module.get_shift_summary("SHIFT-00001")),
			(
				"get_shift_aggregate_production_entries",
				lambda: shift_module.get_shift_aggregate_production_entries("SHIFT-00001"),
			),
			("start_shift", lambda: Shift.start_shift(frappe._dict(name="SHIFT-00001"))),
			("end_shift", lambda: Shift.end_shift(frappe._dict(name="SHIFT-00001"))),
			("cancel_shift", lambda: Shift.cancel_shift(frappe._dict(name="SHIFT-00001"))),
		]

		for label, gated_call in gated_calls:
			with self.subTest(label=label):
				with patch.object(access_control, "assert_app_access", side_effect=frappe.PermissionError):
					with self.assertRaises(frappe.PermissionError):
						gated_call()

	def test_denied_user_not_blocked_by_app_gate_for_core_doctype_delete_path(self) -> None:
		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.api.frappe_client_delete_doc"
			) as delete_doc:
				delete("Stock Entry", "STE-00001")
		assert_app_access.assert_not_called()
		delete_doc.assert_called_once_with("Stock Entry", "STE-00001")

	def test_shift_delete_allows_doc_scoped_branch_match_without_default_branch(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._get_access_configuration",
				return_value=access_control.AccessConfiguration(
					enabled=True,
					rules=(("Manufacturing User", "Branch B"),),
				),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.db.get_value",
				return_value="Branch B",
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch"
			) as resolve_user_branch,
			patch("production_entry_app.production_entry_app.api.frappe_client_delete_doc") as delete_doc,
			patch(
				"production_entry_app.production_entry_app.api._cleanup_orphan_stock_entry_loss_links"
			) as cleanup_orphans,
			patch.object(
				access_control, "assert_app_access", wraps=access_control.assert_app_access
			) as guard,
		):
			delete("Shift", "SHIFT-B-00001")
		guard.assert_called_once_with(doctype="Shift", docname="SHIFT-B-00001")
		resolve_user_branch.assert_not_called()
		cleanup_orphans.assert_called_once_with("SHIFT-B-00001")
		delete_doc.assert_called_once_with("Shift", "SHIFT-B-00001")

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

		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.api.frappe.has_permission",
				return_value=False,
			) as has_permission:
				with patch(
					"production_entry_app.production_entry_app.api.frappe.get_doc", return_value=shift_doc
				):
					with self.assertRaises(frappe.PermissionError):
						get_shift_details_for_stock_entry("SHIFT-B-00001")
		assert_app_access.assert_called_once_with(doctype="Shift", docname="SHIFT-B-00001")
		has_permission.assert_called_once_with("Shift", "read", "SHIFT-B-00001")

	def test_shift_specific_endpoints_use_target_shift_read_permission(self) -> None:
		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.doctype.shift.shift.frappe.has_permission",
				return_value=False,
			) as has_permission:
				with self.assertRaises(frappe.PermissionError):
					shift_module.get_linked_downtime_entries("SHIFT-B-00001")
		assert_app_access.assert_called_once_with(doctype="Shift", docname="SHIFT-B-00001")
		has_permission.assert_called_once_with("Shift", "read", "SHIFT-B-00001")

		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.doctype.shift.shift.frappe.has_permission",
				return_value=False,
			) as has_permission:
				with self.assertRaises(frappe.PermissionError):
					shift_module.check_running_shift_conflict("SHIFT-B-00001")
		assert_app_access.assert_called_once_with(doctype="Shift", docname="SHIFT-B-00001")
		has_permission.assert_called_once_with("Shift", "read", "SHIFT-B-00001")

	def test_shift_timeline_data_allows_doc_scoped_branch_match_without_default_branch(self) -> None:
		class _FakeQuery:
			def select(self, *args, **kwargs):
				return self

			def where(self, *args, **kwargs):
				return self

			def orderby(self, *args, **kwargs):
				return self

			def inner_join(self, *args, **kwargs):
				return self

			def on(self, *args, **kwargs):
				return self

			def groupby(self, *args, **kwargs):
				return self

			def run(self, as_dict: bool = False):
				del as_dict
				return []

		fake_query = _FakeQuery()
		running_shift = [
			{
				"name": "SHIFT-B-00001",
				"shift_date": "2026-01-01",
				"planned_start_time": "08:00:00",
				"shift_end_date": "2026-01-01",
				"planned_end_time": "16:00:00",
			}
		]

		def _get_value(
			doctype: str,
			name: str | dict | tuple | None = None,
			fieldname: str | list | tuple | None = None,
			**kwargs,
		):
			del kwargs
			if doctype == "Shift" and fieldname == "branch":
				return "Branch B"
			if doctype == "Shift" and fieldname == "modified":
				return "2026-01-01 10:00:00"
			return None

		with (
			patch(
				"production_entry_app.production_entry_app.access_control._get_access_configuration",
				return_value=access_control.AccessConfiguration(
					enabled=True,
					rules=(("Manufacturing User", "Branch B"),),
				),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.db.get_value",
				side_effect=_get_value,
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch"
			) as resolve_user_branch,
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.get_all",
				return_value=running_shift,
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.has_permission",
				return_value=True,
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.get_meta",
				return_value=SimpleNamespace(is_submittable=False),
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.qb.from_",
				return_value=fake_query,
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.get_system_float_precision",
				return_value=3,
			),
			patch.object(
				access_control, "assert_app_access", wraps=access_control.assert_app_access
			) as guard,
		):
			resolve_user_branch.return_value = "Branch B"
			result = get_shift_timeline_data("Workstation", "WS-00001")
		guard.assert_has_calls(
			[
				call(doctype="Workstation", docname="WS-00001"),
				call(doctype="Shift", docname="SHIFT-B-00001"),
			]
		)
		self.assertEqual(guard.call_count, 2)
		resolve_user_branch.assert_not_called()
		self.assertEqual(result["shift_name"], "SHIFT-B-00001")
		self.assertEqual(result["entries"], [])
		self.assertEqual(result["float_precision"], 3)

	def test_shift_timeline_data_denies_doc_scoped_branch_mismatch_without_default_branch(self) -> None:
		class _FakeQuery:
			def select(self, *args, **kwargs):
				return self

			def where(self, *args, **kwargs):
				return self

			def orderby(self, *args, **kwargs):
				return self

			def inner_join(self, *args, **kwargs):
				return self

			def on(self, *args, **kwargs):
				return self

			def groupby(self, *args, **kwargs):
				return self

			def run(self, as_dict: bool = False):
				del as_dict
				return []

		fake_query = _FakeQuery()
		running_shift = [
			{
				"name": "SHIFT-B-00001",
				"shift_date": "2026-01-01",
				"planned_start_time": "08:00:00",
				"shift_end_date": "2026-01-01",
				"planned_end_time": "16:00:00",
			}
		]

		def _get_value(
			doctype: str,
			name: str | dict | tuple | None = None,
			fieldname: str | list | tuple | None = None,
			**kwargs,
		):
			del kwargs
			if doctype == "Shift" and fieldname == "branch":
				return "Branch B"
			if doctype == "Shift" and fieldname == "modified":
				return "2026-01-01 10:00:00"
			return None

		with (
			patch(
				"production_entry_app.production_entry_app.access_control._get_access_configuration",
				return_value=access_control.AccessConfiguration(
					enabled=True,
					rules=(("Sales User", "Branch A"),),
				),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.db.get_value",
				side_effect=_get_value,
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch"
			) as resolve_user_branch,
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.get_all",
				return_value=running_shift,
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.has_permission",
				return_value=True,
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.get_meta",
				return_value=SimpleNamespace(is_submittable=False),
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.qb.from_",
				return_value=fake_query,
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.get_system_float_precision",
				return_value=3,
			),
			patch.object(
				access_control, "assert_app_access", wraps=access_control.assert_app_access
			) as guard,
		):
			with self.assertRaises(frappe.PermissionError):
				get_shift_timeline_data("Workstation", "WS-00001")
		guard.assert_called_once_with(doctype="Workstation", docname="WS-00001")
		resolve_user_branch.assert_not_called()

	def test_allowed_user_can_call_required_whitelisted_apis(self) -> None:
		with patch.object(access_control, "assert_app_access") as assert_app_access:
			with patch(
				"production_entry_app.production_entry_app.api.frappe_client_delete_doc"
			) as delete_doc:
				delete("Shift", "SHIFT-00001")
		assert_app_access.assert_called_once_with(doctype="Shift", docname="SHIFT-00001")
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
		assert_app_access.assert_called_once_with(doctype="Workstation", docname="WS-00001")
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
