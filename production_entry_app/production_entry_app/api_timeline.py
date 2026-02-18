from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from production_entry_app.production_entry_app.utils.shift_time import combine_date_time


def _get_timeline_cache_key(doctype: str, docname: str, shift_name: str) -> str:
	return f"pea:timeline:{frappe.session.user}:{doctype}:{docname}:{shift_name}"


def _get_cached_timeline_data(doctype: str, docname: str, shift_name: str) -> dict | None:
	return frappe.cache().get_value(_get_timeline_cache_key(doctype, docname, shift_name))


def _set_cached_timeline_data(doctype: str, docname: str, shift_name: str, data: dict) -> None:
	frappe.cache().set_value(
		_get_timeline_cache_key(doctype, docname, shift_name),
		data,
		expires_in_sec=30,
	)


@frappe.whitelist()
def get_shift_timeline_data(doctype: str, docname: str) -> dict:
	"""Return running shift timeline data for Workstation/Operator forms."""
	if doctype not in ("Workstation", "Operator"):
		frappe.throw(_("Invalid doctype for timeline data."))
	if not frappe.has_permission(doctype, "read", docname):
		raise frappe.PermissionError

	running_shift = frappe.get_all(
		"Shift",
		filters={"status": "Running"},
		fields=["name", "shift_date", "planned_start_time", "shift_end_date", "planned_end_time"],
		limit=1,
		order_by="modified desc",
	)
	if not running_shift:
		return {"shift_name": None, "entries": []}

	shift = running_shift[0]
	if not frappe.has_permission("Shift", "read", shift.get("name")):
		raise frappe.PermissionError
	cached_data = _get_cached_timeline_data(doctype, docname, shift.get("name"))
	if cached_data is not None:
		return cached_data

	shift_start = combine_date_time(shift.get("shift_date"), shift.get("planned_start_time"))
	shift_end = combine_date_time(
		shift.get("shift_end_date") or shift.get("shift_date"),
		shift.get("planned_end_time") or "23:59:59",
	)

	filter_field = "custom_workstation" if doctype == "Workstation" else "custom_operator"
	stock_entry = DocType("Stock Entry")
	rows = (
		frappe.qb.from_(stock_entry)
		.select(
			stock_entry.name,
			stock_entry.custom_actual_start_date.as_("actual_start"),
			stock_entry.custom_actual_end_date.as_("actual_end"),
			stock_entry.fg_completed_qty.as_("fg_qty"),
			stock_entry.custom_rejection_qty.as_("rejection_qty"),
		)
		.where(
			(stock_entry.docstatus == 1)
			& (stock_entry.purpose == "Manufacture")
			& (stock_entry.custom_shift == shift.get("name"))
			& (stock_entry[filter_field] == docname)
			& stock_entry.custom_actual_start_date.isnotnull()
			& stock_entry.custom_actual_end_date.isnotnull()
		)
		.orderby(stock_entry.custom_actual_start_date)
	).run(as_dict=True)

	if not rows:
		result = {
			"shift_name": shift.get("name"),
			"shift_start": str(shift_start),
			"shift_end": str(shift_end),
			"entries": [],
		}
		_set_cached_timeline_data(doctype, docname, shift.get("name"), result)
		return result

	stock_entry_detail = DocType("Stock Entry Detail")
	names = [row.get("name") for row in rows if row.get("name")]
	fg_rows = (
		frappe.qb.from_(stock_entry_detail)
		.select(
			stock_entry_detail.parent,
			stock_entry_detail.item_code,
			Sum(stock_entry_detail.qty).as_("fg_qty"),
		)
		.where((stock_entry_detail.parent.isin(names)) & (stock_entry_detail.is_finished_item == 1))
		.groupby(stock_entry_detail.parent, stock_entry_detail.item_code)
	).run(as_dict=True)
	fg_item_by_entry = {}
	fg_qty_by_entry = {}
	for fg_row in fg_rows:
		parent = fg_row.get("parent")
		if parent and parent not in fg_item_by_entry:
			fg_item_by_entry[parent] = fg_row.get("item_code")
		if parent:
			fg_qty_by_entry[parent] = flt(fg_qty_by_entry.get(parent) or 0, 3) + flt(
				fg_row.get("fg_qty") or 0, 3
			)

	entries = []
	for row in rows:
		good_qty = flt(fg_qty_by_entry.get(row.get("name"), row.get("fg_qty") or 0), 3)
		rejection_qty = flt(row.get("rejection_qty") or 0, 3)
		entries.append(
			{
				"name": row.get("name"),
				"actual_start": str(row.get("actual_start")),
				"actual_end": str(row.get("actual_end")),
				"fg_item": fg_item_by_entry.get(row.get("name")),
				"fg_qty": good_qty,
				"rejection_qty": rejection_qty,
				"ok_qty": flt(good_qty - rejection_qty, 3),
			}
		)

	result = {
		"shift_name": shift.get("name"),
		"shift_start": str(shift_start),
		"shift_end": str(shift_end),
		"entries": entries,
	}
	_set_cached_timeline_data(doctype, docname, shift.get("name"), result)
	return result
