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
	frappe.throw(_("No Company found for test bootstrap."))


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


def cleanup_running_shifts() -> None:
	for name in frappe.get_all("Shift", filters={"status": "Running"}, pluck="name"):
		frappe.db.set_value("Shift", name, "status", "Completed", update_modified=False)


def bootstrap_manufacturing_test_context(prefix: str) -> dict[str, Any]:
	company = resolve_test_company()
	abbr = get_company_abbr(company)
	return {
		"company": company,
		"abbr": abbr,
		"wip_warehouse": ensure_warehouse(f"{prefix} WIP - {abbr}", company),
		"rm_warehouse": ensure_warehouse(f"{prefix} RM - {abbr}", company),
		"fg_warehouse": ensure_warehouse(f"{prefix} FG - {abbr}", company),
		"rejection_warehouse": ensure_warehouse(f"{prefix} Rejection - {abbr}", company),
	}
