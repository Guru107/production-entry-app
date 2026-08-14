from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.test_bootstrap import (
	bootstrap_manufacturing_test_context,
	ensure_branch,
	ensure_department,
	resolve_test_branch,
	save_test_user,
)

PEA_STANDARD_DEPENDENCY_DOCTYPES: tuple[str, ...] = (
	"Page",
	"Company",
	"Fiscal Year",
	"Stock Entry",
	"Stock Entry Detail",
	"Stock Settings",
	"BOM",
	"BOM Item",
	"Item",
	"Workstation",
	"Warehouse",
	"UOM",
	"Downtime Entry",
)

PEA_REPORT_FILTER_STANDARD_DOCTYPES: tuple[str, ...] = (
	"Fiscal Year",
	"BOM",
	"Item",
	"Workstation",
)

PEA_REPORT_FILTER_MODULE_DOCTYPES: tuple[str, ...] = ("Operator", "Shift")

PEA_READ_ONLY_ALLOWED_DOCTYPES: tuple[str, ...] = (
	*PEA_REPORT_FILTER_STANDARD_DOCTYPES,
	*PEA_REPORT_FILTER_MODULE_DOCTYPES,
)

PEA_READ_ONLY_BLOCKED_MODULE_DOCTYPES: tuple[str, ...] = (
	"Die Tool Counter",
	"Die Tool Maintenance Log",
	"Downtime Reason",
	"Loss Entry",
	"Production Entry Settings",
	"Rejection Breakup",
	"Rejection Reason",
)

