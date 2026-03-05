from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	get_entry_production_minutes,
	get_entry_qty_maps,
	get_entry_total_strokes,
	get_loss_time_maps,
)


def execute(filters: dict | None = None):
	filters = filters or {}
	return _get_columns(), _get_rows(filters)


def _get_columns() -> list[dict]:
	return [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 120},
		{
			"label": _("Operator"),
			"fieldname": "operator",
			"fieldtype": "Link",
			"options": "Operator",
			"width": 160,
		},
		{
			"label": _("Workstation"),
			"fieldname": "workstation",
			"fieldtype": "Link",
			"options": "Workstation",
			"width": 160,
		},
		{"label": _("Working Hours"), "fieldname": "working_hours", "fieldtype": "Float", "width": 120},
		{
			"label": _("Setting Time (Hrs)"),
			"fieldname": "setting_time_hrs",
			"fieldtype": "Float",
			"width": 130,
		},
		{"label": _("Loss Time (Hrs)"), "fieldname": "loss_time_hrs", "fieldtype": "Float", "width": 130},
		{
			"label": _("Production Time (Hrs)"),
			"fieldname": "production_time_hrs",
			"fieldtype": "Float",
			"width": 150,
		},
		{"label": _("Total Strokes"), "fieldname": "total_strokes", "fieldtype": "Float", "width": 120},
		{"label": _("SPM"), "fieldname": "spm", "fieldtype": "Float", "width": 100},
	]


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_operator", "custom_workstation", "custom_shift"),
	)


def _get_shift_duration_map(shift_names: set[str]) -> dict[str, float]:
	if not shift_names:
		return {}
	rows = frappe.get_all(
		"Shift",
		filters={"name": ["in", list(shift_names)]},
		fields=["name", "shift_duration"],
	)
	return {row.get("name"): flt(row.get("shift_duration") or 0, 3) for row in rows if row.get("name")}


def _get_rows(filters: dict) -> list[dict]:
	entries = frappe.get_all(
		"Stock Entry",
		filters=_build_filters(filters),
		fields=[
			"name",
			"posting_date",
			"custom_operator",
			"custom_workstation",
			"custom_shift",
			"fg_completed_qty",
			"custom_rejection_qty",
			"custom_actual_start_date",
			"custom_actual_end_date",
			"custom_production_time_mins",
		],
		order_by="posting_date asc, custom_operator asc, custom_workstation asc",
	)
	if not entries:
		return []

	entry_names = [entry.get("name") for entry in entries if entry.get("name")]
	good_qty_map, rejection_qty_map, _ = get_entry_qty_maps(entry_names)
	setup_time_map, loss_time_map = get_loss_time_maps(entry_names)

	shift_duration_map = _get_shift_duration_map(
		{entry.get("custom_shift") for entry in entries if entry.get("custom_shift")}
	)

	aggregates: dict[tuple[str, str, str], dict] = {}
	for entry in entries:
		entry_name = entry.get("name")
		posting_date = str(entry.get("posting_date") or "")
		operator = entry.get("custom_operator") or "Unassigned"
		workstation = entry.get("custom_workstation") or "Unassigned"
		group_key = (posting_date, operator, workstation)
		agg = aggregates.setdefault(
			group_key,
			{
				"date": posting_date,
				"operator": operator,
				"workstation": workstation,
				"shift_names": set(),
				"setting_time_hrs": 0.0,
				"loss_time_hrs": 0.0,
				"total_strokes": 0.0,
				"production_mins": 0.0,
			},
		)

		shift_name = entry.get("custom_shift")
		if shift_name:
			agg["shift_names"].add(shift_name)

		if entry_name:
			agg["setting_time_hrs"] += flt((setup_time_map.get(entry_name) or 0) / 60, 3)
			agg["loss_time_hrs"] += flt((loss_time_map.get(entry_name) or 0) / 60, 3)

		total_strokes, _rejection_qty = get_entry_total_strokes(
			entry,
			good_qty_map=good_qty_map,
			rejection_qty_map=rejection_qty_map,
		)
		agg["total_strokes"] += flt(total_strokes, 3)

		agg["production_mins"] += get_entry_production_minutes(
			entry,
			setup_mins=flt(setup_time_map.get(entry_name) or 0, 3) if entry_name else 0,
			loss_mins=flt(loss_time_map.get(entry_name) or 0, 3) if entry_name else 0,
		)

	rows: list[dict] = []
	for key in sorted(aggregates.keys()):
		agg = aggregates[key]
		working_hours = flt(
			sum(shift_duration_map.get(shift_name, 0) for shift_name in agg["shift_names"]),
			3,
		)
		production_mins = flt(agg["production_mins"], 3)
		setting_time_hrs = flt(agg["setting_time_hrs"], 3)
		loss_time_hrs = flt(agg["loss_time_hrs"], 3)
		production_time_hrs = flt(production_mins / 60, 3) if production_mins > 0 else 0
		spm = flt((agg["total_strokes"] / (production_time_hrs * 60)), 3) if production_time_hrs > 0 else 0
		rows.append(
			{
				"date": agg["date"],
				"operator": agg["operator"],
				"workstation": agg["workstation"],
				"working_hours": working_hours,
				"setting_time_hrs": setting_time_hrs,
				"loss_time_hrs": loss_time_hrs,
				"production_time_hrs": production_time_hrs,
				"total_strokes": flt(agg["total_strokes"], 3),
				"spm": spm,
			}
		)

	return rows
