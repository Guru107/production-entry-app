from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	get_entry_production_minutes,
	get_entry_raw_duration_minutes,
	get_entry_total_strokes,
	get_parent_loss_metrics,
	get_parent_quantity_metrics,
	iter_stock_entries_in_chunks,
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
	return {row.get("name"): flt(row.get("shift_duration") or 0) for row in rows if row.get("name")}


def _get_rows(filters: dict) -> list[dict]:
	aggregates: dict[tuple[str, str, str], dict] = {}
	shift_names: set[str] = set()
	has_entries = False
	for entries in iter_stock_entries_in_chunks(
		_build_filters(filters),
		[
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
		order_by="posting_date asc, name asc",
	):
		has_entries = True
		entry_names = [entry.get("name") for entry in entries if entry.get("name")]
		parent_quantity_metrics = get_parent_quantity_metrics(entry_names)
		parent_loss_metrics = get_parent_loss_metrics(entry_names)
		good_qty_map = {parent: flt(metrics.get("good_qty") or 0) for parent, metrics in parent_quantity_metrics.items()}
		rejection_qty_map = {
			parent: flt(metrics.get("rejection_qty") or 0) for parent, metrics in parent_quantity_metrics.items()
		}
		total_rejected_qty_map = {
			parent: flt(metrics.get("total_rejected_qty") or 0) for parent, metrics in parent_quantity_metrics.items()
		}

		for entry in entries:
			entry_name = entry.get("name")
			loss_metrics = parent_loss_metrics.get(entry_name or "", {})
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
				shift_names.add(shift_name)

			if entry_name:
				agg["setting_time_hrs"] += float(loss_metrics.get("setup_mins") or 0) / 60
				agg["loss_time_hrs"] += float(loss_metrics.get("loss_mins") or 0) / 60

			total_strokes, _rejection_qty = get_entry_total_strokes(
				entry,
				good_qty_map=good_qty_map,
				rejection_qty_map=rejection_qty_map,
				total_rejected_qty_map=total_rejected_qty_map,
			)
			agg["total_strokes"] += float(total_strokes)

			setup_mins = float(loss_metrics.get("setup_mins") or 0)
			loss_mins = float(loss_metrics.get("loss_mins") or 0)
			production_mins = get_entry_production_minutes(entry, setup_mins=setup_mins, loss_mins=loss_mins)
			raw_duration_mins = get_entry_raw_duration_minutes(entry)
			raw_production_mins = max(raw_duration_mins - setup_mins - loss_mins, 0)
			if raw_duration_mins > 0 and abs(raw_production_mins - production_mins) <= 0.01:
				production_mins = raw_production_mins
			agg["production_mins"] += production_mins

	if not has_entries:
		return []

	shift_duration_map = _get_shift_duration_map(shift_names)

	rows: list[dict] = []
	for key in sorted(aggregates.keys()):
		agg = aggregates[key]
		working_hours = sum(shift_duration_map.get(shift_name, 0) for shift_name in agg["shift_names"])
		production_mins = float(agg["production_mins"])
		setting_time_hrs = float(agg["setting_time_hrs"])
		loss_time_hrs = float(agg["loss_time_hrs"])
		production_time_hrs = (production_mins / 60) if production_mins > 0 else 0
		spm = (agg["total_strokes"] / (production_time_hrs * 60)) if production_time_hrs > 0 else 0
		rows.append(
			{
				"date": agg["date"],
				"operator": agg["operator"],
				"workstation": agg["workstation"],
				"working_hours": working_hours,
				"setting_time_hrs": setting_time_hrs,
				"loss_time_hrs": loss_time_hrs,
				"production_time_hrs": production_time_hrs,
				"total_strokes": float(agg["total_strokes"]),
				"spm": spm,
			}
		)

	return rows
