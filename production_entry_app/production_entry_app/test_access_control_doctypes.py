from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import access_control
from production_entry_app.production_entry_app.overrides.test_stock_entry_hooks import (
	_append_rejection_breakup_rows,
	_ensure_rejection_breakup_custom_field,
	_ensure_rejection_breakup_doctype,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import ensure_department

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

DOCLEVEL_GATED_DOCTYPES: tuple[str, ...] = (
	"Shift",
	"Downtime Reason",
	"Operator",
	"Die Tool Counter",
	"Die Tool Maintenance Log",
	"Rejection Reason",
)

ALLOWED_BRANCH: str = "Allowed Branch"
DENIED_BRANCH: str = "Denied Branch"
ALLOWED_USER: str = "pea_allowed_user@example.com"
DENIED_USER: str = "pea_denied_user@example.com"
BLOGGER_USER: str = "pea_blogger_user@example.com"
USER_ROLE: str = "Manufacturing User"


class TestAccessControlDoctypes(FrappeTestCase):
	def setUp(self) -> None:
		_ensure_user_with_role(ALLOWED_USER, USER_ROLE)
		_ensure_user_with_role(DENIED_USER, USER_ROLE)
		_ensure_user_with_role(BLOGGER_USER, "Blogger")
		frappe.set_user("Administrator")
		access_control.invalidate_access_control_cache()

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_denied_user_cannot_access_all_gated_doctypes_doc_level(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_access_config(ALLOWED_BRANCH),
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch",
				return_value=DENIED_BRANCH,
			),
		):
			frappe.set_user(DENIED_USER)
			for doctype in DOCLEVEL_GATED_DOCTYPES:
				with self.subTest(doctype=doctype):
					self.assertFalse(frappe.has_permission(_make_doc(doctype, DENIED_BRANCH), ptype="read"))

	def test_denied_user_cannot_access_loss_entry_child_rows_when_shift_parent_is_denied(
		self,
	) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_access_config(ALLOWED_BRANCH),
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch",
				return_value=ALLOWED_BRANCH,
			),
		):
			frappe.set_user(DENIED_USER)
			shift, loss_entry = _make_shift_with_loss_entry(DENIED_BRANCH)
			with self.subTest(doctype="Shift"):
				self.assertFalse(frappe.has_permission(shift, ptype="read"))
			with self.subTest(doctype="Loss Entry"):
				self.assertFalse(frappe.has_permission(loss_entry, ptype="read"))

	def test_denied_user_cannot_access_rejection_breakup_child_rows_when_parent_stock_entry_is_denied(
		self,
	) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_access_config(ALLOWED_BRANCH),
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch",
				return_value=ALLOWED_BRANCH,
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Blogger"],
			),
		):
			frappe.set_user(BLOGGER_USER)
			stock_entry, rejection_breakup = _make_stock_entry_with_rejection_breakup()
			with self.subTest(doctype="Stock Entry"):
				self.assertFalse(frappe.has_permission(stock_entry, ptype="read"))
			with self.subTest(doctype="Rejection Breakup"):
				self.assertFalse(frappe.has_permission(rejection_breakup, ptype="read"))

	def test_denied_user_cannot_access_list_create_routes_for_gated_doctypes(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_access_config(ALLOWED_BRANCH),
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch",
				return_value=DENIED_BRANCH,
			),
		):
			frappe.set_user(DENIED_USER)
			for doctype in GATED_DOCTYPES:
				with self.subTest(doctype=doctype, ptype="read"):
					self.assertFalse(_call_doctype_permission_hook(doctype, ptype="read"))
				with self.subTest(doctype=doctype, ptype="create"):
					self.assertFalse(_call_doctype_permission_hook(doctype, ptype="create"))

	def test_allowed_user_can_access_all_gated_doctypes(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_access_config(ALLOWED_BRANCH),
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch",
				return_value=ALLOWED_BRANCH,
			),
		):
			frappe.set_user(ALLOWED_USER)
			for doctype in DOCLEVEL_GATED_DOCTYPES:
				with self.subTest(doctype=doctype):
					self.assertTrue(frappe.has_permission(_make_doc(doctype, ALLOWED_BRANCH), ptype="read"))
				with self.subTest(doctype=doctype, ptype="read"):
					self.assertTrue(_call_doctype_permission_hook(doctype, ptype="read"))
				with self.subTest(doctype=doctype, ptype="create"):
					self.assertTrue(_call_doctype_permission_hook(doctype, ptype="create"))
			shift, loss_entry = _make_shift_with_loss_entry(ALLOWED_BRANCH)
			with self.subTest(doctype="Shift"):
				self.assertTrue(frappe.has_permission(shift, ptype="read"))
			with self.subTest(doctype="Loss Entry"):
				self.assertTrue(frappe.has_permission(loss_entry, ptype="read"))
			stock_entry, rejection_breakup = _make_stock_entry_with_rejection_breakup()
			with self.subTest(doctype="Stock Entry"):
				self.assertTrue(frappe.has_permission(stock_entry, ptype="read"))
			with self.subTest(doctype="Rejection Breakup"):
				self.assertTrue(frappe.has_permission(rejection_breakup, ptype="read"))

	def test_system_manager_bypass_allows_all_gated_doctypes(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_access_config(ALLOWED_BRANCH),
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch",
				return_value=DENIED_BRANCH,
			),
		):
			frappe.set_user("Administrator")
			for doctype in DOCLEVEL_GATED_DOCTYPES:
				with self.subTest(doctype=doctype):
					self.assertTrue(frappe.has_permission(_make_doc(doctype, DENIED_BRANCH), ptype="read"))
				with self.subTest(doctype=doctype, ptype="read"):
					self.assertTrue(_call_doctype_permission_hook(doctype, ptype="read"))
				with self.subTest(doctype=doctype, ptype="create"):
					self.assertTrue(_call_doctype_permission_hook(doctype, ptype="create"))
			shift, loss_entry = _make_shift_with_loss_entry(DENIED_BRANCH)
			with self.subTest(doctype="Shift"):
				self.assertTrue(frappe.has_permission(shift, ptype="read"))
			with self.subTest(doctype="Loss Entry"):
				self.assertTrue(frappe.has_permission(loss_entry, ptype="read"))
			stock_entry, rejection_breakup = _make_stock_entry_with_rejection_breakup()
			with self.subTest(doctype="Stock Entry"):
				self.assertTrue(frappe.has_permission(stock_entry, ptype="read"))
			with self.subTest(doctype="Rejection Breakup"):
				self.assertTrue(frappe.has_permission(rejection_breakup, ptype="read"))


