from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.utils import get_datetime


def get_die_tool_strokes(item_code: str) -> float:
	if not item_code:
		frappe.throw(_("Die Tool Item is required to calculate strokes."))

	strokes_per_unit = float(frappe.db.get_value("Item", item_code, "custom_strokes_per_unit") or 0)
	if strokes_per_unit <= 0:
		return 0.0

	last_maintenance = _get_last_maintenance_datetime(item_code)

	total_units = 0.0
	for row in _get_stock_entry_rows(item_code):
		posting_dt = _get_posting_datetime(row)
		if last_maintenance and posting_dt < last_maintenance:
			continue
		rejection_qty = float(row.get("custom_rejection_qty") or 0)
		fg_completed_qty = float(row.get("qty") or 0)
		total_units += fg_completed_qty + rejection_qty

	return total_units * strokes_per_unit


def _get_last_maintenance_datetime(item_code: str) -> datetime.datetime | None:
	rows = frappe.get_all(
		"Die Tool Maintenance Log",
		filters={"die_tool_item": item_code},
		fields=["maintenance_date"],
		order_by="maintenance_date desc",
		limit=1,
	)
	if not rows:
		return None
	return get_datetime(rows[0]["maintenance_date"])


def _get_stock_entry_rows(item_code: str) -> list[dict]:
	parent_rows = frappe.get_all(
		"Stock Entry Detail",
		filters={
			"item_code": item_code,
		},
		fields=["parent", "qty"],
		ignore_permissions=True,
	)
	if not parent_rows:
		return []

	parent_names = [row["parent"] for row in parent_rows]
	stock_entries = frappe.get_all(
		"Stock Entry",
		filters={
			"name": ["in", parent_names],
			"docstatus": 1,
			"purpose": "Manufacture",
		},
		fields=["name", "custom_rejection_qty", "posting_date", "posting_time"],
		ignore_permissions=True,
	)
	entry_map = {row["name"]: row for row in stock_entries}

	rows = []
	for row in parent_rows:
		stock_entry = entry_map.get(row["parent"])
		if not stock_entry:
			continue
		rows.append(
			{
				"qty": row.get("qty"),
				"custom_rejection_qty": stock_entry.get("custom_rejection_qty"),
				"posting_date": stock_entry.get("posting_date"),
				"posting_time": stock_entry.get("posting_time"),
			}
		)
	return rows


def _get_posting_datetime(stock_entry: dict) -> datetime.datetime:
	posting_date = stock_entry.get("posting_date")
	posting_time = stock_entry.get("posting_time") or "00:00:00"
	return get_datetime(f"{posting_date} {posting_time}")
