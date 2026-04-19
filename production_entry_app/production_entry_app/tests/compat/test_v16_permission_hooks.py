"""Tests to ensure all has_permission hooks return explicit True in v16."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.overrides.test_stock_entry_hooks import (
	_append_rejection_breakup_rows,
	_ensure_rejection_breakup_custom_field,
	_ensure_rejection_breakup_doctype,
)

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
		shift = frappe.get_doc({"doctype": "Shift", "shift_date": "2026-01-01"})
		result = frappe.has_permission(shift, ptype="read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_downtime_reason_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Downtime Reason's has_permission hook must return exactly True."""
		dt = frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": "Test"})
		result = frappe.has_permission(dt, ptype="read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_operator_has_permission_returns_explicit_true(self) -> None:
		"""Operator's has_permission hook must return exactly True."""
		operator = frappe.get_doc({"doctype": "Operator", "operator_name": "Test Operator"})
		result = frappe.has_permission(operator, ptype="read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_die_tool_counter_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Die Tool Counter's has_permission hook must return exactly True."""
		dtc = frappe.get_doc({"doctype": "Die Tool Counter", "die_tool_item": "Test Item"})
		result = frappe.has_permission(dtc, ptype="read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_die_tool_maintenance_log_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Die Tool Maintenance Log's has_permission hook must return exactly True."""
		log = frappe.get_doc({"doctype": "Die Tool Maintenance Log", "die_tool_item": "Test Item"})
		result = frappe.has_permission(log, ptype="read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_rejection_reason_has_permission_returns_explicit_true(
		self,
	) -> None:
		"""Rejection Reason's has_permission hook must return exactly True."""
		rr = frappe.get_doc({"doctype": "Rejection Reason", "rejection_reason_name": "Test"})
		result = frappe.has_permission(rr, ptype="read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_loss_entry_has_permission_returns_explicit_true(self) -> None:
		"""Loss Entry's has_permission hook must return exactly True."""
		_, loss_entry = _make_shift_with_loss_entry()
		result = loss_entry.has_permission("read")
		self.assertIs(
			result,
			True,
			"has_permission must return exactly True, not a truthy value",
		)

	def test_rejection_breakup_has_permission_returns_explicit_true(self) -> None:
		"""Rejection Breakup's has_permission hook must return exactly True."""
		_, breakup = _make_stock_entry_with_rejection_breakup()
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


def _make_shift_with_loss_entry() -> tuple[frappe.model.document.Document, frappe.model.document.Document]:
	shift = frappe.get_doc({"doctype": "Shift", "shift_date": "2026-01-01"})
	shift.append(
		"planned_losses",
		{
			"downtime_reason": "Tea Break",
			"start_time": "09:00:00",
			"end_time": "09:10:00",
		},
	)
	return shift, shift.planned_losses[0]


def _make_stock_entry_with_rejection_breakup() -> (
	tuple[
		frappe.model.document.Document,
		frappe.model.document.Document,
	]
):
	_ensure_rejection_breakup_doctype()
	_ensure_rejection_breakup_custom_field()
	stock_entry = frappe.get_doc({"doctype": "Stock Entry"})
	_append_rejection_breakup_rows(
		stock_entry,
		[
			{
				"rejection_reason": "Burr",
				"qty": 1,
				"is_rework": 0,
				"remark": "Permission test",
			},
		],
	)
	return stock_entry, stock_entry.custom_rejection_breakup[0]