def _access_config(branch: str) -> SimpleNamespace:
	return SimpleNamespace(
		enabled=True,
		rules=((USER_ROLE, branch),),
	)


def _call_doctype_permission_hook(doctype: str, ptype: str) -> bool:
	hooks = frappe.get_hooks("has_permission")
	hook_paths = hooks.get(doctype) or []
	if isinstance(hook_paths, str):
		hook_paths = [hook_paths]
	if not hook_paths:
		raise AssertionError(f"No has_permission hook configured for {doctype}")
	hook = frappe.get_attr(hook_paths[0])
	return hook(doc=None, ptype=ptype)


def _make_shift_with_loss_entry(
	branch: str,
) -> tuple[frappe.model.document.Document, frappe.model.document.Document]:
	ensure_department("PEA Test Department")
	shift = frappe.get_doc(
		{
			"doctype": "Shift",
			"department": "PEA Test Department",
			"branch": branch,
			"shift_label": "1",
			"shift_duration": "8",
			"shift_date": "2026-04-18",
			"planned_start_time": "08:00:00",
		}
	)
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


def _make_doc(doctype: str, branch: str) -> frappe.model.document.Document:
	if doctype == "Loss Entry":
		return _make_shift_with_loss_entry(branch)[1]
	if doctype == "Rejection Breakup":
		return _make_stock_entry_with_rejection_breakup()[1]
	doc = frappe.get_doc({"doctype": doctype})
	doc.name = f"{doctype}-TEST-{branch}"
	if doctype == "Shift":
		doc.branch = branch
	elif doctype == "Downtime Reason":
		doc.downtime_reason_name = f"{doctype} {branch}"
	elif doctype == "Operator":
		doc.operator_name = f"{doctype} {branch}"
	elif doctype == "Die Tool Counter":
		doc.die_tool_item = f"{doctype} {branch}"
	elif doctype == "Die Tool Maintenance Log":
		doc.die_tool_item = f"{doctype} {branch}"
	elif doctype == "Rejection Reason":
		doc.rejection_reason_name = f"{doctype} {branch}"
	return doc


def _ensure_user_with_role(email: str, role: str) -> None:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = email.split("@", 1)[0]
		user.user_type = "System User"
	user.add_roles(role)
	user.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so role changes are visible
