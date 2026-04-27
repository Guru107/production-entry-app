from __future__ import annotations

from typing import Any

import frappe
from frappe import _

_PRODUCTION_ENTRY_SHIFT_SETTINGS_FIELDS: tuple[str, ...] = (
	"shift_raw_material_warehouse",
	"shift_wip_warehouse",
	"shift_rejection_warehouse",
	"shift_scrap_warehouse",
	"shift_start_buffer_mins",
	"shift_end_buffer_mins",
)


def _resolve_company_from_candidates(
	test_company_exists: bool, default_company: str | None, default_exists: bool, first_company: str | None
) -> str | None:
	if test_company_exists:
		return "_Test Company"
	if default_company and default_exists:
		return default_company
	return first_company


def resolve_test_company() -> str:
	default_company = frappe.db.get_single_value("Global Defaults", "default_company")
	company = _resolve_company_from_candidates(
		test_company_exists=bool(frappe.db.exists("Company", "_Test Company")),
		default_company=default_company,
		default_exists=bool(default_company and frappe.db.exists("Company", default_company)),
		first_company=frappe.db.get_value("Company", {}, "name", order_by="creation asc"),
	)
	if company:
		return company
	frappe.throw(
		_(
			"No Company found for test bootstrap. Ensure ERPNext fixtures are installed and run "
			"`production_entry_app.production_entry_app.utils.test_setup.before_tests`."
		)
	)


def get_company_abbr(company: str) -> str:
	return frappe.db.get_value("Company", company, "abbr") or "_TC"


def resolve_test_branch() -> str | None:
	for key in ("branch", "Branch"):
		branch = frappe.defaults.get_user_default(key)
		if branch and frappe.db.exists("Branch", branch):
			return branch
	return frappe.db.get_value("Branch", {}, "name", order_by="creation asc")


def ensure_branch(name: str) -> str:
	if frappe.db.exists("Branch", name):
		return name
	return frappe.get_doc({"doctype": "Branch", "branch": name}).insert(ignore_permissions=True).name


def ensure_department(name: str, company: str | None = None) -> str:
	"""Ensure a Department exists; return its name (doc name, which may differ from department_name)."""
	if frappe.db.exists("Department", name):
		return name
	company = company or resolve_test_company()
	# Department may autoname as "department_name - company_abbr"; check by department_name
	meta = frappe.get_meta("Department", cached=True)
	filters: dict[str, str] = {"department_name": name}
	if meta.has_field("company") and company:
		filters["company"] = company
	existing = frappe.get_all(
		"Department",
		filters=filters,
		limit=1,
		pluck="name",
	)
	if existing:
		return existing[0]
	kwargs: dict[str, Any] = {"doctype": "Department", "department_name": name}
	if meta.has_field("company") and company:
		kwargs["company"] = company
	doc = frappe.get_doc(kwargs)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_warehouse(warehouse_name: str, company: str) -> str:
	if frappe.db.exists("Warehouse", warehouse_name):
		return warehouse_name

	doc = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": warehouse_name.split(" - ")[0],
			"company": company,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_item(item_code: str, *, item_group: str = "Products", stock_uom: str = "Nos") -> str:
	if frappe.db.exists("Item", item_code):
		return item_code

	if not frappe.db.exists("Item Group", item_group):
		item_group = "All Item Groups"

	doc = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"stock_uom": stock_uom,
			"is_stock_item": 1,
			"valuation_rate": 100,
			"item_group": item_group,
		}
	)
	if frappe.get_meta("Item", cached=True).has_field("gst_hsn_code"):
		doc.gst_hsn_code = "998314"
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_production_entry_settings_shift_fields() -> None:
	meta = frappe.get_meta("Production Entry Settings", cached=True)
	if all(meta.has_field(fieldname) for fieldname in _PRODUCTION_ENTRY_SHIFT_SETTINGS_FIELDS):
		return
	frappe.reload_doc("production_entry_app", "doctype", "production_entry_settings")
	frappe.clear_document_cache("Production Entry Settings")


def ensure_rejection_reason(name: str) -> None:
	if frappe.db.exists("Rejection Reason", name):
		return
	frappe.get_doc({"doctype": "Rejection Reason", "rejection_reason_name": name}).insert(
		ignore_permissions=True
	)


