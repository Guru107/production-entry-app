from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime


def update_counter_for_stock_entry(doc, direction: int = 1) -> None:
	"""Increment or decrement die tool strokes based on finished good qty."""
	if not _is_manufacture_entry(doc):
		return

	fg_row = _find_finished_good_row(doc)
	if not fg_row:
		return

	item_code = fg_row.get("item_code")
	if not item_code:
		return

	strokes_per_unit = float(frappe.db.get_value("Item", item_code, "custom_strokes_per_unit") or 0)
	if strokes_per_unit <= 0:
		return

	rejection_qty = float(doc.get("custom_rejection_qty") or 0)
	total_qty = float(fg_row.get("qty") or 0) + rejection_qty
	stroke_delta = total_qty * strokes_per_unit
	if not stroke_delta:
		return

	counter = _get_or_create_counter(item_code)
	current_count = float(counter.current_stroke_count or 0)
	new_count = current_count + (direction * stroke_delta)
	if new_count < 0:
		new_count = 0

	counter.current_stroke_count = new_count
	counter.stroke_capacity = float(frappe.db.get_value("Item", item_code, "custom_stroke_capacity") or 0)
	counter.save(ignore_permissions=True)


def reset_die_tool_counter(die_tool_code: str) -> dict:
	"""Reset the stroke count to zero after maintenance completion."""
	if not die_tool_code:
		frappe.throw(_("Die Tool Code is required to reset stroke count."))

	counter = _get_or_create_counter(die_tool_code)
	counter.current_stroke_count = 0
	counter.last_reset_on = now_datetime()
	counter.last_reset_by = frappe.session.user
	counter.save(ignore_permissions=True)
	return {
		"name": counter.name,
		"current_stroke_count": counter.current_stroke_count,
		"last_reset_on": counter.last_reset_on,
	}


def _get_or_create_counter(item_code: str):
	if frappe.db.exists("Die Tool Counter", item_code):
		return frappe.get_doc("Die Tool Counter", item_code)
	return frappe.get_doc(
		{
			"doctype": "Die Tool Counter",
			"die_tool_item": item_code,
			"current_stroke_count": 0,
		}
	).insert(ignore_permissions=True)


def _find_finished_good_row(doc):
	for row in doc.get("items", []):
		if row.get("is_finished_item"):
			return row
	return None


def _is_manufacture_entry(doc) -> bool:
	return doc.get("purpose") == "Manufacture"
