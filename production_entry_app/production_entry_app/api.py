from __future__ import annotations

import datetime
import json

import frappe
from frappe import _
from frappe.utils import add_to_date
from frappe.utils import get_datetime, get_time, now_datetime

from production_entry_app.production_entry_app.utils.die_tool_counter import (
	_get_or_create_counter,
	get_counter_health,
)
from production_entry_app.production_entry_app.utils.shift_time import get_shift_planned_end_datetime
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	ensure_item,
	ensure_warehouse,
	resolve_test_company,
)


@frappe.whitelist()
def get_shift_details_for_stock_entry(shift_name: str) -> dict:
	"""Return shift details to auto-populate Stock Entry fields.

	Called from the Stock Entry client script when custom_shift is set.
	"""
	if not shift_name:
		return {}

	shift = frappe.get_doc("Shift", shift_name)

	planned_start = None
	if shift.shift_date and shift.planned_start_time:
		planned_start = datetime.datetime.combine(
			frappe.utils.getdate(shift.shift_date),
			get_time(shift.planned_start_time),
		)

	planned_end = None
	planned_end = get_shift_planned_end_datetime(
		shift_date=shift.shift_date,
		planned_start_time=shift.planned_start_time,
		planned_end_time=shift.planned_end_time,
		shift_end_date=shift.shift_end_date,
		shift_duration=shift.shift_duration,
	)

	return {
		"branch": shift.branch,
		"custom_planned_start_date": str(planned_start) if planned_start else None,
		"custom_planned_end_date": str(planned_end) if planned_end else None,
		"from_warehouse": shift.work_in_progress_warehouse,
		"to_warehouse": shift.work_in_progress_warehouse,
	}


@frappe.whitelist()
def get_items_with_rejection(doc: str) -> list[dict]:
	"""Populate BOM items and apply rejection logic, returning the items list.

	Called from the Stock Entry "Get Items" button.  Accepts the Stock Entry
	doc as a JSON string, builds a clean Stock Entry, calls ERPNext's
	``get_items()`` to fetch BOM rows, then applies our rejection-entry logic
	so the user sees the final items (including the rejection row) *before*
	saving.
	"""
	from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
		_apply_rejection_entries,
	)

	doc_dict = json.loads(doc) if isinstance(doc, str) else doc

	# Build a clean SE with only the fields get_items() needs.
	# Avoids issues when the browser sends the full frm.doc with child
	# tables, metadata, and __islocal / __unsaved flags.
	se = frappe.new_doc("Stock Entry")
	se.purpose = doc_dict.get("purpose", "Manufacture")
	se.stock_entry_type = doc_dict.get("stock_entry_type", "Manufacture")
	se.company = doc_dict.get("company")
	se.from_bom = 1
	se.bom_no = doc_dict.get("bom_no")
	se.fg_completed_qty = float(doc_dict.get("fg_completed_qty") or 0)
	se.use_multi_level_bom = doc_dict.get("use_multi_level_bom", 0)
	se.from_warehouse = doc_dict.get("from_warehouse")
	se.to_warehouse = doc_dict.get("to_warehouse")
	se.posting_date = doc_dict.get("posting_date") or frappe.utils.nowdate()
	se.posting_time = doc_dict.get("posting_time") or frappe.utils.nowtime()
	se.custom_rejection_qty = float(doc_dict.get("custom_rejection_qty") or 0)
	se.custom_shift = doc_dict.get("custom_shift")
	se.work_order = doc_dict.get("work_order")

	se.get_items()
	_apply_rejection_entries(se)

	# Return only data fields — exclude Frappe metadata that would corrupt
	# client-side child rows when assigned via Object.assign / $.extend.
	_meta_fields = {
		"name",
		"parent",
		"parenttype",
		"parentfield",
		"doctype",
		"idx",
		"docstatus",
		"creation",
		"modified",
		"owner",
		"modified_by",
		"__islocal",
		"__unsaved",
	}
	items = []
	for row in se.get("items", []):
		d = {k: v for k, v in row.as_dict().items() if k not in _meta_fields}
		items.append(d)
	return items


@frappe.whitelist()
def get_die_tool_counter(die_tool_code: str) -> dict:
	counter = _get_or_create_counter(die_tool_code)
	current_strokes = float(counter.current_stroke_count or 0)
	stroke_capacity = float(counter.stroke_capacity or 0)
	warning_threshold_pct = float(counter.warning_threshold_pct or 90)
	utilization_pct, is_maintenance_due = get_counter_health(
		current_strokes=current_strokes,
		stroke_capacity=stroke_capacity,
		warning_threshold_pct=warning_threshold_pct,
		precision=3,
	)
	return {
		"die_tool_code": die_tool_code,
		"current_strokes": current_strokes,
		"stroke_capacity": stroke_capacity,
		"warning_threshold_pct": warning_threshold_pct,
		"utilization_pct": utilization_pct,
		"is_maintenance_due": is_maintenance_due,
	}


