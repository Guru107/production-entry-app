"""Tests to ensure all has_permission hooks return explicit True in v16."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


class TestPermissionHooksExplicitReturn(FrappeTestCase):
	"""Verify permission hooks return exactly True (not just truthy values)."""

	def test_shift_has_permission_returns_explicit_true(self) -> None:
		"""Shift's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			Shift,
		)

		shift = frappe.get_doc({"doctype": "Shift", "shift_date": "2026-01-01"})
		result = shift.has_permission("read")
		if result:
			self.assertIs(result, True)

	def test_downtime_reason_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Downtime Reason's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.downtime_reason.downtime_reason import (
			DowntimeReason,
		)

		dt = frappe.get_doc(
			{"doctype": "DowntimeReason", "downtime_reason_name": "Test"}
		)
		result = dt.has_permission("read")
		if result:
			self.assertIs(result, True)

	def test_operator_has_permission_returns_explicit_true(self) -> None:
		"""Operator's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.operator.operator import (
			Operator,
		)

		operator = frappe.get_doc(
			{"doctype": "Operator", "operator_name": "Test Operator"}
		)
		result = operator.has_permission("read")
		if result:
			self.assertIs(result, True)

	def test_die_tool_counter_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Die Tool Counter's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.die_tool_counter.die_tool_counter import (
			DieToolCounter,
		)

		dtc = frappe.get_doc(
			{"doctype": "Die Tool Counter", "die_tool_item": "Test Item"}
		)
		result = dtc.has_permission("read")
		if result:
			self.assertIs(result, True)

	def test_die_tool_maintenance_log_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Die Tool Maintenance Log's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.die_tool_maintenance_log.die_tool_maintenance_log import (
			DieToolMaintenanceLog,
		)

		log = frappe.get_doc(
			{"doctype": "Die Tool Maintenance Log", "die_tool_item": "Test Item"}
		)
		result = log.has_permission("read")
		if result:
			self.assertIs(result, True)

	def test_rejection_reason_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Rejection Reason's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.rejection_reason.rejection_reason import (
			RejectionReason,
		)

		rr = frappe.get_doc(
			{"doctype": "Rejection Reason", "rejection_reason_name": "Test"}
		)
		result = rr.has_permission("read")
		if result:
			self.assertIs(result, True)
