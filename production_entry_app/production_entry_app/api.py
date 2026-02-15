from __future__ import annotations

import datetime
import json

import frappe
from frappe import _
from frappe.utils import get_time

from production_entry_app.production_entry_app.utils.die_tool_strokes import get_die_tool_strokes
from production_entry_app.production_entry_app.utils.shift_time import get_shift_planned_end_datetime


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
def get_die_tool_strokes_count(die_tool_code: str) -> dict:
	return {
		"die_tool_code": die_tool_code,
		"current_strokes": get_die_tool_strokes(die_tool_code),
	}
