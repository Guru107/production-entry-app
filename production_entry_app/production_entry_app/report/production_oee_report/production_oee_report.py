from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	get_duration_minutes,
	get_entry_qty_maps,
)


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
	return columns, rows


def _get_columns() -> list[dict]:
	return [
		{
			"label": _("Stock Entry"),
			"fieldname": "stock_entry",
			"fieldtype": "Link",
			"options": "Stock Entry",
			"width": 140,
		},
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
		{"label": _("Shift"), "fieldname": "shift", "fieldtype": "Link", "options": "Shift", "width": 140},
		{
			"label": _("Operator"),
			"fieldname": "operator",
			"fieldtype": "Link",
			"options": "Operator",
			"width": 140,
		},
		{
			"label": _("Workstation"),
			"fieldname": "workstation",
			"fieldtype": "Link",
			"options": "Workstation",
			"width": 140,
		},
		{
			"label": _("Die Tool Item"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 150,
		},
		{"label": _("Good Qty"), "fieldname": "good_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Rejection Qty"), "fieldname": "rejection_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Availability %"), "fieldname": "availability_pct", "fieldtype": "Percent", "width": 110},
		{"label": _("Performance %"), "fieldname": "performance_pct", "fieldtype": "Percent", "width": 110},
		{"label": _("Quality %"), "fieldname": "quality_pct", "fieldtype": "Percent", "width": 100},
		{"label": _("OEE %"), "fieldname": "oee_pct", "fieldtype": "Percent", "width": 90},
	]


def _get_rows(filters: dict) -> list[dict]:
	entries = frappe.get_all(
		"Stock Entry",
		filters=_build_filters(filters),
		fields=[
			"name",
			"posting_date",
			"custom_shift",
			"custom_operator",
			"custom_workstation",
			"fg_completed_qty",
			"custom_rejection_qty",
			"custom_planned_start_date",
			"custom_planned_end_date",
			"custom_actual_start_date",
			"custom_actual_end_date",
			"custom_actual_duration_mins",
			"custom_operator_efficiency_pct",
		],
		order_by="posting_date asc, name asc",
	)
	entry_names = [entry.name for entry in entries]
	good_qty_map, rejection_qty_map, fg_item_map = get_entry_qty_maps(entry_names, include_fg_item=True)

	rows = []
	for entry in entries:
		good_qty = flt(entry.get("fg_completed_qty") or 0, 3)
		if good_qty <= 0:
			good_qty = good_qty_map.get(entry.name, 0)
		rejection_qty = flt(entry.get("custom_rejection_qty") or 0, 3)
		if rejection_qty <= 0:
			rejection_qty = rejection_qty_map.get(entry.name, 0)
		total_qty = flt(good_qty + rejection_qty, 3)

		planned_mins = get_duration_minutes(
			entry.get("custom_planned_start_date"), entry.get("custom_planned_end_date")
		)
		actual_mins = flt(entry.get("custom_actual_duration_mins") or 0, 3)
		if actual_mins <= 0:
			actual_mins = get_duration_minutes(
				entry.get("custom_actual_start_date"), entry.get("custom_actual_end_date")
			)

		availability_pct = flt((actual_mins / planned_mins) * 100, 2) if planned_mins > 0 else 0
		availability_pct = min(availability_pct, 100.0)
		performance_pct = flt(entry.get("custom_operator_efficiency_pct") or 0, 2)
		quality_pct = flt((good_qty / total_qty) * 100, 2) if total_qty > 0 else 0
		oee_pct = flt((availability_pct * performance_pct * quality_pct) / 10000, 2)
		item_code = fg_item_map.get(entry.name)

		rows.append(
			{
				"stock_entry": entry.name,
				"posting_date": entry.posting_date,
				"shift": entry.custom_shift,
				"operator": entry.custom_operator,
				"workstation": entry.custom_workstation,
				"item_code": item_code,
				"good_qty": good_qty,
				"rejection_qty": rejection_qty,
				"total_qty": total_qty,
				"availability_pct": availability_pct,
				"performance_pct": performance_pct,
				"quality_pct": quality_pct,
				"oee_pct": oee_pct,
			}
		)

	return rows


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_shift", "custom_operator", "custom_workstation"),
	)
