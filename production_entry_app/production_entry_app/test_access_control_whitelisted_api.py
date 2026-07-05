from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import access_control
from production_entry_app.production_entry_app.api import (
	get_access_control_state,
	get_die_tool_counter,
	get_items_with_rejection,
	get_shift_details_for_stock_entry,
	reset_die_tool_counter,
)
from production_entry_app.production_entry_app.api_timeline import get_shift_timeline_data
from production_entry_app.production_entry_app.doctype.shift import shift as shift_module
from production_entry_app.production_entry_app.doctype.shift.shift import Shift
from production_entry_app.production_entry_app.e2e_api import (
	bootstrap_e2e_context,
	cleanup_e2e_context,
	cleanup_reserved_e2e_artifacts,
	create_e2e_downtime_entry,
	create_e2e_full_shift_stock_entries,
	create_e2e_submitted_stock_entry,
	set_e2e_system_float_precision,
)

REQUIRED_ROLE: str = "PEA User"
READ_ROLE: str = "PEA Read Only"


class TestAccessControlWhitelistedApi(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_denied_user_cannot_call_gated_whitelisted_apis(self) -> None:
		gated_calls = [
			(
				"get_shift_details_for_stock_entry",
				"assert_app_read_access",
				lambda: get_shift_details_for_stock_entry("SHIFT-00001"),
			),
			("get_items_with_rejection", "assert_app_write_access", lambda: get_items_with_rejection("{}")),
			("get_die_tool_counter", "assert_app_read_access", lambda: get_die_tool_counter("ITEM-00001")),
			(
				"reset_die_tool_counter",
				"assert_app_write_access",
				lambda: reset_die_tool_counter("ITEM-00001"),
			),
			("bootstrap_e2e_context", "assert_app_write_access", lambda: bootstrap_e2e_context()),
			(
				"set_e2e_system_float_precision",
				"assert_app_write_access",
				lambda: set_e2e_system_float_precision(),
			),
			("cleanup_e2e_context", "assert_app_write_access", lambda: cleanup_e2e_context()),
			(
				"cleanup_reserved_e2e_artifacts",
				"assert_app_write_access",
				lambda: cleanup_reserved_e2e_artifacts(),
			),
			(
				"create_e2e_submitted_stock_entry",
				"assert_app_write_access",
				lambda: create_e2e_submitted_stock_entry(),
			),
			(
				"create_e2e_full_shift_stock_entries",
				"assert_app_write_access",
				lambda: create_e2e_full_shift_stock_entries(),
			),
			("create_e2e_downtime_entry", "assert_app_write_access", lambda: create_e2e_downtime_entry()),
			(
				"get_shift_timeline_data",
				"assert_app_read_access",
				lambda: get_shift_timeline_data("Workstation", "WS-00001"),
			),
		]

		for label, guard_name, gated_call in gated_calls:
			with self.subTest(label=label):
				with patch.object(access_control, guard_name, side_effect=frappe.PermissionError):
					with self.assertRaises(frappe.PermissionError):
						gated_call()

	def test_denied_user_cannot_call_shift_specific_gated_apis(self) -> None:
		gated_calls = [
			(
				"get_linked_downtime_entries",
				"assert_app_read_access",
				lambda: shift_module.get_linked_downtime_entries("SHIFT-00001"),
			),
			(
				"check_running_shift_conflict",
				"assert_app_read_access",
				lambda: shift_module.check_running_shift_conflict("SHIFT-00001"),
			),
			(
				"get_shift_summary",
				"assert_app_read_access",
				lambda: shift_module.get_shift_summary("SHIFT-00001"),
			),
			(
				"get_shift_aggregate_production_entries",
				"assert_app_read_access",
				lambda: shift_module.get_shift_aggregate_production_entries("SHIFT-00001"),
			),
			(
				"start_shift",
				"assert_app_write_access",
				lambda: Shift.start_shift(frappe._dict(name="SHIFT-00001")),
			),
			(
				"end_shift",
				"assert_app_write_access",
				lambda: Shift.end_shift(frappe._dict(name="SHIFT-00001")),
			),
			(
				"cancel_shift",
				"assert_app_write_access",
				lambda: Shift.cancel_shift(frappe._dict(name="SHIFT-00001")),
			),
		]

		for label, guard_name, gated_call in gated_calls:
			with self.subTest(label=label):
				with patch.object(access_control, guard_name, side_effect=frappe.PermissionError):
					with self.assertRaises(frappe.PermissionError):
						gated_call()

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

		with patch.object(access_control, "assert_app_read_access") as assert_app_read_access:
			with patch(
				"production_entry_app.production_entry_app.api.frappe.has_permission",
				return_value=False,
			) as has_permission:
				with patch(
					"production_entry_app.production_entry_app.api.frappe.get_doc", return_value=shift_doc
				):
					with self.assertRaises(frappe.PermissionError):
						get_shift_details_for_stock_entry("SHIFT-B-00001")
			assert_app_read_access.assert_called_once_with()
		has_permission.assert_called_once_with("Shift", "read", "SHIFT-B-00001")

	def test_shift_details_returns_empty_without_access_check_when_shift_is_missing(self) -> None:
		with patch.object(access_control, "assert_app_read_access") as assert_app_read_access:
			self.assertEqual(get_shift_details_for_stock_entry(""), {})
		assert_app_read_access.assert_not_called()

	def test_shift_specific_endpoints_use_target_shift_read_permission(self) -> None:
		with patch.object(access_control, "assert_app_read_access") as assert_app_read_access:
			with patch(
				"production_entry_app.production_entry_app.doctype.shift.shift.frappe.has_permission",
				return_value=False,
			) as has_permission:
				with self.assertRaises(frappe.PermissionError):
					shift_module.get_linked_downtime_entries("SHIFT-B-00001")
			assert_app_read_access.assert_called_once_with()
		has_permission.assert_called_once_with("Shift", "read", "SHIFT-B-00001")

		with patch.object(access_control, "assert_app_read_access") as assert_app_read_access:
			with patch(
				"production_entry_app.production_entry_app.doctype.shift.shift.frappe.has_permission",
				return_value=False,
			) as has_permission:
				with self.assertRaises(frappe.PermissionError):
					shift_module.check_running_shift_conflict("SHIFT-B-00001")
			assert_app_read_access.assert_called_once_with()
		has_permission.assert_called_once_with("Shift", "read", "SHIFT-B-00001")

	def test_shift_timeline_data_allows_when_user_has_required_role(self) -> None:
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

		with (
			patch(
				"production_entry_app.production_entry_app.access_control._get_access_configuration",
				return_value=access_control.AccessConfiguration(
					enabled=True,
					write_role=REQUIRED_ROLE,
					read_role=READ_ROLE,
				),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User", REQUIRED_ROLE],
			),
			patch(
				"production_entry_app.production_entry_app.api_timeline.frappe.db.get_value",
				return_value="2026-01-01 10:00:00",
			),
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
				access_control, "assert_app_read_access", wraps=access_control.assert_app_read_access
			) as guard,
		):
			result = get_shift_timeline_data("Workstation", "WS-00001")
			guard.assert_has_calls([call(), call()])
		self.assertEqual(guard.call_count, 2)
		self.assertEqual(result["shift_name"], "SHIFT-B-00001")
		self.assertEqual(result["entries"], [])
		self.assertEqual(result["float_precision"], 3)

	def test_shift_timeline_data_denies_when_user_missing_required_role(self) -> None:
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

		with (
			patch(
				"production_entry_app.production_entry_app.access_control._get_access_configuration",
				return_value=access_control.AccessConfiguration(
					enabled=True,
					write_role=REQUIRED_ROLE,
					read_role=READ_ROLE,
				),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
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
				access_control, "assert_app_read_access", wraps=access_control.assert_app_read_access
			) as guard,
		):
			with self.assertRaises(frappe.PermissionError):
				get_shift_timeline_data("Workstation", "WS-00001")
			guard.assert_called_once_with()

	def test_allowed_user_can_call_required_whitelisted_apis(self) -> None:
		with patch.object(access_control, "assert_app_read_access") as assert_app_read_access:
			with patch(
				"production_entry_app.production_entry_app.api.frappe.db.exists",
				return_value=False,
			):
				result = get_die_tool_counter("ITEM-00001")
		assert_app_read_access.assert_called_once()
		self.assertEqual(result["die_tool_code"], "ITEM-00001")

		with patch.object(access_control, "assert_app_read_access") as assert_app_read_access:
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
		assert_app_read_access.assert_called_once_with()
		self.assertEqual(
			result,
			{"shift_name": None, "entries": [], "float_precision": 3},
		)

	def test_get_access_control_state_returns_enabled_flag(self) -> None:
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
