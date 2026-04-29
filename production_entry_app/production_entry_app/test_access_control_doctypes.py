from __future__ import annotations

import json
from pathlib import Path
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
WRITE_PERMISSION_KEYS: tuple[str, ...] = ("create", "read", "write")
READ_ONLY_DENIED_PERMISSION_KEYS: tuple[str, ...] = ("create", "delete", "write", "submit")

DOCLEVEL_GATED_DOCTYPES: tuple[str, ...] = (
	"Shift",
	"Downtime Reason",
	"Operator",
	"Die Tool Counter",
	"Die Tool Maintenance Log",
	"Rejection Reason",
)

TEST_BRANCH: str = "PEA Test Branch"
ALLOWED_USER: str = "pea_allowed_user@example.com"
READ_ONLY_USER: str = "pea_read_only_user@example.com"
DENIED_USER: str = "pea_denied_user@example.com"
USER_ROLE: str = "Manufacturing User"
WRITE_ROLE: str = "PEA User"
READ_ROLE: str = "PEA Read Only"


class TestAccessControlDoctypes(FrappeTestCase):
	def setUp(self) -> None:
		_reload_gated_doctype_metadata()
		_ensure_user_with_roles(ALLOWED_USER, (WRITE_ROLE,))
		_ensure_user_with_roles(READ_ONLY_USER, (READ_ROLE,))
		_ensure_user_with_roles(DENIED_USER, (USER_ROLE,))
		frappe.set_user("Administrator")
		access_control.invalidate_access_control_cache()

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_role_fixture_setup_resets_dedicated_users_to_exact_roles(self) -> None:
		_ensure_user_with_roles(DENIED_USER, (WRITE_ROLE, "System Manager"))
		self.assertEqual(
			_get_user_roles(DENIED_USER),
			sorted((WRITE_ROLE, "System Manager")),
		)

		_ensure_user_with_roles(DENIED_USER, (USER_ROLE,))
		self.assertEqual(_get_user_roles(DENIED_USER), [USER_ROLE])

	def test_gated_doctype_native_permissions_use_pea_roles(self) -> None:
		for doctype in GATED_DOCTYPES:
			with self.subTest(doctype=doctype):
				permission_by_role = _get_json_permissions_by_role(doctype)
				self.assertIn(WRITE_ROLE, permission_by_role)
				for key in _write_permission_keys_for_doctype(permission_by_role["System Manager"]):
					self.assertEqual(permission_by_role[WRITE_ROLE].get(key), 1)
				self.assertIn(READ_ROLE, permission_by_role)
				self.assertEqual(permission_by_role[READ_ROLE].get("read"), 1)
				for key in READ_ONLY_DENIED_PERMISSION_KEYS:
					self.assertNotEqual(permission_by_role[READ_ROLE].get(key), 1)
				self.assertNotIn(USER_ROLE, permission_by_role)
				self.assertNotIn("Manufacturing Manager", permission_by_role)

	def test_denied_user_cannot_access_all_gated_doctypes_doc_level(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control._load_access_configuration",
			return_value=_access_config(),
		):
			frappe.set_user(DENIED_USER)
			for doctype in DOCLEVEL_GATED_DOCTYPES:
				with self.subTest(doctype=doctype):
					self.assertFalse(frappe.has_permission(_make_doc(doctype), ptype="read"))

	def test_denied_user_cannot_access_loss_entry_child_rows_when_shift_parent_is_denied(
		self,
	) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control._load_access_configuration",
			return_value=_access_config(),
		):
			frappe.set_user(DENIED_USER)
			shift, loss_entry = _make_shift_with_loss_entry()
			with self.subTest(doctype="Shift"):
				self.assertFalse(frappe.has_permission(shift, ptype="read"))
			with self.subTest(doctype="Loss Entry"):
				self.assertFalse(frappe.has_permission(loss_entry, ptype="read"))

	def test_denied_user_can_access_stock_entry_natively_but_is_blocked_on_rejection_breakup(
		self,
	) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control._load_access_configuration",
			return_value=_access_config(),
		):
			frappe.set_user(DENIED_USER)
			stock_entry, rejection_breakup = _make_stock_entry_with_rejection_breakup()
			with self.subTest(doctype="Stock Entry"):
				self.assertTrue(frappe.has_permission(stock_entry, ptype="read"))
			with self.subTest(doctype="Rejection Breakup"):
				self.assertFalse(rejection_breakup.has_permission("read", user=DENIED_USER))

	def test_denied_user_cannot_access_list_create_routes_for_gated_doctypes(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control._load_access_configuration",
			return_value=_access_config(),
		):
			frappe.set_user(DENIED_USER)
			for doctype in GATED_DOCTYPES:
				with self.subTest(doctype=doctype, ptype="read"):
					self.assertFalse(_call_doctype_permission_hook(doctype, ptype="read"))
				with self.subTest(doctype=doctype, ptype="create"):
					self.assertFalse(_call_doctype_permission_hook(doctype, ptype="create"))

	def test_read_only_user_can_read_but_cannot_create_gated_doctypes(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control._load_access_configuration",
			return_value=_access_config(),
		):
			frappe.set_user(READ_ONLY_USER)
			for doctype in DOCLEVEL_GATED_DOCTYPES:
				with self.subTest(doctype=doctype, ptype="doc_read"):
					self.assertTrue(frappe.has_permission(_make_doc(doctype), ptype="read"))
			for doctype in GATED_DOCTYPES:
				with self.subTest(doctype=doctype, ptype="read"):
					self.assertTrue(_call_doctype_permission_hook(doctype, ptype="read"))
				with self.subTest(doctype=doctype, ptype="create"):
					self.assertFalse(_call_doctype_permission_hook(doctype, ptype="create"))
			shift, loss_entry = _make_shift_with_loss_entry()
			with self.subTest(doctype="Shift", ptype="doc_read"):
				self.assertTrue(frappe.has_permission(shift, ptype="read"))
			with self.subTest(doctype="Loss Entry", ptype="doc_read"):
				self.assertTrue(frappe.has_permission(loss_entry, ptype="read"))
			stock_entry, rejection_breakup = _make_stock_entry_with_rejection_breakup()
			del stock_entry
			with self.subTest(doctype="Rejection Breakup", ptype="doc_read"):
				self.assertFalse(rejection_breakup.has_permission("read", user=READ_ONLY_USER))

	def test_rejection_breakup_requires_parent_stock_entry_access_after_app_gate(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control._load_access_configuration",
			return_value=_access_config(),
		):
			frappe.set_user(ALLOWED_USER)
			stock_entry, rejection_breakup = _make_stock_entry_with_rejection_breakup()
			del stock_entry

			self.assertFalse(rejection_breakup.has_permission("read", user=ALLOWED_USER))

	def test_allowed_user_can_access_all_gated_doctypes(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control._load_access_configuration",
			return_value=_access_config(),
		):
			frappe.set_user(ALLOWED_USER)
			for doctype in DOCLEVEL_GATED_DOCTYPES:
				with self.subTest(doctype=doctype):
					self.assertTrue(frappe.has_permission(_make_doc(doctype), ptype="read"))
				with self.subTest(doctype=doctype, ptype="read"):
					self.assertTrue(_call_doctype_permission_hook(doctype, ptype="read"))
				with self.subTest(doctype=doctype, ptype="create"):
					self.assertTrue(_call_doctype_permission_hook(doctype, ptype="create"))
			shift, loss_entry = _make_shift_with_loss_entry()
			with self.subTest(doctype="Shift"):
				self.assertTrue(frappe.has_permission(shift, ptype="read"))
			with self.subTest(doctype="Loss Entry"):
				self.assertTrue(frappe.has_permission(loss_entry, ptype="read"))
			stock_entry, rejection_breakup = _make_stock_entry_with_rejection_breakup()
			del stock_entry
			with self.subTest(doctype="Rejection Breakup"):
				self.assertFalse(rejection_breakup.has_permission("read", user=ALLOWED_USER))

	def test_system_manager_bypass_allows_all_gated_doctypes(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control._load_access_configuration",
			return_value=_access_config(),
		):
			frappe.set_user("Administrator")
			for doctype in DOCLEVEL_GATED_DOCTYPES:
				with self.subTest(doctype=doctype):
					self.assertTrue(frappe.has_permission(_make_doc(doctype), ptype="read"))
				with self.subTest(doctype=doctype, ptype="read"):
					self.assertTrue(_call_doctype_permission_hook(doctype, ptype="read"))
				with self.subTest(doctype=doctype, ptype="create"):
					self.assertTrue(_call_doctype_permission_hook(doctype, ptype="create"))
			shift, loss_entry = _make_shift_with_loss_entry()
			with self.subTest(doctype="Shift"):
				self.assertTrue(frappe.has_permission(shift, ptype="read"))
			with self.subTest(doctype="Loss Entry"):
				self.assertTrue(frappe.has_permission(loss_entry, ptype="read"))
			stock_entry, rejection_breakup = _make_stock_entry_with_rejection_breakup()
			with self.subTest(doctype="Stock Entry"):
				self.assertTrue(frappe.has_permission(stock_entry, ptype="read"))
			with self.subTest(doctype="Rejection Breakup"):
				self.assertTrue(rejection_breakup.has_permission("read", user="Administrator"))


