from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import access_control

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

ALLOWED_BRANCH: str = "Allowed Branch"
DENIED_BRANCH: str = "Denied Branch"
ALLOWED_USER: str = "pea_allowed_user@example.com"
DENIED_USER: str = "pea_denied_user@example.com"
USER_ROLE: str = "Manufacturing User"


class TestAccessControlDoctypes(FrappeTestCase):
	def setUp(self) -> None:
		_ensure_user_with_role(ALLOWED_USER, USER_ROLE)
		_ensure_user_with_role(DENIED_USER, USER_ROLE)
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
			for doctype in GATED_DOCTYPES:
				with self.subTest(doctype=doctype):
					self.assertFalse(
						access_control.has_gated_doctype_permission(
							_make_doc(doctype, DENIED_BRANCH),
							ptype="read",
						)
					)

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
					self.assertFalse(
						access_control.has_gated_doctype_permission(doc=None, ptype="read")
					)
				with self.subTest(doctype=doctype, ptype="create"):
					self.assertFalse(
						access_control.has_gated_doctype_permission(doc=None, ptype="create")
					)

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
			for doctype in GATED_DOCTYPES:
				with self.subTest(doctype=doctype):
					self.assertTrue(
						access_control.has_gated_doctype_permission(
							_make_doc(doctype, ALLOWED_BRANCH),
							ptype="read",
						)
					)
				with self.subTest(doctype=doctype, ptype="read"):
					self.assertTrue(
						access_control.has_gated_doctype_permission(doc=None, ptype="read")
					)
				with self.subTest(doctype=doctype, ptype="create"):
					self.assertTrue(
						access_control.has_gated_doctype_permission(doc=None, ptype="create")
					)

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
			for doctype in GATED_DOCTYPES:
				with self.subTest(doctype=doctype):
					self.assertTrue(
						access_control.has_gated_doctype_permission(
							_make_doc(doctype, DENIED_BRANCH),
							ptype="read",
						)
					)
				with self.subTest(doctype=doctype, ptype="read"):
					self.assertTrue(
						access_control.has_gated_doctype_permission(doc=None, ptype="read")
					)
				with self.subTest(doctype=doctype, ptype="create"):
					self.assertTrue(
						access_control.has_gated_doctype_permission(doc=None, ptype="create")
					)


def _access_config(branch: str) -> SimpleNamespace:
	return SimpleNamespace(
		enabled=True,
		rules=((USER_ROLE, branch),),
	)


def _make_doc(doctype: str, branch: str) -> frappe.model.document.Document:
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
