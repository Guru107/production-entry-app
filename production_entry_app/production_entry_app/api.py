from __future__ import annotations

import datetime
import json

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, get_time, now_datetime

from production_entry_app.production_entry_app.joint_production import (
	calculate_joint_rm_consumption_from_boms,
	is_scrap_row,
	materialize_joint_production_rows,
)
from production_entry_app.production_entry_app.utils.alternative_items import (
	apply_direct_manufacture_alternative_flags,
)
from production_entry_app.production_entry_app.utils.die_tool_counter import (
	_get_or_create_counter,
	get_counter_health,
	is_die_tool_enabled,
)
from production_entry_app.production_entry_app.utils.production_warehouses import (
	get_branch_warehouse_defaults,
	get_production_warehouses,
	get_shift_warehouses,
	require_warehouse,
	set_production_header_warehouses,
)
from production_entry_app.production_entry_app.utils.shift_time import get_shift_planned_end_datetime
from production_entry_app.production_entry_app.utils.system_precision import (
	get_system_float_precision,
)

_ALLOWED_STOCK_ENTRY_SHIFT_STATUSES: tuple[str, ...] = ("Running", "Completed")


@frappe.whitelist()
def get_joint_stock_entry_type() -> str:
	if not frappe.has_permission("Stock Entry", "create"):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	stock_entry_types = frappe.get_list(
		"Stock Entry Type",
		filters={
			"purpose": "Repack",
			"custom_pea_joint_lh_rh_production": 1,
		},
		order_by="modified desc, name asc",
		pluck="name",
		limit=1,
	)
	if not stock_entry_types:
		frappe.throw(_("Configure a Repack Stock Entry Type for Joint LH/RH Production first."))
	stock_entry_type = stock_entry_types[0]
	return stock_entry_type


@frappe.whitelist()
def get_rework_stock_entry_type(required: int = 1, stock_entry_type: str | None = None) -> str:
	if not frappe.has_permission("Stock Entry", "create"):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	if stock_entry_type is not None:
		if not stock_entry_type:
			return ""
		if not frappe.has_permission("Stock Entry Type", "read", stock_entry_type):
			frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
		selected_type = frappe.db.get_value(
			"Stock Entry Type",
			stock_entry_type,
			["purpose", "custom_pea_rework_entry"],
			as_dict=True,
		)
		if (
			selected_type
			and selected_type.purpose == "Material Transfer"
			and selected_type.custom_pea_rework_entry
		):
			return stock_entry_type
		return ""
	stock_entry_types = frappe.get_list(
		"Stock Entry Type",
		filters={
			"purpose": "Material Transfer",
			"custom_pea_rework_entry": 1,
		},
		order_by="modified desc, name asc",
		pluck="name",
		limit=2,
	)
	if not stock_entry_types:
		if not cint(required):
			return ""
		frappe.throw(_("Configure a Material Transfer Stock Entry Type for Rework first."))
	if len(stock_entry_types) > 1:
		if not cint(required):
			return ""
		frappe.throw(_("Only one Material Transfer Stock Entry Type can be configured for Rework."))
	return stock_entry_types[0]


@frappe.whitelist()
def get_rework_source_warehouse(company: str, branch: str) -> str:
	"""Return the configured rejection source used to create Rework Stock Entries."""
	if not frappe.has_permission("Stock Entry", "create"):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	warehouse = get_branch_warehouse_defaults(company, branch).get("rejection_warehouse") or ""
	if warehouse and not frappe.has_permission("Warehouse", "read", warehouse):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	return warehouse


@frappe.whitelist()
def get_joint_rm_consumption(
	lh_bom: str,
	rh_bom: str,
	lh_gross_qty: float,
	rh_gross_qty: float,
) -> float:
	if not frappe.has_permission("Stock Entry", "create"):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	if not lh_bom or not rh_bom:
		frappe.throw(_("Select both LH and RH BOMs."))
	for bom_no in (lh_bom, rh_bom):
		if not frappe.has_permission("BOM", "read", bom_no):
			frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	return calculate_joint_rm_consumption_from_boms(
		lh_bom_no=lh_bom,
		rh_bom_no=rh_bom,
		lh_gross_qty=lh_gross_qty,
		rh_gross_qty=rh_gross_qty,
	)