def _access_config() -> SimpleNamespace:
	return SimpleNamespace(
		enabled=True,
		write_role=WRITE_ROLE,
		read_role=READ_ROLE,
	)


def _reload_gated_doctype_metadata() -> None:
	for doctype in GATED_DOCTYPES:
		frappe.reload_doc("production_entry_app", "doctype", frappe.scrub(doctype))
		frappe.clear_cache(doctype=doctype)


def _get_json_permissions_by_role(doctype: str) -> dict[str, dict]:
	scrubbed_doctype = frappe.scrub(doctype)
	path = Path(__file__).parent / "doctype" / scrubbed_doctype / f"{scrubbed_doctype}.json"
	doctype_schema = json.loads(path.read_text())
	return {permission["role"]: permission for permission in doctype_schema["permissions"]}


def _write_permission_keys_for_doctype(system_manager_permission: dict) -> tuple[str, ...]:
	keys = list(WRITE_PERMISSION_KEYS)
	if system_manager_permission.get("delete") == 1:
		keys.append("delete")
	if system_manager_permission.get("submit") == 1:
		keys.append("submit")
	return tuple(keys)


def _call_doctype_permission_hook(doctype: str, ptype: str) -> bool:
	hooks = frappe.get_hooks("has_permission")
	hook_paths = hooks.get(doctype) or []
	if isinstance(hook_paths, str):
		hook_paths = [hook_paths]
	if not hook_paths:
		raise AssertionError(f"No has_permission hook configured for {doctype}")
	hook = frappe.get_attr(hook_paths[0])
	return hook(doc=None, ptype=ptype)


