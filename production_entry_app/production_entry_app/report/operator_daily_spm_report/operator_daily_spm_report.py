from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, get_time

from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	get_duration_minutes,
	get_entry_qty_maps,
)

SETUP_TIME_REASON: str = "Setup Time"


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


def _get_loss_duration_hours(start_time, end_time) -> float:
	if not start_time or not end_time:
		return 0.0
	start = get_time(start_time)
	end = get_time(end_time)
	start_mins = (start.hour * 60) + start.minute + (start.second / 60)
	end_mins = (end.hour * 60) + end.minute + (end.second / 60)
	duration_mins = end_mins - start_mins
	if duration_mins < 0:
		duration_mins += 24 * 60
	return flt(duration_mins / 60, 3) if duration_mins > 0 else 0.0


def _get_shift_duration_map(shift_names: set[str]) -> dict[str, float]:
	if not shift_names:
		return {}
	rows = frappe.get_all(
		"Shift",
		filters={"name": ["in", list(shift_names)]},
		fields=["name", "shift_duration"],
	)
	return {row.get("name"): flt(row.get("shift_duration") or 0, 3) for row in rows if row.get("name")}


def _as_datetime(value) -> datetime.datetime | None:
	if not value:
		return None
	dt = get_datetime(value)
	return dt if isinstance(dt, datetime.datetime) else None


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
		],
		order_by="posting_date asc, custom_operator asc, custom_workstation asc",
	)
	if not entries:
		return []

	entry_names = [entry.get("name") for entry in entries if entry.get("name")]
	good_qty_map, rejection_qty_map, _ = get_entry_qty_maps(entry_names)

	loss_rows = frappe.get_all(
		"Loss Entry",
		filters={"parenttype": "Stock Entry", "parent": ["in", entry_names]},
		fields=["parent", "downtime_reason", "start_time", "end_time"],
	)
	setup_time_map: dict[str, float] = {}
	loss_time_map: dict[str, float] = {}
	for row in loss_rows:
		parent = row.get("parent")
		if not parent:
			continue
		duration_hours = _get_loss_duration_hours(row.get("start_time"), row.get("end_time"))
		if duration_hours <= 0:
			continue
		if row.get("downtime_reason") == SETUP_TIME_REASON:
			setup_time_map[parent] = flt(setup_time_map.get(parent, 0) + duration_hours, 3)
		else:
			loss_time_map[parent] = flt(loss_time_map.get(parent, 0) + duration_hours, 3)

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
				"min_actual_start": None,
				"max_actual_end": None,
			},
		)

		shift_name = entry.get("custom_shift")
		if shift_name:
			agg["shift_names"].add(shift_name)

		if entry_name:
			agg["setting_time_hrs"] += flt(setup_time_map.get(entry_name) or 0, 3)
			agg["loss_time_hrs"] += flt(loss_time_map.get(entry_name) or 0, 3)

		rejection_qty = flt(entry.get("custom_rejection_qty") or 0, 3)
		if rejection_qty <= 0 and entry_name:
			rejection_qty = flt(rejection_qty_map.get(entry_name) or 0, 3)

		fg_completed_qty = flt(entry.get("fg_completed_qty") or 0, 3)
		total_strokes = fg_completed_qty
		if total_strokes <= 0 and entry_name:
			total_strokes = flt(good_qty_map.get(entry_name) or 0, 3) + rejection_qty
		agg["total_strokes"] += flt(total_strokes, 3)

		start_dt = _as_datetime(entry.get("custom_actual_start_date"))
		end_dt = _as_datetime(entry.get("custom_actual_end_date"))
		if start_dt and (not agg["min_actual_start"] or start_dt < agg["min_actual_start"]):
			agg["min_actual_start"] = start_dt
		if end_dt and (not agg["max_actual_end"] or end_dt > agg["max_actual_end"]):
			agg["max_actual_end"] = end_dt

	rows: list[dict] = []
	for key in sorted(aggregates.keys()):
		agg = aggregates[key]
		working_hours = flt(
			sum(shift_duration_map.get(shift_name, 0) for shift_name in agg["shift_names"]),
			3,
		)
		base_prod_mins = get_duration_minutes(agg["min_actual_start"], agg["max_actual_end"])
		setting_time_hrs = flt(agg["setting_time_hrs"], 3)
		loss_time_hrs = flt(agg["loss_time_hrs"], 3)
		production_time_hrs = flt(max((base_prod_mins / 60) - setting_time_hrs - loss_time_hrs, 0), 3)
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
