from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, get_time

from production_entry_app.production_entry_app.report.report_utils import (
	get_available_hours_by_day,
	get_entry_production_minutes,
	get_entry_qty_maps,
	get_entry_total_strokes,
	get_planned_loss_hours_by_day,
)

LOSS_BUCKETS: tuple[tuple[str, str], ...] = (
	("setup", "Setup Time"),
	("trial", "Trial Time"),
	("mtrl_handl", "Material Handling Time"),
	("no_operator", "No Operator Time"),
	("no_mtrl", "No Material Time"),
	("maint", "Maintenance Time"),
	("p_maint", "P. Maintenance Time"),
	("tool_break", "Tool Break Time"),
	("other", "Other Time"),
	("no_helper", "No Helper Time"),
	("power_off", "Power Off Time"),
)

LOSS_REASON_TO_BUCKET: dict[str, str] = {
	"Setup Time": "setup",
	"Setup time": "setup",
	"Trial": "trial",
	"Mtrl Handl": "mtrl_handl",
	"No Operator": "no_operator",
	"No Mtrl": "no_mtrl",
	"Maint": "maint",
	"P. Maint": "p_maint",
	"Tool Break": "tool_break",
	"Other": "other",
	"No Helper": "no_helper",
	"Power Off": "power_off",
}


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
	return columns, rows


def _get_columns() -> list[dict]:
	columns = [
		{"label": _("Day"), "fieldname": "day", "fieldtype": "Date", "width": 110},
		{
			"label": _("Workstation"),
			"fieldname": "workstation",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("Strokes Required"),
			"fieldname": "stroke_required",
			"fieldtype": "Float",
			"width": 125,
		},
		{
			"label": _("1st Shift Strokes"),
			"fieldname": "first_shift_strokes",
			"fieldtype": "Float",
			"width": 130,
		},
		{
			"label": _("2nd Shift Strokes"),
			"fieldname": "second_shift_strokes",
			"fieldtype": "Float",
			"width": 130,
		},
		{"label": _("Total Strokes"), "fieldname": "total_strokes", "fieldtype": "Float", "width": 110},
		{"label": _("Rejection"), "fieldname": "rejection", "fieldtype": "Float", "width": 95},
		{"label": _("STD SPM"), "fieldname": "std_spm", "fieldtype": "Float", "width": 95},
		{"label": _("Act SPM"), "fieldname": "act_spm", "fieldtype": "Float", "width": 95},
		{
			"label": _("Productivity (P)"),
			"fieldname": "productivity_pct",
			"fieldtype": "Percent",
			"width": 130,
		},
		{"label": _("Quality (Q)"), "fieldname": "quality_pct", "fieldtype": "Percent", "width": 110},
		{
			"label": _("Availability (A)"),
			"fieldname": "availability_pct",
			"fieldtype": "Percent",
			"width": 130,
		},
		{"label": _("OEE"), "fieldname": "oee", "fieldtype": "Percent", "width": 90},
		{"label": _("OEE Mult %"), "fieldname": "oee_mult_pct", "fieldtype": "Percent", "width": 100},
		{"label": _("Avl. time (hrs)"), "fieldname": "avl_time_hrs", "fieldtype": "Float", "width": 110},
	]

	for key, label in LOSS_BUCKETS:
		columns.append(
			{
				"label": _("1st Shift {0}").format(label),
				"fieldname": f"{key}_1st",
				"fieldtype": "Float",
				"width": 145,
			}
		)
		columns.append(
			{
				"label": _("2nd Shift {0}").format(label),
				"fieldname": f"{key}_2nd",
				"fieldtype": "Float",
				"width": 145,
			}
		)

	columns.extend(
		[
			{
				"label": _("Total Loss Time"),
				"fieldname": "total_loss_time",
				"fieldtype": "Float",
				"width": 120,
			},
			{"label": _("Running Time"), "fieldname": "running_time", "fieldtype": "Float", "width": 105},
		]
	)

	return columns


