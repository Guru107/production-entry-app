from __future__ import annotations

import importlib
from typing import Any

import frappe
from frappe.tests.utils import FrappeTestCase

PERMISSION_HOOKS: tuple[tuple[str, str], ...] = (
	("production_entry_app.production_entry_app.doctype.operator.operator", "Operator"),
	(
		"production_entry_app.production_entry_app.doctype.die_tool_counter.die_tool_counter",
		"Die Tool Counter",
	),
	(
		"production_entry_app.production_entry_app.doctype.die_tool_maintenance_log.die_tool_maintenance_log",
		"Die Tool Maintenance Log",
	),
	(
		"production_entry_app.production_entry_app.doctype.rejection_reason.rejection_reason",
		"Rejection Reason",
	),
	("production_entry_app.production_entry_app.doctype.loss_entry.loss_entry", "Loss Entry"),
	(
		"production_entry_app.production_entry_app.doctype.rejection_breakup.rejection_breakup",
		"Rejection Breakup",
	),
)


class TestPermissionHookSignatures(FrappeTestCase):
	def test_permission_hooks_accept_user_and_debug_arguments(self) -> None:
		for module_path, doctype in PERMISSION_HOOKS:
			with self.subTest(doctype=doctype):
				importlib.import_module(module_path)
				doc = frappe.get_doc({"doctype": doctype})
				result: Any = doc.has_permission(ptype="read", user=frappe.session.user, debug=False)

				self.assertIsInstance(result, bool)
