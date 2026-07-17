from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.test_bootstrap import (
	bootstrap_manufacturing_test_context,
	ensure_branch,
	ensure_department,
	resolve_test_branch,
)

PEA_READ_ONLY_STANDARD_READ_DOCTYPES: tuple[str, ...] = (
	"Page",
	"Company",
	"Stock Entry",
	"Stock Entry Detail",
	"BOM",
	"BOM Item",
	"Item",
	"Workstation",
	"Warehouse",
	"UOM",
)

PEA_READ_ONLY_ALLOWED_STANDARD_FLAGS: tuple[str, ...] = ("read", "select")

PEA_READ_ONLY_BLOCKED_STANDARD_FLAGS: tuple[str, ...] = (
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
)


def _ensure_user_with_exact_roles(email: str, roles: tuple[str, ...]) -> None:
	for role in roles:
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
	for role in roles:
		user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - role changes must be visible to permission checks
	frappe.clear_cache(user=email)


class TestNativeShiftPermissions(FrappeTestCase):
	def setUp(self) -> None:
		bootstrap_manufacturing_test_context("SHIFT-NATIVE-PERM")
		self.department = ensure_department(f"Test Department {frappe.generate_hash(length=6)}")
		self.branch = ensure_branch(resolve_test_branch() or "_Test Branch")
		frappe.defaults.set_user_default("branch", self.branch)
		frappe.defaults.set_user_default("Branch", self.branch)
		frappe.reload_doc("production_entry_app", "doctype", "shift")
		for doctype in ("Shift", *PEA_READ_ONLY_STANDARD_READ_DOCTYPES):
			frappe.clear_cache(doctype=doctype)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_pea_user_can_create_read_and_write_shift(self) -> None:
		email = f"test_native_shift_user_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(email, ("PEA User",))

		try:
			frappe.set_user(email)
			doc = self._build_shift_doc("2026-07-06", "1").insert()
			self.assertTrue(frappe.has_permission("Shift", "read", doc=doc))
			self.assertTrue(frappe.has_permission("Shift", "write", doc=doc))

			loaded = frappe.get_doc("Shift", doc.name)
			loaded.shift_duration = "10"
			loaded.save()
		finally:
			frappe.set_user("Administrator")

	def test_pea_read_only_can_read_but_cannot_write_shift(self) -> None:
		email = f"test_native_shift_readonly_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(email, ("PEA Read Only",))
		doc = self._build_shift_doc("2026-07-07", "1").insert(ignore_permissions=True)

		try:
			frappe.set_user(email)
			self.assertTrue(frappe.has_permission("Shift", "read", doc=doc))
			self.assertFalse(frappe.has_permission("Shift", "write", doc=doc))

			loaded = frappe.get_doc("Shift", doc.name)
			loaded.shift_duration = "10"
			with self.assertRaises(frappe.PermissionError):
				loaded.save()
		finally:
			frappe.set_user("Administrator")

	def test_pea_read_only_standard_docperms_are_read_select_only(self) -> None:
		for doctype in PEA_READ_ONLY_STANDARD_READ_DOCTYPES:
			rows = frappe.get_all(
				"DocPerm",
				filters={
					"parent": doctype,
					"role": "PEA Read Only",
				},
				fields=[
					"permlevel",
					"if_owner",
					*PEA_READ_ONLY_ALLOWED_STANDARD_FLAGS,
					*PEA_READ_ONLY_BLOCKED_STANDARD_FLAGS,
				],
			)
			self.assertEqual(len(rows), 1, f"{doctype} must have one PEA Read Only DocPerm row")

			row = rows[0]
			self.assertEqual(row.get("permlevel"), 0, f"{doctype}.permlevel must be 0")
			self.assertEqual(row.get("if_owner"), 0, f"{doctype}.if_owner must be 0")
			for flag in PEA_READ_ONLY_ALLOWED_STANDARD_FLAGS:
				self.assertEqual(row.get(flag), 1, f"{doctype}.{flag} must be enabled")
			for flag in PEA_READ_ONLY_BLOCKED_STANDARD_FLAGS:
				self.assertEqual(row.get(flag), 0, f"{doctype}.{flag} must stay disabled")

	def test_pea_read_only_can_read_stock_entry_but_cannot_create_it(self) -> None:
		email = f"test_native_stock_entry_readonly_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(email, ("PEA Read Only",))

		try:
			frappe.set_user(email)
			self.assertTrue(frappe.has_permission("Stock Entry", "read"))
			self.assertFalse(frappe.has_permission("Stock Entry", "create"))

			doc = frappe.get_doc(
				{
					"doctype": "Stock Entry",
					"purpose": "Manufacture",
					"stock_entry_type": "Manufacture",
				}
			)
			with self.assertRaises(frappe.PermissionError):
				doc.insert()
		finally:
			frappe.set_user("Administrator")

	def test_user_without_pea_roles_cannot_read_shift(self) -> None:
		email = f"test_native_shift_none_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(email, ("Blogger",))
		doc = self._build_shift_doc("2026-07-08", "1").insert(ignore_permissions=True)

		try:
			frappe.set_user(email)
			self.assertFalse(frappe.has_permission("Shift", "read", doc=doc))
		finally:
			frappe.set_user("Administrator")

	def _build_shift_doc(self, shift_date: str, shift_label: str) -> frappe.model.document.Document:
		return frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self.department,
				"branch": self.branch,
				"shift_label": shift_label,
				"shift_duration": "8",
				"shift_date": shift_date,
				"planned_start_time": "08:00:00",
			}
		)