def _make_shift_with_loss_entry() -> tuple[frappe.model.document.Document, frappe.model.document.Document]:
	ensure_department("PEA Test Department")
	shift = frappe.get_doc(
		{
			"doctype": "Shift",
			"department": "PEA Test Department",
			"branch": TEST_BRANCH,
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
	return stock_entry, stock_entry.custom_pea_rejection_breakup[0]


def _make_doc(doctype: str) -> frappe.model.document.Document:
	if doctype == "Loss Entry":
		return _make_shift_with_loss_entry()[1]
	if doctype == "Rejection Breakup":
		return _make_stock_entry_with_rejection_breakup()[1]
	doc = frappe.get_doc({"doctype": doctype})
	doc.name = f"{doctype}-TEST"
	if doctype == "Shift":
		doc.branch = TEST_BRANCH
	elif doctype == "Downtime Reason":
		doc.downtime_reason_name = f"{doctype} Test"
	elif doctype == "Operator":
		doc.operator_name = f"{doctype} Test"
	elif doctype == "Die Tool Counter":
		doc.die_tool_item = f"{doctype} Test"
	elif doctype == "Die Tool Maintenance Log":
		doc.die_tool_item = f"{doctype} Test"
	elif doctype == "Rejection Reason":
		doc.rejection_reason_name = f"{doctype} Test"
	return doc


def _ensure_user_with_roles(email: str, roles: tuple[str, ...]) -> None:
	unique_roles = tuple(dict.fromkeys(roles))
	for role in unique_roles:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = email.split("@", 1)[0]
		user.user_type = "System User"
	user.set("roles", [])
	for role in unique_roles:
		user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so role changes are visible


def _get_user_roles(email: str) -> list[str]:
	return sorted(
		frappe.get_all(
			"Has Role",
			filters={"parent": email, "parenttype": "User"},
			pluck="role",
		)
	)