@frappe.whitelist()
def get_joint_production_items(doc: str) -> list[dict]:
	try:
		doc_dict = json.loads(doc)
	except (TypeError, ValueError):
		frappe.throw(_("Stock Entry payload must be a valid JSON object."))
	if not isinstance(doc_dict, dict) or doc_dict.get("doctype") not in (None, "Stock Entry"):
		frappe.throw(_("Stock Entry payload must be a valid JSON object."))

	docname = doc_dict.get("name")
	is_local_doc = bool(doc_dict.get("__islocal"))
	if docname and not is_local_doc and frappe.db.exists("Stock Entry", docname):
		if not frappe.has_permission("Stock Entry", "write", docname):
			frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	elif not frappe.has_permission("Stock Entry", "create"):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)

	for doctype, fieldname in (
		("BOM", "custom_pea_lh_bom"),
		("BOM", "custom_pea_rh_bom"),
		("Item", "custom_pea_die_tool_item"),
		("Shift", "custom_pea_shift"),
		("Warehouse", "from_warehouse"),
		("Warehouse", "to_warehouse"),
	):
		name = doc_dict.get(fieldname)
		if name and not frappe.has_permission(doctype, "read", name):
			frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)

	stock_entry = frappe.new_doc("Stock Entry")
	for fieldname in (
		"purpose",
		"stock_entry_type",
		"company",
		"branch",
		"from_warehouse",
		"to_warehouse",
		"custom_pea_shift",
		"custom_pea_is_joint_lh_rh",
		"custom_pea_lh_bom",
		"custom_pea_lh_gross_qty",
		"custom_pea_lh_rejection_qty",
		"custom_pea_rh_bom",
		"custom_pea_rh_gross_qty",
		"custom_pea_rh_rejection_qty",
		"custom_pea_total_strokes",
		"custom_pea_die_tool_item",
	):
		stock_entry.set(fieldname, doc_dict.get(fieldname))
	return materialize_joint_production_rows(stock_entry)


def _cleanup_orphan_stock_entry_loss_links(shift_name: str) -> None:
	"""Delete Loss Entry rows linked to deleted Stock Entry parents for a Shift."""
	if not shift_name:
		return

	rows = frappe.get_all(
		"Loss Entry",
		filters={"shift": shift_name, "parenttype": "Stock Entry"},
		fields=["name", "parent"],
	)
	if not rows:
		return

	parent_names = sorted({row.get("parent") for row in rows if row.get("parent")})
	if not parent_names:
		return

	existing_parents = set(
		frappe.get_all("Stock Entry", filters={"name": ("in", parent_names)}, pluck="name")
	)
	orphan_row_names = [
		row.get("name")
		for row in rows
		if row.get("name") and row.get("parent") and row.get("parent") not in existing_parents
	]
	if orphan_row_names:
		frappe.db.delete("Loss Entry", {"name": ("in", orphan_row_names)})


@frappe.whitelist()
def get_shift_details_for_stock_entry(shift_name: str) -> dict:
	"""Return shift details to auto-populate Stock Entry fields.

	Called from the Stock Entry client script when custom_pea_shift is set.
	"""
	if not shift_name:
		return {}
	if not frappe.has_permission("Shift", "read", shift_name):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)

	shift = frappe.get_doc("Shift", shift_name)
	if shift.status not in _ALLOWED_STOCK_ENTRY_SHIFT_STATUSES:
		frappe.throw(
			_(
				"Only Running or Completed shifts can be linked in Stock Entry. Selected shift {0} is {1}."
			).format(
				frappe.bold(frappe.utils.escape_html(str(shift.name))),
				frappe.bold(frappe.utils.escape_html(str(shift.status or _("not found")))),
			)
		)
	planned_start = None
	if shift.shift_date and shift.planned_start_time:
		planned_start = datetime.datetime.combine(
			frappe.utils.getdate(shift.shift_date),
			get_time(shift.planned_start_time),
		)

	planned_end = get_shift_planned_end_datetime(
		shift_date=shift.shift_date,
		planned_start_time=shift.planned_start_time,
		planned_end_time=shift.planned_end_time,
		shift_end_date=shift.shift_end_date,
		shift_duration=shift.shift_duration,
	)

	wip_warehouse = get_shift_warehouses(shift).get("work_in_progress_warehouse")
	return {
		"company": shift.company,
		"branch": shift.branch,
		"custom_pea_planned_start_date": str(planned_start) if planned_start else None,
		"custom_pea_planned_end_date": str(planned_end) if planned_end else None,
		"from_warehouse": wip_warehouse,
		"to_warehouse": wip_warehouse,
	}


