from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	get_entry_qty_maps,
	get_finished_item_maps,
)
from production_entry_app.production_entry_app.utils.loss_time import build_interval_overlap_filters
from production_entry_app.production_entry_app.utils.shift_time import combine_date_time
from production_entry_app.production_entry_app.utils.system_precision import (
	get_system_float_precision,
)

TIMELINE_CACHE_PREFIX: str = "pea:timeline"


def get_timeline_cache_prefix(doctype: str, docname: str, shift_name: str) -> str:
	return f"{TIMELINE_CACHE_PREFIX}:{doctype}:{docname}:{shift_name}:"


def invalidate_timeline_cache_for_stock_entry(doc: Document) -> None:
	shift_name = doc.get("custom_pea_shift")
	if not shift_name:
		return
	for doctype, fieldname in (
		("Workstation", "custom_pea_workstation"),
		("Operator", "custom_pea_operator"),
	):
		docname = doc.get(fieldname)
		if docname:
			frappe.cache().delete_keys(get_timeline_cache_prefix(doctype, docname, shift_name))


def _get_timeline_cache_key(doctype: str, docname: str, shift_name: str) -> str:
	"""Cache key includes shift's modified timestamp so any change to the shift
	automatically invalidates the timeline cache."""
	shift_modified = frappe.db.get_value("Shift", shift_name, "modified") or ""
	return f"{get_timeline_cache_prefix(doctype, docname, shift_name)}{shift_modified}"


def _set_cached_timeline_data(doctype: str, docname: str, shift_name: str, data: dict) -> None:
	frappe.cache().set_value(
		_get_timeline_cache_key(doctype, docname, shift_name),
		data,
		expires_in_sec=30,
	)


def _get_cached_timeline_data(doctype: str, docname: str, shift_name: str) -> dict | None:
	"""Return cached timeline data if present, None if stale or missing.

	Cache is keyed by the shift's modified timestamp, so any change to the shift
	automatically produces a different key, making the cache stale.
	"""
	return frappe.cache().get_value(_get_timeline_cache_key(doctype, docname, shift_name))


def _with_float_precision(payload: dict) -> dict:
	result = dict(payload)
	result.setdefault("float_precision", get_system_float_precision())
	return result


@frappe.whitelist()
def get_shift_timeline_data(doctype: str, docname: str) -> dict:
	"""Return running shift timeline data for Workstation/Operator forms."""
	if doctype not in ("Workstation", "Operator"):
		frappe.throw(_("Invalid doctype for timeline data."))
	if not frappe.has_permission(doctype, "read", docname):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)

	running_shift = frappe.get_list(
		"Shift",
		filters={"status": "Running"},
		fields=["name", "shift_date", "planned_start_time", "shift_end_date", "planned_end_time"],
		limit=1,
		order_by="modified desc",
	)
	if not running_shift:
		return {"shift_name": None, "entries": [], "float_precision": get_system_float_precision()}

	shift = running_shift[0]
	if not frappe.has_permission("Shift", "read", shift.get("name")):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	if not frappe.has_permission("Stock Entry", "read"):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	if doctype == "Workstation" and not frappe.has_permission("Downtime Entry", "read"):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	cached_data = _get_cached_timeline_data(doctype, docname, shift.get("name"))
	if cached_data is not None:
		return _with_float_precision(cached_data)

	shift_start = combine_date_time(shift.get("shift_date"), shift.get("planned_start_time"))
	shift_end = combine_date_time(
		shift.get("shift_end_date") or shift.get("shift_date"),
		shift.get("planned_end_time") or "23:59:59",
	)

	filter_field = "custom_pea_workstation" if doctype == "Workstation" else "custom_pea_operator"
	rows = frappe.get_list(
		"Stock Entry",
		filters={
			"docstatus": 1,
			"custom_pea_shift": shift.get("name"),
			filter_field: docname,
			"custom_pea_actual_start_date": ("is", "set"),
			"custom_pea_actual_end_date": ("is", "set"),
		},
		or_filters=[
			["purpose", "=", "Manufacture"],
			["custom_pea_is_joint_lh_rh", "=", 1],
		],
		fields=[
			"name",
			"custom_pea_actual_start_date as actual_start",
			"custom_pea_actual_end_date as actual_end",
			"fg_completed_qty as fg_qty",
			"custom_pea_rejection_qty as rejection_qty",
			"custom_pea_is_joint_lh_rh",
		],
		order_by="custom_pea_actual_start_date asc",
		limit_page_length=0,
	)

	names = [row.get("name") for row in rows if row.get("name")]
	good_qty_by_entry, joint_rejection_qty_by_entry, _unused_fg_item_map = get_entry_qty_maps(names)
	fg_item_by_entry, fg_item_label_by_entry = get_finished_item_maps(names)

	entries = []
	for row in rows:
		entry_name = row.get("name")
		good_qty = flt(good_qty_by_entry.get(entry_name) or row.get("fg_qty") or 0)
		is_joint_production = bool(row.get("custom_pea_is_joint_lh_rh"))
		rejection_qty = flt(
			joint_rejection_qty_by_entry.get(entry_name, 0)
			if is_joint_production
			else row.get("rejection_qty") or 0
		)
		entries.append(
			{
				"name": entry_name,
				"actual_start": str(row.get("actual_start")),
				"actual_end": str(row.get("actual_end")),
				"fg_item": fg_item_by_entry.get(entry_name),
				"fg_item_label": fg_item_label_by_entry.get(entry_name),
				"fg_qty": good_qty,
				"rejection_qty": rejection_qty,
				"ok_qty": good_qty if is_joint_production else good_qty - rejection_qty,
				"entry_type": "production",
			}
		)

	if doctype == "Workstation":
		downtime_filters = [
			["workstation", "=", docname],
			["from_time", "is", "set"],
			["to_time", "is", "set"],
			*build_interval_overlap_filters("from_time", "to_time", shift_start, shift_end),
		]
		if frappe.get_meta("Downtime Entry", cached=True).is_submittable:
			downtime_filters.append(["docstatus", "!=", 2])
		downtime_rows = frappe.get_list(
			"Downtime Entry",
			filters=downtime_filters,
			fields=["name", "from_time as actual_start", "to_time as actual_end", "stop_reason"],
			order_by="from_time asc",
			limit_page_length=0,
		)
		for row in downtime_rows:
			entries.append(
				{
					"name": row.get("name"),
					"actual_start": str(row.get("actual_start")),
					"actual_end": str(row.get("actual_end")),
					"stop_reason": row.get("stop_reason"),
					"entry_type": "downtime",
				}
			)

	entries.sort(key=lambda row: str(row.get("actual_start") or ""))

	result = {
		"shift_name": shift.get("name"),
		"shift_start": str(shift_start),
		"shift_end": str(shift_end),
		"float_precision": get_system_float_precision(),
		"entries": entries,
	}
	_set_cached_timeline_data(doctype, docname, shift.get("name"), result)
	return result
