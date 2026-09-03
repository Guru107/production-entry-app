from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

PRODUCTION_ENTRY_SHIFT_SETTINGS_FIELDS: tuple[str, ...] = (
	"branch_warehouse_defaults",
	"shift_start_buffer_mins",
	"shift_end_buffer_mins",
)
TEST_GST_HSN_CODE: str = "998314"


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
		doc.gst_hsn_code = TEST_GST_HSN_CODE
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_production_entry_settings_shift_fields() -> None:
	meta = frappe.get_meta("Production Entry Settings", cached=True)
	if all(meta.has_field(fieldname) for fieldname in PRODUCTION_ENTRY_SHIFT_SETTINGS_FIELDS):
		return
	frappe.reload_doc("production_entry_app", "doctype", "branch_warehouse_default")
	frappe.reload_doc("production_entry_app", "doctype", "production_entry_settings")
	frappe.clear_document_cache("Production Entry Settings")


def set_test_branch_warehouse_defaults(company: str, branch: str, **warehouses: str | None) -> None:
	"""Update only the test's Company/Branch row; test cleanup restores the snapshot."""
	settings = frappe.get_single("Production Entry Settings")
	row = next(
		(
			row
			for row in settings.branch_warehouse_defaults
			if row.company == company and row.branch == branch
		),
		None,
	)
	if row is None:
		row = settings.append("branch_warehouse_defaults", {"company": company, "branch": branch})
	row.update(warehouses)
	settings.save(ignore_permissions=True)


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


def save_test_user(user: frappe.model.document.Document) -> None:
	"""Save a fixture user without tripping Frappe's user-creation throttle."""
	previous_in_import = frappe.flags.get("in_import")
	frappe.flags.in_import = True
	try:
		user.save(ignore_permissions=True)
	finally:
		if previous_in_import is None:
			frappe.flags.pop("in_import", None)
		else:
			frappe.flags.in_import = previous_in_import


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


def build_joint_bom_scrap_row(
	*, secondary_item_meta: Any, item_code: str, qty: float, rate: float, uom: str
) -> dict[str, Any]:
	type_field = "secondary_item_type" if secondary_item_meta.has_field("secondary_item_type") else "type"
	row = {
		type_field: "Scrap",
		"item_code": item_code,
		"qty": qty,
		"uom": uom,
		"conversion_factor": 1,
		"cost_allocation_per": 0,
		"process_loss_per": 0,
	}
	if secondary_item_meta.has_field("rate"):
		row["rate"] = rate
	else:
		row["valuation_type"] = "Manual"
		row["cost"] = flt(qty) * flt(rate)
	return row


def get_joint_bom_scrap_rate(row: Any) -> float:
	rate = row.get("rate")
	if rate is not None:
		return flt(rate, 6)
	qty = flt(row.get("stock_qty") or row.get("qty"), 6)
	return flt(flt(row.get("cost"), 6) / qty, 6) if qty else 0


def ensure_joint_test_bom(
	*,
	item_code: str,
	rm_item: str,
	scrap_items: list[tuple[str, float, float]],
	company: str,
	bom_quantity: float = 100,
	rm_qty: float = 49.125,
	is_default: bool | None = None,
) -> str:
	"""Return a submitted BOM matching the requested quantities and scrap recipe.

	ERPNext recalculates BOM Item rates from valuation during submission, so the
	input RM rate is deliberately not part of fixture identity. Fixture scrap rates
	are in Company currency, regardless of the current user's currency default.
	"""
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	for bom_name in frappe.get_all(
		"BOM",
		filters={
			"item": item_code,
			"company": company,
			"currency": company_currency,
			"is_active": 1,
			"docstatus": 1,
		},
		pluck="name",
	):
		bom = frappe.get_doc("BOM", bom_name)
		items = list(bom.get("items") or [])
		bom_scrap = list(bom.get("secondary_items") or bom.get("scrap_items") or [])
		actual_scrap = sorted(
			(
				row.get("item_code"),
				flt(row.get("stock_qty") or row.get("qty"), 6),
				get_joint_bom_scrap_rate(row),
			)
			for row in bom_scrap
			if row.get("secondary_item_type") in (None, "Scrap") and row.get("type") in (None, "Scrap")
		)
		expected_scrap = sorted((code, flt(qty, 6), flt(rate, 6)) for code, qty, rate in scrap_items)
		if (
			flt(bom.quantity, 6) == flt(bom_quantity, 6)
			and (is_default is None or int(bom.is_default or 0) == int(is_default))
			and len(items) == 1
			and items[0].get("item_code") == rm_item
			and flt(items[0].get("stock_qty") or items[0].get("qty"), 6) == flt(rm_qty, 6)
			and actual_scrap == expected_scrap
		):
			return bom.name

	values = {
		"doctype": "BOM",
		"item": item_code,
		"company": company,
		"currency": company_currency,
		"conversion_rate": 1,
		"quantity": bom_quantity,
		"is_default": int(bool(is_default)),
		"is_active": 1,
		"items": [{"item_code": rm_item, "qty": rm_qty, "rate": 50}],
	}
	if frappe.get_meta("BOM", cached=True).has_field("secondary_items"):
		secondary_item_meta = frappe.get_meta("BOM Secondary Item", cached=True)
		values["secondary_items"] = [
			build_joint_bom_scrap_row(
				secondary_item_meta=secondary_item_meta,
				item_code=scrap_item,
				qty=qty,
				rate=rate,
				uom=frappe.db.get_value("Item", scrap_item, "stock_uom"),
			)
			for scrap_item, qty, rate in scrap_items
		]
	else:
		values["scrap_items"] = [
			{"item_code": scrap_item, "stock_qty": qty, "rate": rate} for scrap_item, qty, rate in scrap_items
		]
	bom = frappe.get_doc(values).insert(ignore_permissions=True)
	bom.submit()
	return bom.name