def _get_rows(filters: dict) -> list[dict]:
	groups = _get_stock_entry_groups(filters)
	if not groups:
		return []

	days = [group["day"] for group in groups.values()]
	available_hours_by_day = get_available_hours_by_day(days)
	planned_loss_hours_by_day = get_planned_loss_hours_by_day(days)

	_get_loss_buckets_from_stock_entry_losses(filters, groups)

	rows = []
	for group in sorted(groups.values(), key=lambda row: (str(row["day"]), str(row["workstation"]))):
		day = group["day"]
		total_day_hours = flt(available_hours_by_day.get(day) or 0, 3)
		planned_loss_hrs = flt(planned_loss_hours_by_day.get(day) or 0, 3)
		avl_time_hrs = flt(max(total_day_hours - planned_loss_hrs, 0), 3)
		total_loss_time = 0.0
		for key, _label in LOSS_BUCKETS:
			total_loss_time += flt(group[f"{key}_1st"], 3)
			total_loss_time += flt(group[f"{key}_2nd"], 3)
		total_loss_time = flt(total_loss_time, 3)

		running_time = flt(max(avl_time_hrs - total_loss_time, 0), 3)
		std_spm = (
			flt(group["standard_spm_weighted_sum"] / group["duration_hours_sum"], 3)
			if group["duration_hours_sum"] > 0
			else 0
		)
		stroke_required = flt(running_time * std_spm * 60, 3)
		total_strokes = flt(group["total_strokes"], 3)
		rejection = flt(group["rejection"], 3)
		act_spm = flt((total_strokes / (running_time * 60)), 3) if running_time > 0 else 0
		productivity_pct = flt((act_spm / std_spm) * 100, 2) if std_spm > 0 else 0
		quality_pct = flt(((total_strokes - rejection) / total_strokes) * 100, 2) if total_strokes > 0 else 0
		availability_pct = flt((running_time / avl_time_hrs) * 100, 2) if avl_time_hrs > 0 else 0
		oee = flt((availability_pct + quality_pct + productivity_pct) / 3, 2)
		oee_mult_pct = flt((availability_pct * quality_pct * productivity_pct) / 10000, 2)

		row = {
			"day": group["day"],
			"workstation": group["workstation"],
			"stroke_required": stroke_required,
			"first_shift_strokes": flt(group["first_shift_strokes"], 3),
			"second_shift_strokes": flt(group["second_shift_strokes"], 3),
			"total_strokes": total_strokes,
			"rejection": rejection,
			"std_spm": std_spm,
			"act_spm": act_spm,
			"productivity_pct": productivity_pct,
			"quality_pct": quality_pct,
			"availability_pct": availability_pct,
			"oee": oee,
			"oee_mult_pct": oee_mult_pct,
			"avl_time_hrs": avl_time_hrs,
			"total_loss_time": total_loss_time,
			"running_time": running_time,
		}

		for key, _label in LOSS_BUCKETS:
			row[f"{key}_1st"] = flt(group[f"{key}_1st"], 3)
			row[f"{key}_2nd"] = flt(group[f"{key}_2nd"], 3)

		rows.append(row)

	return rows


def _get_stock_entry_groups(filters: dict) -> dict[tuple[str, str], dict]:
	stock_entry_filters: dict = {"docstatus": 1, "purpose": "Manufacture"}

	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	if from_date and to_date:
		stock_entry_filters["posting_date"] = ["between", [from_date, to_date]]
	elif from_date:
		stock_entry_filters["posting_date"] = [">=", from_date]
	elif to_date:
		stock_entry_filters["posting_date"] = ["<=", to_date]

	if filters.get("custom_workstation"):
		stock_entry_filters["custom_workstation"] = filters.get("custom_workstation")

	entries = frappe.get_all(
		"Stock Entry",
		filters=stock_entry_filters,
		fields=[
			"name",
			"posting_date",
			"custom_shift",
			"custom_workstation",
			"fg_completed_qty",
			"custom_rejection_qty",
			"custom_standard_spm",
			"custom_actual_duration_mins",
			"custom_production_time_mins",
			"custom_actual_start_date",
			"custom_actual_end_date",
		],
	)
	if not entries:
		return {}

	entry_names = [entry.get("name") for entry in entries if entry.get("name")]
	good_qty_map, rejection_qty_map, _fg_map = get_entry_qty_maps(entry_names, include_fg_item=False)
	shift_labels = _get_shift_label_map(entries)
	groups: dict[tuple[str, str], dict] = {}
	for entry in entries:
		day = str(entry.get("posting_date") or "")
		workstation = entry.get("custom_workstation") or "Unassigned"
		group_key = (day, workstation)
		if group_key not in groups:
			groups[group_key] = _new_group(day, workstation)
		group = groups[group_key]

		total_strokes, rejection_qty = get_entry_total_strokes(
			entry,
			good_qty_map=good_qty_map,
			rejection_qty_map=rejection_qty_map,
		)
		group["total_strokes"] += total_strokes
		group["rejection"] += rejection_qty

		shift_label = shift_labels.get(entry.get("custom_shift"))
		if shift_label == "1":
			group["first_shift_strokes"] += total_strokes
		elif shift_label == "2":
			group["second_shift_strokes"] += total_strokes

		duration_hours = flt(get_entry_production_minutes(entry) / 60, 3)
		standard_spm = flt(entry.get("custom_standard_spm") or 0, 3)
		if duration_hours > 0:
			group["duration_hours_sum"] += duration_hours
			group["standard_spm_weighted_sum"] += standard_spm * duration_hours
		group["standard_spm_sum"] += standard_spm
		group["entry_count"] += 1

	return groups