@frappe.whitelist()
def reset_die_tool_counter(die_tool_code: str, maintenance_date: str | None = None) -> dict:
	if not die_tool_code:
		frappe.throw(_("Die Tool Item is required."))

	maintenance_dt = get_datetime(maintenance_date) if maintenance_date else now_datetime()
	maintenance_log = frappe.get_doc(
		{
			"doctype": "Die Tool Maintenance Log",
			"die_tool_item": die_tool_code,
			"maintenance_date": maintenance_dt,
			"remarks": _("Counter reset from API."),
		}
	).insert(ignore_permissions=True)
	maintenance_log.flags.ignore_permissions = True
	maintenance_log.submit()

	counter = _get_or_create_counter(die_tool_code)
	return {
		"die_tool_code": die_tool_code,
		"current_strokes": counter.current_stroke_count,
		"maintenance_log": maintenance_log.name,
	}


def _ensure_rejection_reason(name: str) -> None:
	if frappe.db.exists("Rejection Reason", name):
		return
	frappe.get_doc({"doctype": "Rejection Reason", "rejection_reason_name": name}).insert(ignore_permissions=True)


def _ensure_downtime_reason(name: str) -> None:
	if frappe.db.exists("Downtime Reason", name):
		return
	frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert(ignore_permissions=True)


def _ensure_operator(name: str) -> None:
	if frappe.db.exists("Operator", name):
		return
	frappe.get_doc({"doctype": "Operator", "operator_name": name, "is_active": 1}).insert(ignore_permissions=True)


def _ensure_workstation(name: str, standard_spm: float) -> None:
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


def _ensure_default_bom(fg_item: str, rm_item: str, company: str) -> str:
	existing = frappe.db.get_value(
		"BOM",
		{"item": fg_item, "is_default": 1, "is_active": 1, "docstatus": 1},
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


def _ensure_stock(item_code: str, warehouse: str, company: str, target_qty: float) -> None:
	actual_qty = float(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0)
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


def _e2e_base_date(prefix: str) -> str:
	offset = sum(ord(ch) for ch in (prefix or "E2E")) % 30
	return add_to_date(frappe.utils.today(), days=7 + offset, as_string=True)


@frappe.whitelist()
def bootstrap_e2e_context(prefix: str = "E2E") -> dict:
	"""Create deterministic test masters for Playwright E2E tests."""
	company = resolve_test_company()
	abbr = frappe.db.get_value("Company", company, "abbr") or "TC"

	wip_warehouse = ensure_warehouse(f"{prefix} WIP - {abbr}", company)
	rm_warehouse = ensure_warehouse(f"{prefix} RM - {abbr}", company)
	fg_warehouse = ensure_warehouse(f"{prefix} FG - {abbr}", company)
	rejection_warehouse = ensure_warehouse(f"{prefix} Rejection - {abbr}", company)

	fg_item = ensure_item(f"_{prefix}_FG_Item")
	rm_item = ensure_item(f"_{prefix}_RM_Item")
	frappe.db.set_value("Item", fg_item, "custom_strokes_per_unit", 5, update_modified=False)
	frappe.db.set_value("Item", fg_item, "custom_stroke_capacity", 10000, update_modified=False)

	operator_name = f"{prefix} Operator"
	workstation_name = f"{prefix} Workstation"
	_ensure_operator(operator_name)
	_ensure_workstation(workstation_name, standard_spm=2)
	_ensure_rejection_reason("Burr")
	_ensure_rejection_reason("Crack")
	_ensure_downtime_reason("Tea Break")
	_ensure_downtime_reason("Lunch Break")

	frappe.db.set_single_value("Manufacturing Settings", "shift_wip_warehouse", wip_warehouse)
	frappe.db.set_single_value("Manufacturing Settings", "shift_raw_material_warehouse", rm_warehouse)
	frappe.db.set_single_value("Manufacturing Settings", "shift_rejection_warehouse", rejection_warehouse)
	frappe.db.set_single_value("Manufacturing Settings", "shift_start_buffer_mins", 60)
	frappe.db.set_single_value("Manufacturing Settings", "shift_end_buffer_mins", 60)

	bom = _ensure_default_bom(fg_item=fg_item, rm_item=rm_item, company=company)
	_ensure_stock(rm_item, wip_warehouse, company, target_qty=1000)

	base_date = _e2e_base_date(prefix)
	shift_name = f"SHIFT-{base_date}.Shift-1"
	if frappe.db.exists("Shift", shift_name):
		shift = frappe.get_doc("Shift", shift_name)
	else:
		shift = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": base_date,
				"planned_start_time": "08:00:00",
				"work_in_progress_warehouse": wip_warehouse,
				"raw_material_warehouse": rm_warehouse,
				"rejection_warehouse": rejection_warehouse,
			}
		).insert(ignore_permissions=True)
	if shift.status != "Running":
		shift.start_shift()

	frappe.db.commit()  # nosemgrep: frappe-manual-commit - tests need deterministic persisted setup
	return {
		"company": company,
		"wip_warehouse": wip_warehouse,
		"rm_warehouse": rm_warehouse,
		"fg_warehouse": fg_warehouse,
		"rejection_warehouse": rejection_warehouse,
		"fg_item": fg_item,
		"rm_item": rm_item,
		"operator": operator_name,
		"workstation": workstation_name,
		"bom": bom,
		"shift_name": shift.name,
		"shift_date": base_date,
	}