@frappe.whitelist()
def get_items_with_rejection(doc: str) -> list[dict]:
	"""Populate BOM items and apply rejection logic, returning the items list.

	Called from the Stock Entry "Get Items" button. Accepts the Stock Entry
	doc as a JSON string, builds a clean Stock Entry, calls ERPNext's
	``get_items()`` to fetch BOM rows, then applies our rejection-entry logic
	so the user sees the final items (including the rejection row) *before*
	saving.
	"""
	from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
		_apply_rejection_entries,
	)

	try:
		doc_dict = json.loads(doc)
	except (TypeError, ValueError):
		frappe.throw(_("Stock Entry payload must be a valid JSON object."))
	if not isinstance(doc_dict, dict) or doc_dict.get("doctype") not in (None, "Stock Entry"):
		frappe.throw(_("Stock Entry payload must be a valid JSON object."))

	docname = (doc_dict or {}).get("name")
	is_local_doc = bool((doc_dict or {}).get("__islocal"))
	if docname and not is_local_doc and frappe.db.exists("Stock Entry", docname):
		if not frappe.has_permission("Stock Entry", "write", docname):
			frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	elif not frappe.has_permission("Stock Entry", "create"):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)

	for doctype, fieldname in (
		("BOM", "bom_no"),
		("Work Order", "work_order"),
		("Shift", "custom_pea_shift"),
		("Warehouse", "from_warehouse"),
		("Warehouse", "to_warehouse"),
	):
		name = doc_dict.get(fieldname)
		if name and not frappe.has_permission(doctype, "read", name):
			frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)

	se = frappe.new_doc("Stock Entry")
	se.purpose = doc_dict.get("purpose", "Manufacture")
	se.stock_entry_type = doc_dict.get("stock_entry_type", "Manufacture")
	se.company = doc_dict.get("company")
	se.branch = doc_dict.get("branch")
	se.from_bom = 1
	se.bom_no = doc_dict.get("bom_no")
	se.fg_completed_qty = float(doc_dict.get("fg_completed_qty") or 0)
	se.use_multi_level_bom = doc_dict.get("use_multi_level_bom", 0)
	se.from_warehouse = doc_dict.get("from_warehouse")
	se.to_warehouse = doc_dict.get("to_warehouse")
	se.posting_date = doc_dict.get("posting_date") or frappe.utils.nowdate()
	se.posting_time = doc_dict.get("posting_time") or frappe.utils.nowtime()
	se.custom_pea_rejection_qty = float(doc_dict.get("custom_pea_rejection_qty") or 0)
	se.custom_pea_shift = doc_dict.get("custom_pea_shift")
	se.work_order = doc_dict.get("work_order")

	# Work Orders retain ERPNext's warehouse configuration even when linked to a Shift.
	use_production_defaults = se.purpose == "Manufacture" and not se.work_order
	warehouses = get_production_warehouses(se) if use_production_defaults else {}
	if use_production_defaults:
		set_production_header_warehouses(se, warehouses)
	se.get_items()
	if use_production_defaults:
		for row in se.items:
			if is_scrap_row(row):
				row.t_warehouse = require_warehouse(warehouses, "scrap_warehouse")
		se.set_actual_qty()
	apply_direct_manufacture_alternative_flags(se)
	_apply_rejection_entries(se)

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
	if not die_tool_code or not frappe.db.exists("Item", die_tool_code):
		return _empty_die_tool_payload(die_tool_code)
	if not frappe.has_permission("Item", "read", die_tool_code):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	if not is_die_tool_enabled(die_tool_code):
		return _empty_die_tool_payload(die_tool_code)

	counters = frappe.get_list(
		"Die Tool Counter",
		filters={"die_tool_item": die_tool_code},
		fields=["name", "current_stroke_count", "stroke_capacity", "warning_threshold_pct"],
		limit=1,
	)
	counter = counters[0] if counters else None
	if not counter:
		return {
			"die_tool_code": die_tool_code,
			"has_die_tool": 1,
			"current_strokes": 0,
			"stroke_capacity": 0,
			"warning_threshold_pct": 90,
			"utilization_pct": 0,
			"is_maintenance_due": 0,
			"float_precision": get_system_float_precision(),
		}
	current_strokes = float(counter.get("current_stroke_count") or 0)
	stroke_capacity = float(counter.get("stroke_capacity") or 0)
	warning_threshold_pct = float(counter.get("warning_threshold_pct") or 90)
	utilization_pct, is_maintenance_due = get_counter_health(
		current_strokes=current_strokes,
		stroke_capacity=stroke_capacity,
		warning_threshold_pct=warning_threshold_pct,
	)
	return {
		"die_tool_code": die_tool_code,
		"has_die_tool": 1,
		"current_strokes": current_strokes,
		"stroke_capacity": stroke_capacity,
		"warning_threshold_pct": warning_threshold_pct,
		"utilization_pct": utilization_pct,
		"is_maintenance_due": is_maintenance_due,
		"float_precision": get_system_float_precision(),
	}


def _empty_die_tool_payload(die_tool_code: str | None) -> dict:
	return {
		"die_tool_code": die_tool_code,
		"has_die_tool": 0,
		"current_strokes": 0,
		"stroke_capacity": 0,
		"warning_threshold_pct": 90,
		"utilization_pct": 0,
		"is_maintenance_due": 0,
		"float_precision": get_system_float_precision(),
	}


@frappe.whitelist()
def reset_die_tool_counter(die_tool_code: str, maintenance_date: str | None = None) -> dict:
	if not die_tool_code:
		frappe.throw(_("Die Tool Item is required."))
	if not is_die_tool_enabled(die_tool_code):
		frappe.throw(_("Die tool counter reset is not allowed because this item has no die tool."))
	if not frappe.has_permission("Die Tool Maintenance Log", "create"):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)

	maintenance_dt = get_datetime(maintenance_date) if maintenance_date else now_datetime()
	maintenance_log = frappe.get_doc(
		{
			"doctype": "Die Tool Maintenance Log",
			"die_tool_item": die_tool_code,
			"maintenance_date": maintenance_dt,
			"remarks": _("Counter reset from API."),
		}
	).insert()
	maintenance_log.submit()

	counter = _get_or_create_counter(die_tool_code)
	return {
		"die_tool_code": die_tool_code,
		"current_strokes": counter.current_stroke_count,
		"maintenance_log": maintenance_log.name,
	}
