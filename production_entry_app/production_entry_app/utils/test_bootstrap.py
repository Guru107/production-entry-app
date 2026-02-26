from __future__ import annotations

from typing import Any

import frappe
from frappe import _


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
	doc.insert(ignore_permissions=True)
	return doc.name


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
		frappe.db.set_value("Workstation", name, "custom_standard_spm", standard_spm, update_modified=False)
		return
	frappe.get_doc(
		{
			"doctype": "Workstation",
			"workstation_name": name,
			"production_capacity": 1,
			"hour_rate": 100,
			"custom_standard_spm": standard_spm,
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
	company = resolve_test_company()
	abbr = get_company_abbr(company)
	rejection_warehouse = ensure_warehouse(f"{prefix} Rejection - {abbr}", company)
	if frappe.get_meta("Warehouse", cached=True).has_field("is_rejected_warehouse"):
		frappe.db.set_value(
			"Warehouse", rejection_warehouse, "is_rejected_warehouse", 1, update_modified=False
		)
	return {
		"company": company,
		"abbr": abbr,
		"wip_warehouse": ensure_warehouse(f"{prefix} WIP - {abbr}", company),
		"rm_warehouse": ensure_warehouse(f"{prefix} RM - {abbr}", company),
		"fg_warehouse": ensure_warehouse(f"{prefix} FG - {abbr}", company),
		"rejection_warehouse": rejection_warehouse,
	}
