from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
)
from production_entry_app.production_entry_app.utils.die_tool_counter import get_counter_health


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
	return columns, rows


def _get_columns() -> list[dict]:
	return apply_system_precision(
		[
			{
				"label": _("Die Tool Item"),
				"fieldname": "die_tool_item",
				"fieldtype": "Link",
				"options": "Item",
				"width": 180,
			},
			{
				"label": _("Current Stroke Count"),
				"fieldname": "current_stroke_count",
				"fieldtype": "Float",
				"width": 160,
			},
			{
				"label": _("Max Stroke Count"),
				"fieldname": "stroke_capacity",
				"fieldtype": "Float",
				"width": 140,
			},
			{
				"label": _("Utilization %"),
				"fieldname": "utilization_pct",
				"fieldtype": "Percent",
				"width": 110,
			},
			{
				"label": _("Warning Threshold %"),
				"fieldname": "warning_threshold_pct",
				"fieldtype": "Percent",
				"width": 140,
			},
			{
				"label": _("Maintenance Due"),
				"fieldname": "maintenance_due",
				"fieldtype": "Check",
				"width": 120,
			},
			{
				"label": _("Last Maintenance Date"),
				"fieldname": "last_maintenance_date",
				"fieldtype": "Datetime",
				"width": 180,
			},
			{
				"label": _("Maintenance Count"),
				"fieldname": "maintenance_count",
				"fieldtype": "Int",
				"width": 140,
			},
			{
				"label": _("Last Reset On"),
				"fieldname": "last_reset_on",
				"fieldtype": "Datetime",
				"width": 160,
			},
			{
				"label": _("Last Reset By"),
				"fieldname": "last_reset_by",
				"fieldtype": "Link",
				"options": "User",
				"width": 140,
			},
		]
	)


def _get_rows(filters: dict) -> list[dict]:
	counter_filters = {}
	if filters.get("item_code"):
		counter_filters["die_tool_item"] = filters.get("item_code")

	counters = frappe.get_list(
		"Die Tool Counter",
		filters=counter_filters,
		fields=[
			"die_tool_item",
			"current_stroke_count",
			"stroke_capacity",
			"warning_threshold_pct",
			"last_reset_on",
			"last_reset_by",
		],
		order_by="die_tool_item asc",
		limit_page_length=0,
	)

	maintenance_filters = {"docstatus": 1}
	if filters.get("item_code"):
		maintenance_filters["die_tool_item"] = filters.get("item_code")

	maintenance_rows = frappe.get_list(
		"Die Tool Maintenance Log",
		filters=maintenance_filters,
		fields=["die_tool_item", "maintenance_date"],
		limit_page_length=0,
	)
	maintenance_map: dict[str, dict] = {}
	for maintenance_row in maintenance_rows:
		die_tool_item = maintenance_row.get("die_tool_item")
		if not die_tool_item:
			continue

		summary = maintenance_map.setdefault(
			die_tool_item,
			{"last_maintenance_date": None, "maintenance_count": 0},
		)
		summary["maintenance_count"] += 1
		maintenance_date = maintenance_row.get("maintenance_date")
		if maintenance_date and (
			not summary["last_maintenance_date"] or maintenance_date > summary["last_maintenance_date"]
		):
			summary["last_maintenance_date"] = maintenance_date

	rows = []
	for counter in counters:
		stroke_capacity = flt(counter.get("stroke_capacity") or 0)
		current_strokes = flt(counter.get("current_stroke_count") or 0)
		warning_threshold_pct = float(counter.get("warning_threshold_pct") or 90)
		utilization_pct, maintenance_due = get_counter_health(
			current_strokes=current_strokes,
			stroke_capacity=stroke_capacity,
			warning_threshold_pct=warning_threshold_pct,
		)

		maintenance = maintenance_map.get(counter.get("die_tool_item"), {})
		rows.append(
			{
				"die_tool_item": counter.get("die_tool_item"),
				"current_stroke_count": current_strokes,
				"stroke_capacity": stroke_capacity,
				"utilization_pct": utilization_pct,
				"warning_threshold_pct": warning_threshold_pct,
				"maintenance_due": maintenance_due,
				"last_maintenance_date": maintenance.get("last_maintenance_date"),
				"maintenance_count": int(maintenance.get("maintenance_count") or 0),
				"last_reset_on": counter.get("last_reset_on"),
				"last_reset_by": counter.get("last_reset_by"),
			}
		)
	return rows