@frappe.whitelist()
def cleanup_e2e_context(prefix: str = "E2E") -> dict:
	"""Remove seeded E2E docs and end running shifts created for E2E."""
	target_operator = f"{prefix} Operator"
	target_workstation = f"{prefix} Workstation"
	target_fg_item = f"_{prefix}_FG_Item"
	target_rm_item = f"_{prefix}_RM_Item"

	base_date = _e2e_base_date(prefix)
	next_date = add_to_date(base_date, days=1, as_string=True)
	e2e_shift_names = []
	for shift_date in (base_date, next_date):
		for label in ("1", "2"):
			e2e_shift_names.append(f"SHIFT-{shift_date}.Shift-{label}")

	for name in e2e_shift_names:
		if not frappe.db.exists("Shift", name):
			continue
		doc = frappe.get_doc("Shift", name)
		if doc.status == "Running":
			doc.end_shift()
			doc.reload()
		if doc.status in ("Draft", "Cancelled", "Completed"):
			frappe.delete_doc("Shift", name, ignore_permissions=True, force=True)

	stock_entries = frappe.get_all(
		"Stock Entry",
		filters=[["stock_entry_type", "=", "Manufacture"], ["name", "like", "MAT-STE-%"]],
		fields=["name", "docstatus"],
		order_by="creation desc",
		limit=40,
	)
	for row in stock_entries:
		se = frappe.get_doc("Stock Entry", row.name)
		if se.get("custom_operator") != target_operator and se.get("fg_item") != target_fg_item:
			continue
		if se.docstatus == 1:
			se.cancel()
		if se.docstatus == 0:
			frappe.delete_doc("Stock Entry", se.name, ignore_permissions=True, force=True)

	for doctype, name in (("Workstation", target_workstation), ("Operator", target_operator)):
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)

	for item in (target_fg_item, target_rm_item):
		if frappe.db.exists("Die Tool Counter", {"die_tool_item": item}):
			for counter_name in frappe.get_all(
				"Die Tool Counter", filters={"die_tool_item": item}, pluck="name"
			):
				frappe.delete_doc("Die Tool Counter", counter_name, ignore_permissions=True, force=True)
		for log_name in frappe.get_all("Die Tool Maintenance Log", filters={"die_tool_item": item}, pluck="name"):
			doc = frappe.get_doc("Die Tool Maintenance Log", log_name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Die Tool Maintenance Log", log_name, ignore_permissions=True, force=True)

	frappe.db.commit()  # nosemgrep: frappe-manual-commit - deterministic cleanup for test reruns
	return {"ok": True}


@frappe.whitelist()
def create_e2e_submitted_stock_entry(prefix: str = "E2E", rejection_qty: float = 0) -> dict:
	"""Create and submit one manufacture stock entry for E2E report coverage."""
	ctx = bootstrap_e2e_context(prefix=prefix)
	shift = frappe.get_doc("Shift", ctx["shift_name"])
	shift_date = str(shift.shift_date)

	doc = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Manufacture",
			"purpose": "Manufacture",
			"company": ctx["company"],
			"from_bom": 1,
			"bom_no": ctx["bom"],
			"fg_completed_qty": 100,
			"custom_shift": ctx["shift_name"],
			"custom_operator": ctx["operator"],
			"custom_workstation": ctx["workstation"],
			"custom_rejection_qty": float(rejection_qty or 0),
			"custom_actual_start_date": f"{shift_date} 08:00:00",
			"custom_actual_end_date": f"{shift_date} 09:00:00",
			"posting_date": shift_date,
			"posting_time": "09:00:00",
		}
	)
	doc.get_items()
	if float(rejection_qty or 0) > 0:
		doc.append("custom_rejection_breakup", {"rejection_reason": "Burr", "qty": float(rejection_qty or 0)})
	doc.insert(ignore_permissions=True)
	doc.submit()

	frappe.db.commit()  # nosemgrep: frappe-manual-commit - required for report read-after-write checks
	return {"name": doc.name, "docstatus": doc.docstatus, "posting_date": shift_date}
