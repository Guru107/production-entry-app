from __future__ import annotations

import frappe

STANDARD_DEPENDENCIES = (
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

STANDARD_REPORT_FILTERS = ("Fiscal Year", "BOM", "Item", "Workstation")

MODULE_BLOCKED_DOCTYPES = (
	"Die Tool Counter",
	"Die Tool Maintenance Log",
	"Downtime Reason",
	"Loss Entry",
	"Production Entry Settings",
	"Rejection Breakup",
	"Rejection Reason",
)

MODULE_DEPENDENCIES = (*MODULE_BLOCKED_DOCTYPES, "Operator", "Shift")

READ_ONLY_ALLOWED_DOCTYPES = (*STANDARD_REPORT_FILTERS, "Operator", "Shift")

STANDARD_PERMISSION_NAMES = {
	"Fiscal Year": "pea-read-only-fiscal-year",
	"BOM": "pea-read-only-bom",
	"Item": "pea-read-only-item",
	"Workstation": "pea-read-only-workstation",
}

BLOCKED_FLAGS = {
	"read": 0,
	"write": 0,
	"create": 0,
	"delete": 0,
	"submit": 0,
	"cancel": 0,
	"amend": 0,
	"report": 0,
	"export": 0,
	"import": 0,
	"share": 0,
	"print": 0,
	"email": 0,
}

PERMISSION_FIELDS = (
	"permlevel",
	"if_owner",
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
	"select",
)


def execute() -> None:
	frappe.db.delete(
		"Custom DocPerm",
		{
			"role": "PEA User",
			"parent": ["in", (*STANDARD_DEPENDENCIES, *MODULE_DEPENDENCIES)],
		},
	)
	frappe.db.delete("Custom DocPerm", {"role": "PEA Read Only"})
	frappe.db.delete(
		"DocPerm",
		{"role": "PEA User", "parent": ["in", STANDARD_DEPENDENCIES]},
	)
	frappe.db.delete(
		"DocPerm",
		{"role": "PEA Read Only", "parent": ["not in", READ_ONLY_ALLOWED_DOCTYPES]},
	)

	for doctype in STANDARD_REPORT_FILTERS:
		_set_report_filter_permission(doctype)
	_set_report_filter_permission("Operator")
	_set_report_filter_permission("Shift", report=1)
	_sync_pea_custom_permissions()
	frappe.clear_cache()


def _set_report_filter_permission(doctype: str, *, report: int = 0) -> None:
	names = frappe.get_all(
		"DocPerm",
		filters={"parent": doctype, "role": "PEA Read Only"},
		pluck="name",
	)
	preferred_name = STANDARD_PERMISSION_NAMES.get(doctype)
	if preferred_name:
		if preferred_name not in names:
			frappe.db.delete("DocPerm", {"name": ["in", names]})
			permission = frappe.get_doc(
				{
					"doctype": "DocPerm",
					"name": preferred_name,
					"parent": doctype,
					"parentfield": "permissions",
					"parenttype": "DocType",
					"role": "PEA Read Only",
				}
			)
			permission.flags.name_set = True
			permission.insert(ignore_permissions=True)
			names = [permission.name]
		target_name = preferred_name
	else:
		if not names:
			permission = frappe.get_doc(
				{
					"doctype": "DocPerm",
					"parent": doctype,
					"parentfield": "permissions",
					"parenttype": "DocType",
					"role": "PEA Read Only",
				}
			).insert(ignore_permissions=True)
			names = [permission.name]
		target_name = names[0]

	frappe.db.set_value(
		"DocPerm",
		target_name,
		{
			"permlevel": 0,
			"if_owner": 0,
			"select": 1,
			**BLOCKED_FLAGS,
			"report": report,
		},
		update_modified=False,
	)
	extra_names = [name for name in names if name != target_name]
	if extra_names:
		frappe.db.delete("DocPerm", {"name": ["in", extra_names]})


def _sync_pea_custom_permissions() -> None:
	for doctype in (*STANDARD_DEPENDENCIES, *MODULE_DEPENDENCIES):
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			continue
		for role in ("PEA User", "PEA Read Only"):
			for permission in frappe.get_all(
				"DocPerm",
				filters={"parent": doctype, "role": role},
				fields=PERMISSION_FIELDS,
			):
				frappe.get_doc(
					{
						"doctype": "Custom DocPerm",
						"parent": doctype,
						"parentfield": "permissions",
						"parenttype": "DocType",
						"role": role,
						**permission,
					}
				).insert(ignore_permissions=True)
