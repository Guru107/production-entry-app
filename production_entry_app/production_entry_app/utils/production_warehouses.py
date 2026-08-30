from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe import _
from frappe.model.base_document import BaseDocument

WAREHOUSE_FIELDS: tuple[str, ...] = (
	"raw_material_warehouse",
	"work_in_progress_warehouse",
	"rejection_warehouse",
	"scrap_warehouse",
)


def validate_warehouse_companies(rows: Iterable[BaseDocument | dict]) -> None:
	"""Validate all configured warehouses with one lookup, including settings child rows."""
	assignments = [
		(row.get(fieldname), row.get("company"))
		for row in rows
		for fieldname in (*WAREHOUSE_FIELDS, "from_warehouse", "to_warehouse")
		if row.get(fieldname)
	]
	if not assignments:
		return
	companies = dict(
		frappe.get_all(
			"Warehouse",
			filters={"name": ["in", list({name for name, _company in assignments})]},
			fields=["name", "company"],
			as_list=True,
		)
	)
	for warehouse, company in assignments:
		if not company or companies.get(warehouse) != company:
			frappe.throw(
				_("Warehouse {0} must belong to Company {1}.").format(
					frappe.utils.escape_html(warehouse),
					frappe.utils.escape_html(company or ""),
				)
			)


def get_branch_warehouse_defaults(company: str | None, branch: str | None) -> dict:
	if not company or not branch:
		return {}
	return (
		frappe.db.get_value(
			"Branch Warehouse Default",
			{
				"parent": "Production Entry Settings",
				"parenttype": "Production Entry Settings",
				"parentfield": "branch_warehouse_defaults",
				"company": company,
				"branch": branch,
			},
			list(WAREHOUSE_FIELDS),
			as_dict=True,
		)
		or {}
	)


def get_shift_warehouses(shift: BaseDocument) -> dict:
	defaults = get_branch_warehouse_defaults(shift.get("company"), shift.get("branch"))
	warehouses = {field: shift.get(field) or defaults.get(field) for field in WAREHOUSE_FIELDS}
	validate_warehouse_companies([{"company": shift.get("company"), **warehouses}])
	return warehouses


def get_production_warehouses(doc: BaseDocument) -> dict:
	"""Explicit Shift values precede Company/Branch defaults; there is no global fallback."""
	if doc.get("custom_pea_shift"):
		shift = frappe.get_doc("Shift", doc.get("custom_pea_shift"))
		if shift.company != doc.get("company"):
			frappe.throw(_("Stock Entry Company must match the selected Shift Company."))
		return get_shift_warehouses(shift)
	return get_shift_warehouses(doc)


def require_warehouse(warehouses: dict, fieldname: str) -> str:
	warehouse = warehouses.get(fieldname)
	if not warehouse:
		labels = {
			"raw_material_warehouse": _("Raw Material Warehouse"),
			"work_in_progress_warehouse": _("Work In Progress Warehouse"),
			"rejection_warehouse": _("Rejection Warehouse"),
			"scrap_warehouse": _("Scrap Warehouse"),
		}
		frappe.throw(
			_(
				"Please set a {0} on the Shift or in Production Entry Settings for this Company and Branch."
			).format(labels[fieldname])
		)
	return warehouse


def set_production_header_warehouses(doc: BaseDocument, warehouses: dict) -> None:
	"""Prepare a Fetch Items document, checking native access after resolving defaults."""
	for fieldname in ("from_warehouse", "to_warehouse"):
		if not doc.get(fieldname):
			doc.set(fieldname, require_warehouse(warehouses, "work_in_progress_warehouse"))
	validate_warehouse_companies([doc])
	for warehouse in {doc.get("from_warehouse"), doc.get("to_warehouse")}:
		if not frappe.has_permission("Warehouse", "read", warehouse):
			frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