def ensure_downtime_reason(name: str) -> None:
	if frappe.db.exists("Downtime Reason", name):
		if frappe.get_meta("Downtime Reason", cached=True).has_field("is_active"):
			frappe.db.set_value("Downtime Reason", name, "is_active", 1, update_modified=False)
		return
	doc = {"doctype": "Downtime Reason", "downtime_reason_name": name}
	if frappe.get_meta("Downtime Reason", cached=True).has_field("is_active"):
		doc["is_active"] = 1
	frappe.get_doc(doc).insert(ignore_permissions=True)


def ensure_operator(name: str) -> None:
	if frappe.db.exists("Operator", name):
		return
	frappe.get_doc({"doctype": "Operator", "operator_name": name, "is_active": 1}).insert(
		ignore_permissions=True
	)


def ensure_workstation(name: str, standard_spm: float) -> None:
	if frappe.db.exists("Workstation", name):
		frappe.db.set_value(
			"Workstation", name, "custom_pea_standard_spm", standard_spm, update_modified=False
		)
		return
	frappe.get_doc(
		{
			"doctype": "Workstation",
			"workstation_name": name,
			"production_capacity": 1,
			"hour_rate": 100,
			"custom_pea_standard_spm": standard_spm,
		}
	).insert(ignore_permissions=True)


def ensure_default_bom(fg_item: str, rm_item: str, company: str) -> str:
	existing = frappe.db.get_value(
		"BOM",
		{"item": fg_item, "company": company, "is_default": 1, "is_active": 1, "docstatus": 1},
		"name",
	)
	if existing:
		return existing

	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"item": fg_item,
			"company": company,
			"quantity": 1,
			"is_default": 1,
			"is_active": 1,
			"items": [{"item_code": rm_item, "qty": 1, "rate": 50}],
		}
	).insert(ignore_permissions=True)
	bom.submit()
	return bom.name


def ensure_stock(item_code: str, warehouse: str, company: str, target_qty: float) -> None:
	actual_qty = float(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0
	)
	if actual_qty >= target_qty:
		return
	diff = target_qty - actual_qty
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Receipt",
			"purpose": "Material Receipt",
			"company": company,
			"to_warehouse": warehouse,
			"items": [
				{
					"item_code": item_code,
					"qty": diff,
					"t_warehouse": warehouse,
					"basic_rate": 50,
				}
			],
		}
	).insert(ignore_permissions=True)
	se.submit()


def cleanup_running_shifts() -> None:
	for name in frappe.get_all("Shift", filters={"status": "Running"}, pluck="name"):
		frappe.db.set_value("Shift", name, "status", "Completed", update_modified=False)


def bootstrap_manufacturing_test_context(prefix: str) -> dict[str, Any]:
	ensure_production_entry_settings_shift_fields()
	company = resolve_test_company()
	abbr = get_company_abbr(company)
	branch = ensure_branch(resolve_test_branch() or "_Test Branch")
	wip_warehouse = ensure_warehouse(f"{prefix} WIP - {abbr}", company)
	rm_warehouse = ensure_warehouse(f"{prefix} RM - {abbr}", company)
	fg_warehouse = ensure_warehouse(f"{prefix} FG - {abbr}", company)
	rejection_warehouse = ensure_warehouse(f"{prefix} Rejection - {abbr}", company)
	if frappe.get_meta("Warehouse", cached=True).has_field("is_rejected_warehouse"):
		frappe.db.set_value(
			"Warehouse", rejection_warehouse, "is_rejected_warehouse", 1, update_modified=False
		)
	frappe.db.set_single_value("Production Entry Settings", "shift_raw_material_warehouse", rm_warehouse)
	frappe.db.set_single_value("Production Entry Settings", "shift_wip_warehouse", wip_warehouse)
	frappe.db.set_single_value("Production Entry Settings", "shift_rejection_warehouse", rejection_warehouse)
	frappe.clear_document_cache("Production Entry Settings")
	return {
		"company": company,
		"branch": branch,
		"abbr": abbr,
		"wip_warehouse": wip_warehouse,
		"rm_warehouse": rm_warehouse,
		"fg_warehouse": fg_warehouse,
		"rejection_warehouse": rejection_warehouse,
	}
