from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate

from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	get_entry_qty_maps,
	get_rework_qty_map,
)

PPM_MULTIPLIER: int = 1_000_000


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
	chart = _get_chart(rows)
	return columns, rows, None, chart


def _get_columns() -> list[dict]:
	return [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 120},
		{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 90},
		{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Rework Qty"), "fieldname": "rework_qty", "fieldtype": "Float", "width": 130},
		{"label": _("PPM"), "fieldname": "ppm", "fieldtype": "Float", "width": 120},
	]


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_workstation", "custom_shift", "custom_operator", "bom_no"),
	)


def _get_rows(filters: dict) -> list[dict]:
	entries = frappe.get_all(
		"Stock Entry",
		filters=_build_filters(filters),
		fields=["name", "posting_date", "fg_completed_qty", "custom_rework_qty", "custom_rejection_qty"],
		order_by="posting_date asc",
	)
	if not entries:
		return []

	entry_names = [entry.get("name") for entry in entries if entry.get("name")]
	good_qty_map, rejection_qty_map, _ = get_entry_qty_maps(entry_names)
	rework_qty_map = get_rework_qty_map(entry_names)

	aggregates: dict = {}
	for entry in entries:
		posting_date = getdate(entry.get("posting_date"))
		if not posting_date:
			continue
		entry_name = entry.get("name")
		rejection_qty = flt(entry.get("custom_rejection_qty") or 0, 3)
		if rejection_qty <= 0 and entry_name:
			rejection_qty = flt(rejection_qty_map.get(entry_name) or 0, 3)
		rework_qty = flt(entry.get("custom_rework_qty") or 0, 3)
		if rework_qty <= 0 and entry_name:
			rework_qty = flt(rework_qty_map.get(entry_name) or 0, 3)
		total_qty = flt(entry.get("fg_completed_qty") or 0, 3)
		if total_qty <= 0 and entry_name:
			total_qty = flt(good_qty_map.get(entry_name) or 0, 3) + rejection_qty

		aggregate = aggregates.setdefault(
			posting_date,
			{"date": posting_date.isoformat(), "entries": 0, "total_qty": 0.0, "rework_qty": 0.0},
		)
		aggregate["entries"] += 1
		aggregate["total_qty"] += total_qty
		aggregate["rework_qty"] += rework_qty

	rows = []
	for key_date in sorted(aggregates):
		aggregate = aggregates[key_date]
		total_qty = flt(aggregate["total_qty"], 3)
		rework_qty = flt(aggregate["rework_qty"], 3)
		ppm = flt((rework_qty / total_qty) * PPM_MULTIPLIER, 2) if total_qty > 0 else 0
		rows.append(
			{
				"date": aggregate["date"],
				"entries": aggregate["entries"],
				"total_qty": total_qty,
				"rework_qty": rework_qty,
				"ppm": ppm,
			}
		)

	return rows


def _get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	return {
		"data": {
			"labels": [row["date"] for row in rows],
			"datasets": [
				{
					"name": _("PPM"),
					"values": [flt(row["ppm"], 2) for row in rows],
				},
			],
		},
		"type": "bar",
		"height": 280,
		"axisOptions": {"xAxisMode": "tick", "xIsSeries": 1},
	}
