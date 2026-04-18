"""Tests to ensure all has_permission hooks return explicit True in v16."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

GATED_DOCTYPES: tuple[str, ...] = (
	"Shift",
	"Loss Entry",
	"Downtime Reason",
	"Operator",
	"Die Tool Counter",
	"Die Tool Maintenance Log",
	"Rejection Reason",
	"Rejection Breakup",
)


class TestPermissionHooksExplicitReturn(FrappeTestCase):
	"""Verify permission hooks return exactly True (not just truthy values).

	These tests run as Administrator, so has_permission("read") should always
	return True. The assertion checks that the return value is exactly True
	(v16 requirement) rather than just truthy.
	"""

	def test_shift_has_permission_returns_explicit_true(self) -> None:
		"""Shift's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			Shift,
		)

		shift = frappe.get_doc({"doctype": "Shift", "shift_date": "2026-01-01"})
		result = shift.has_permission("read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_downtime_reason_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Downtime Reason's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.downtime_reason.downtime_reason import (
			DowntimeReason,
		)

		dt = frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": "Test"})
		result = dt.has_permission("read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_operator_has_permission_returns_explicit_true(self) -> None:
		"""Operator's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.operator.operator import (
			Operator,
		)

		operator = frappe.get_doc({"doctype": "Operator", "operator_name": "Test Operator"})
		result = operator.has_permission("read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_die_tool_counter_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Die Tool Counter's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.die_tool_counter.die_tool_counter import (
			DieToolCounter,
		)

		dtc = frappe.get_doc({"doctype": "Die Tool Counter", "die_tool_item": "Test Item"})
		result = dtc.has_permission("read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_die_tool_maintenance_log_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Die Tool Maintenance Log's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.die_tool_maintenance_log.die_tool_maintenance_log import (
			DieToolMaintenanceLog,
		)

		log = frappe.get_doc({"doctype": "Die Tool Maintenance Log", "die_tool_item": "Test Item"})
		result = log.has_permission("read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_rejection_reason_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Rejection Reason's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.rejection_reason.rejection_reason import (
			RejectionReason,
		)

		rr = frappe.get_doc({"doctype": "Rejection Reason", "rejection_reason_name": "Test"})
		result = rr.has_permission("read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_loss_entry_has_permission_returns_explicit_true(self) -> None:
		"""Loss Entry's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.loss_entry.loss_entry import (
			LossEntry,
		)

		loss_entry = frappe.get_doc({"doctype": "Loss Entry"})
		result = loss_entry.has_permission("read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_rejection_breakup_has_permission_returns_explicit_true(self) -> None:
		"""Rejection Breakup's has_permission hook must return exactly True."""
		from production_entry_app.production_entry_app.doctype.rejection_breakup.rejection_breakup import (
			RejectionBreakup,
		)

		breakup = frappe.get_doc({"doctype": "Rejection Breakup"})
		result = breakup.has_permission("read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_gated_doctype_hooks_return_explicit_true_for_doctype_level(self) -> None:
		"""Configured has_permission hooks must return exactly True for doc=None paths."""
		for doctype in GATED_DOCTYPES:
			with self.subTest(doctype=doctype):
				hook = self._get_doctype_hook(doctype)
				result = hook(doc=None, ptype="read")
				self.assertIs(
					result,
					True,
					"doctype-level has_permission hook must return exactly True, not a truthy value",
				)

	def _get_doctype_hook(self, doctype: str):
		hooks = frappe.get_hooks("has_permission")
		hook_paths = hooks.get(doctype) or []
		if isinstance(hook_paths, str):
			hook_paths = [hook_paths]
		self.assertTrue(hook_paths, f"No has_permission hook configured for {doctype}")
		return frappe.get_attr(hook_paths[0])
