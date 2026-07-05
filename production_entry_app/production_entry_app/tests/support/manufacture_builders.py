from __future__ import annotations

from typing import Any

import frappe
from frappe.model.document import Document
from frappe.utils import add_to_date, get_datetime, nowdate, nowtime

from production_entry_app.production_entry_app.utils.test_bootstrap import (
	cleanup_running_shifts,
	ensure_branch,
	ensure_default_bom,
	ensure_department,
	ensure_item,
	ensure_production_entry_settings_shift_fields,
	ensure_stock,
	ensure_warehouse,
	resolve_test_branch,
	resolve_test_company,
)

_SHIFT_SEQUENCE = 0


def bootstrap_manufacture_masters() -> dict[str, Any]:
	ensure_production_entry_settings_shift_fields()
	company = resolve_test_company()
	abbr = frappe.db.get_value("Company", company, "abbr") or "TC"
	wip_warehouse = ensure_warehouse(f"Audit #1 WIP - {abbr}", company)
	fg_warehouse = ensure_warehouse(f"Audit #1 FG - {abbr}", company)
	rejection_warehouse = ensure_warehouse(f"Audit #1 Rejection - {abbr}", company)
	rm_warehouse = ensure_warehouse(f"Audit #1 RM - {abbr}", company)
	if frappe.get_meta("Warehouse", cached=True).has_field("is_rejected_warehouse"):
		frappe.db.set_value(
			"Warehouse", rejection_warehouse, "is_rejected_warehouse", 1, update_modified=False
		)

	fg_item = ensure_item("_Audit #1 FG Item")
	rm_item = ensure_item("_Audit #1 RM Item")
	frappe.db.set_value("Item", fg_item, "custom_pea_strokes_per_unit", 5, update_modified=False)
	frappe.db.set_value("Item", fg_item, "custom_pea_stroke_capacity", 10000, update_modified=False)
	if frappe.get_meta("Item", cached=True).has_field("custom_pea_has_die_tool"):
		frappe.db.set_value("Item", fg_item, "custom_pea_has_die_tool", 1, update_modified=False)

	bom = ensure_default_bom(fg_item=fg_item, rm_item=rm_item, company=company)
	ensure_stock(rm_item, wip_warehouse, company, target_qty=1000)
	return {
		"company": company,
		"bom": bom,
		"wip_warehouse": wip_warehouse,
		"fg_warehouse": fg_warehouse,
		"rejection_warehouse": rejection_warehouse,
		"fg_item": fg_item,
		"rm_item": rm_item,
		"rm_warehouse": rm_warehouse,
	}


def direct_manufacture_doc_dict(
	masters: dict[str, Any], *, fg_qty: float, rejection_qty: float
) -> dict[str, Any]:
	return {
		"company": masters["company"],
		"bom_no": masters["bom"],
		"fg_completed_qty": fg_qty,
		"from_warehouse": masters["wip_warehouse"],
		"to_warehouse": masters["fg_warehouse"],
		"purpose": "Manufacture",
		"stock_entry_type": "Manufacture",
		"custom_pea_rejection_qty": rejection_qty,
		"use_multi_level_bom": 0,
	}


def _build_shift_doc(*, masters: dict[str, Any], status: str) -> Document:
	global _SHIFT_SEQUENCE
	_SHIFT_SEQUENCE += 1
	shift_date = nowdate()
	shift_label = "1"
	branch = ensure_branch(resolve_test_branch() or "_Test Branch")
	department = ensure_department(f"Audit #1 Department {_SHIFT_SEQUENCE:04d}", company=masters["company"])
	return frappe.get_doc(
		{
			"doctype": "Shift",
			"company": masters["company"],
			"branch": branch,
			"shift_date": shift_date,
			"planned_start_time": "08:00:00",
			"shift_duration": "8",
			"shift_label": shift_label,
			"department": department,
			"status": status,
			"work_in_progress_warehouse": masters["wip_warehouse"],
			"raw_material_warehouse": masters["rm_warehouse"],
			"rejection_warehouse": masters["rejection_warehouse"],
		}
	)


def make_running_shift(masters: dict[str, Any]) -> Document:
	cleanup_running_shifts()
	shift = _build_shift_doc(masters=masters, status="Draft").insert(ignore_permissions=True)
	shift.start_shift()
	return shift


def make_completed_shift(masters: dict[str, Any]) -> Document:
	shift = make_running_shift(masters)
	shift.end_shift()
	return shift


def make_direct_manufacture_entry(
	masters: dict[str, Any], *, shift: str, fg_qty: float, rejection_qty: float
) -> Document:
	shift_doc = frappe.get_doc("Shift", shift)
	shift_start = get_datetime(f"{shift_doc.shift_date} {shift_doc.planned_start_time or '08:00:00'}")
	start_dt = add_to_date(shift_start, minutes=15)
	end_dt = add_to_date(start_dt, minutes=45)
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"purpose": "Manufacture",
			"stock_entry_type": "Manufacture",
			"company": masters["company"],
			"from_bom": 1,
			"bom_no": masters["bom"],
			"fg_completed_qty": fg_qty,
			"custom_pea_shift": shift,
			"custom_pea_rejection_qty": rejection_qty,
			"from_warehouse": masters["wip_warehouse"],
			"to_warehouse": masters["fg_warehouse"],
			"posting_date": shift_doc.shift_date,
			"posting_time": nowtime(),
			"custom_pea_actual_start_date": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
			"custom_pea_actual_end_date": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
		}
	)
	se.get_items()
	if rejection_qty > 0:
		se.append(
			"custom_pea_rejection_breakup",
			{
				"rejection_reason": "Burr",
				"qty": rejection_qty,
			},
		)
	return se.insert(ignore_permissions=True)