def _attach_fiscal_year_company(fiscal_year: str, company: str | None) -> None:
	if not company:
		return
	meta = frappe.get_meta("Fiscal Year", cached=True)
	if not meta.has_field("companies"):
		return
	doc = frappe.get_doc("Fiscal Year", fiscal_year)
	if any((row.company or "") == company for row in (doc.get("companies") or [])):
		return
	doc.append("companies", {"company": company})
	doc.flags.ignore_validate_update_after_submit = True
	doc.save(ignore_permissions=True)


def ensure_fiscal_year_for_date(posting_date: str, company: str | None = None) -> None:
	date = getdate(posting_date)
	existing_fiscal_year = frappe.db.get_value(
		"Fiscal Year",
		{
			"year_start_date": ("<=", date),
			"year_end_date": (">=", date),
		},
		"name",
		order_by="year_start_date desc",
	)
	if existing_fiscal_year:
		if frappe.get_meta("Fiscal Year", cached=True).has_field("disabled"):
			frappe.db.set_value("Fiscal Year", existing_fiscal_year, "disabled", 0, update_modified=False)
		_attach_fiscal_year_company(existing_fiscal_year, company)
		return

	fiscal_year = str(date.year)
	doc = {
		"doctype": "Fiscal Year",
		"year": fiscal_year,
		"year_start_date": f"{date.year}-01-01",
		"year_end_date": f"{date.year}-12-31",
	}
	if frappe.get_meta("Fiscal Year", cached=True).has_field("disabled"):
		doc["disabled"] = 0
	if company and frappe.get_meta("Fiscal Year", cached=True).has_field("companies"):
		doc["companies"] = [{"company": company}]
	frappe.get_doc(doc).insert(ignore_permissions=True)


def ensure_stock(
	item_code: str, warehouse: str, company: str, target_qty: float, *, posting_date: str | None = None
) -> None:
	effective_posting_date = posting_date or nowdate()
	ensure_fiscal_year_for_date(effective_posting_date, company)
	actual_qty = float(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0
	)
	if actual_qty >= target_qty:
		return
	diff = target_qty - actual_qty
	doc = {
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
	if posting_date:
		doc.update({"posting_date": posting_date, "posting_time": "00:00:00", "set_posting_time": 1})
	se = frappe.get_doc(doc).insert(ignore_permissions=True)
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
	scrap_warehouse = ensure_warehouse(f"{prefix} Scrap - {abbr}", company)
	if frappe.get_meta("Warehouse", cached=True).has_field("is_rejected_warehouse"):
		frappe.db.set_value(
			"Warehouse", rejection_warehouse, "is_rejected_warehouse", 1, update_modified=False
		)
	set_test_branch_warehouse_defaults(
		company,
		branch,
		raw_material_warehouse=rm_warehouse,
		work_in_progress_warehouse=wip_warehouse,
		rejection_warehouse=rejection_warehouse,
		scrap_warehouse=scrap_warehouse,
	)
	return {
		"company": company,
		"branch": branch,
		"abbr": abbr,
		"wip_warehouse": wip_warehouse,
		"rm_warehouse": rm_warehouse,
		"fg_warehouse": fg_warehouse,
		"rejection_warehouse": rejection_warehouse,
		"scrap_warehouse": scrap_warehouse,
	}