PEA_READ_ONLY_BLOCKED_FLAGS: tuple[str, ...] = (
	"read",
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
	save_test_user(user)
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
		for doctype in ("Shift", *PEA_STANDARD_DEPENDENCY_DOCTYPES):
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

	def test_pea_read_only_can_report_but_cannot_read_shift(self) -> None:
		from frappe.desk.search import search_link

		email = f"test_native_shift_readonly_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(email, ("PEA Read Only",))
		doc = self._build_shift_doc("2026-07-07", "1").insert(ignore_permissions=True)

		try:
			frappe.set_user(email)
			self.assertTrue(frappe.has_permission("Shift", "report"))
			for doctype in (*PEA_REPORT_FILTER_STANDARD_DOCTYPES, *PEA_REPORT_FILTER_MODULE_DOCTYPES):
				self.assertTrue(frappe.only_has_select_perm(doctype), f"{doctype} must be select-only")
				self.assertFalse(frappe.has_permission(doctype, "read"), f"{doctype}.read must be denied")
				self.assertIsInstance(
					search_link(doctype, "", page_length=1, reference_doctype="Shift"),
					list,
				)
			self.assertFalse(frappe.has_permission("Shift", "read", doc=doc))
			self.assertFalse(frappe.has_permission("Shift", "write", doc=doc))
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("Shift", doc.name).check_permission("read")
		finally:
			frappe.set_user("Administrator")

	def test_pea_read_only_standard_docperms_are_filter_select_only(self) -> None:
		for doctype in PEA_STANDARD_DEPENDENCY_DOCTYPES:
			rows = frappe.get_all(
				"DocPerm",
				filters={"parent": doctype, "role": ["in", ["PEA User", "PEA Read Only"]]},
				fields=["role", "permlevel", "if_owner", "select", *PEA_READ_ONLY_BLOCKED_FLAGS],
			)
			if doctype not in PEA_REPORT_FILTER_STANDARD_DOCTYPES:
				self.assertEqual(rows, [], f"{doctype} must not grant a PEA standard DocPerm")
				continue

			self.assertEqual(len(rows), 1, f"{doctype} must have one PEA Read Only DocPerm row")
			row = rows[0]
			self.assertEqual(row.get("role"), "PEA Read Only")
			self.assertEqual(row.get("permlevel"), 0)
			self.assertEqual(row.get("if_owner"), 0)
			self.assertEqual(row.get("select"), 1, f"{doctype}.select must be enabled")
			for flag in PEA_READ_ONLY_BLOCKED_FLAGS:
				self.assertEqual(row.get(flag), 0, f"{doctype}.{flag} must stay disabled")

	def test_pea_custom_permission_overrides_match_source_permissions(self) -> None:
		parents = (
			*PEA_STANDARD_DEPENDENCY_DOCTYPES,
			*PEA_REPORT_FILTER_MODULE_DOCTYPES,
			*PEA_READ_ONLY_BLOCKED_MODULE_DOCTYPES,
		)
		custom_rows = frappe.get_all(
			"Custom DocPerm",
			filters={
				"parent": ["in", parents],
				"role": ["in", ["PEA User", "PEA Read Only"]],
			},
			fields=["parent", "role", "read", "select", "report", "write", "create", "delete"],
		)
		for custom_row in custom_rows:
			source_rows = frappe.get_all(
				"DocPerm",
				filters={"parent": custom_row.parent, "role": custom_row.role},
				fields=["read", "select", "report", "write", "create", "delete"],
			)
			self.assertEqual(len(source_rows), 1)
			self.assertEqual(source_rows[0], {key: custom_row.get(key) for key in source_rows[0]})

	def test_pea_read_only_module_access_is_limited_to_report_filters(self) -> None:
		for doctype in (*PEA_REPORT_FILTER_MODULE_DOCTYPES, *PEA_READ_ONLY_BLOCKED_MODULE_DOCTYPES):
			frappe.reload_doc("production_entry_app", "doctype", frappe.scrub(doctype))
			rows = frappe.get_all(
				"DocPerm",
				filters={"parent": doctype, "role": "PEA Read Only"},
				fields=["read", "select", "report"],
			)
			if doctype in PEA_REPORT_FILTER_MODULE_DOCTYPES:
				self.assertEqual(len(rows), 1, f"{doctype} must have one PEA Read Only row")
				self.assertEqual(rows[0].get("read"), 0, f"{doctype}.read must stay disabled")
				self.assertEqual(rows[0].get("select"), 1, f"{doctype}.select must be enabled")
				self.assertEqual(rows[0].get("report"), int(doctype == "Shift"))
			else:
				self.assertEqual(rows, [], f"{doctype} must not grant PEA Read Only access")

	def test_pea_read_only_can_access_all_app_reports(self) -> None:
		from frappe.desk.query_report import get_report_doc

		email = f"test_native_reports_readonly_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(email, ("PEA Read Only",))
		report_names = frappe.get_all(
			"Report",
			filters={"module": "Production Entry App", "is_standard": "Yes", "disabled": 0},
			pluck="name",
		)
		self.assertEqual(len(report_names), 18)
		shift_report_names = frappe.get_all(
			"Report",
			filters={"ref_doctype": "Shift", "disabled": 0},
			pluck="name",
		)
		self.assertEqual(set(shift_report_names), set(report_names))
		permission_doctypes = set(
			frappe.get_all(
				"DocPerm",
				filters={"role": "PEA Read Only"},
				pluck="parent",
			)
		)
		self.assertEqual(permission_doctypes, set(PEA_READ_ONLY_ALLOWED_DOCTYPES))
		custom_permission_doctypes = set(
			frappe.get_all(
				"Custom DocPerm",
				filters={"role": "PEA Read Only"},
				pluck="parent",
			)
		)
		self.assertTrue(custom_permission_doctypes.issubset(permission_doctypes))
		report_doctypes = set(
			frappe.get_all(
				"DocPerm",
				filters={"role": "PEA Read Only", "report": 1},
				pluck="parent",
			)
		)
		report_doctypes.update(
			frappe.get_all(
				"Custom DocPerm",
				filters={"role": "PEA Read Only", "report": 1},
				pluck="parent",
			)
		)
		self.assertEqual(report_doctypes, {"Shift"})

		try:
			frappe.set_user(email)
			for report_name in report_names:
				self.assertEqual(get_report_doc(report_name).name, report_name)
		finally:
			frappe.set_user("Administrator")

	def test_pea_read_only_cannot_read_or_create_stock_entry(self) -> None:
		email = f"test_native_stock_entry_readonly_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(email, ("PEA Read Only",))

		try:
			frappe.set_user(email)
			self.assertFalse(frappe.has_permission("Stock Entry", "read"))
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