def _get_shift_label_map(entries: list[frappe._dict]) -> dict[str, str]:
	shift_names = sorted({entry.get("custom_shift") for entry in entries if entry.get("custom_shift")})
	if not shift_names:
		return {}
	rows = frappe.get_all(
		"Shift",
		filters={"name": ["in", shift_names]},
		fields=["name", "shift_label"],
	)
	return {row.get("name"): str(row.get("shift_label") or "") for row in rows if row.get("name")}
def _new_group(day: str, workstation: str) -> dict:
	group = {
		"day": day,
		"workstation": workstation,
		"first_shift_strokes": 0.0,
		"second_shift_strokes": 0.0,
		"total_strokes": 0.0,
		"rejection": 0.0,
		"duration_hours_sum": 0.0,
		"standard_spm_weighted_sum": 0.0,
		"standard_spm_sum": 0.0,
		"entry_count": 0,
	}
	for key, _label in LOSS_BUCKETS:
		group[f"{key}_1st"] = 0.0
		group[f"{key}_2nd"] = 0.0
	return group
def _get_loss_buckets_from_stock_entry_losses(filters: dict, groups: dict[tuple[str, str], dict]) -> None:
	"""Populate OEE loss buckets from Stock Entry child table rows only.

	Shift.planned_losses are shift-level and not workstation-specific. They are
	deducted once at the day availability level (global pool), so bucket columns
	here remain unplanned-loss buckets only.
	"""
	if not groups:
		return

	stock_entry_filters: dict = {"docstatus": 1, "purpose": "Manufacture"}

	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	if from_date and to_date:
		stock_entry_filters["posting_date"] = ["between", [from_date, to_date]]
	elif from_date:
		stock_entry_filters["posting_date"] = [">=", from_date]
	elif to_date:
		stock_entry_filters["posting_date"] = ["<=", to_date]

	if filters.get("custom_workstation"):
		stock_entry_filters["custom_workstation"] = filters.get("custom_workstation")

	entries = frappe.get_all(
		"Stock Entry",
		filters=stock_entry_filters,
		fields=["name", "posting_date", "custom_workstation", "custom_shift"],
	)
	if not entries:
		return

	entry_meta_by_name: dict[str, dict[str, str]] = {}
	for row in entries:
		name = row.get("name")
		if not name:
			continue
		entry_meta_by_name[name] = {
			"day": str(row.get("posting_date") or ""),
			"workstation": row.get("custom_workstation") or "Unassigned",
			"shift": row.get("custom_shift") or "",
		}

	if not entry_meta_by_name:
		return

	loss_rows = frappe.get_all(
		"Loss Entry",
		filters={"parenttype": "Stock Entry", "parent": ["in", list(entry_meta_by_name.keys())]},
		fields=["parent", "downtime_reason", "shift", "start_time", "end_time"],
	)
	if not loss_rows:
		return

	shift_label_by_name: dict[str, str] = {}
	shift_names = sorted(
		{row.get("shift") for row in loss_rows if row.get("shift")}
		| {meta.get("shift") for meta in entry_meta_by_name.values() if meta.get("shift")}
	)
	if shift_names:
		for row in frappe.get_all(
			"Shift",
			filters={"name": ["in", shift_names]},
			fields=["name", "shift_label"],
		):
			shift_label_by_name[row.get("name")] = str(row.get("shift_label") or "")

	for row in loss_rows:
		bucket = LOSS_REASON_TO_BUCKET.get(row.get("downtime_reason") or "")
		if not bucket:
			continue

		entry_meta = entry_meta_by_name.get(row.get("parent") or "")
		if not entry_meta:
			continue

		shift_label = shift_label_by_name.get(row.get("shift") or "") or shift_label_by_name.get(
			entry_meta.get("shift") or ""
		)
		if shift_label not in ("1", "2"):
			continue

		start_time = row.get("start_time")
		end_time = row.get("end_time")
		if not start_time or not end_time:
			continue
		start = get_time(start_time)
		end = get_time(end_time)
		start_mins = (start.hour * 60) + start.minute + (start.second / 60)
		end_mins = (end.hour * 60) + end.minute + (end.second / 60)
		duration_mins = end_mins - start_mins
		if duration_mins < 0:
			# Overnight loss interval (e.g. 23:30 -> 00:30).
			duration_mins += 24 * 60
		if duration_mins <= 0:
			continue
		hours = flt(duration_mins / 60, 3)
		if hours <= 0:
			continue

		group = groups.get((entry_meta["day"], entry_meta["workstation"]))
		if not group:
			continue
		fieldname = f"{bucket}_1st" if shift_label == "1" else f"{bucket}_2nd"
		group[fieldname] += hours
