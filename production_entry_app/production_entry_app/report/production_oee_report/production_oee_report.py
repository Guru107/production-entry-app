from __future__ import annotations

from typing import NamedTuple

import frappe
from frappe import _
from frappe.utils import flt, get_time

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	build_stock_entry_filters,
	get_entry_production_minutes,
	get_entry_total_strokes,
	get_loss_duration_minutes,
	get_parent_quantity_metrics,
	get_report_rows,
	iter_stock_entries_in_chunks,
	new_interactive_report_timeout_guard,
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


class _EntryQuantityMaps(NamedTuple):
	good_qty: dict[str, float]
	rejection_qty: dict[str, float]
	total_rejected_qty: dict[str, float]


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	timeout_guard = new_interactive_report_timeout_guard(_("Production OEE Report"))
	rows = _get_rows(filters, timeout_guard)
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
		{
			"label": _("Quality (Q)"),
			"fieldname": "quality_pct",
			"fieldtype": "Percent",
			"width": 110,
		},
		{
			"label": _("Availability (A)"),
			"fieldname": "availability_pct",
			"fieldtype": "Percent",
			"width": 130,
		},
		{"label": _("OEE"), "fieldname": "oee", "fieldtype": "Percent", "width": 90},
		{
			"label": _("OEE Mult %"),
			"fieldname": "oee_mult_pct",
			"fieldtype": "Percent",
			"width": 100,
		},
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

	return apply_system_precision(columns)


def _get_rows(filters: dict, timeout_guard) -> list[dict]:
	shift_label_cache: dict[str, str] = {}
	groups = _get_stock_entry_groups(filters, shift_label_cache, timeout_guard)
	if not groups:
		return []

	timeout_guard()
	availability_hours_by_group = _get_availability_hours_by_group(groups, timeout_guard)

	rows = []
	for group in sorted(groups.values(), key=lambda row: (str(row["day"]), str(row["workstation"]))):
		avl_time_hrs = flt(availability_hours_by_group.get((group["day"], group["workstation"])) or 0)
		total_loss_time = 0.0
		for key, _label in LOSS_BUCKETS:
			total_loss_time += flt(group[f"{key}_1st"])
			total_loss_time += flt(group[f"{key}_2nd"])
		total_loss_time = flt(total_loss_time)

		raw_running_time = flt(max(avl_time_hrs - total_loss_time, 0))
		running_time = flt(raw_running_time)
		std_spm = flt(group["standard_spm"])
		stroke_required = flt(raw_running_time * std_spm * 60)
		total_strokes = flt(group["total_strokes"])
		rejection = flt(group["quality_rejection"])
		act_spm = flt(total_strokes / (raw_running_time * 60)) if raw_running_time > 0 else 0
		productivity_pct = flt((act_spm / std_spm) * 100) if std_spm > 0 else 0
		quality_total = flt(group["quality_total"])
		quality_pct = flt(((quality_total - rejection) / quality_total) * 100) if quality_total > 0 else 0
		availability_pct = flt((raw_running_time / avl_time_hrs) * 100) if avl_time_hrs > 0 else 0
		oee = flt((availability_pct + quality_pct + productivity_pct) / 3)
		oee_mult_pct = flt((availability_pct * quality_pct * productivity_pct) / 10000)

		row = {
			"day": group["day"],
			"workstation": group["workstation"],
			"stroke_required": stroke_required,
			"first_shift_strokes": flt(group["first_shift_strokes"]),
			"second_shift_strokes": flt(group["second_shift_strokes"]),
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
			row[f"{key}_1st"] = flt(group[f"{key}_1st"])
			row[f"{key}_2nd"] = flt(group[f"{key}_2nd"])

		rows.append(row)

	return rows


def _get_stock_entry_groups(
	filters: dict,
	shift_label_cache: dict[str, str],
	timeout_guard,
) -> dict[tuple[str, str], dict]:
	stock_entry_filters = _get_stock_entry_filters(filters)
	groups: dict[tuple[str, str], dict] = {}
	has_rows = False
	for chunk in iter_stock_entries_in_chunks(stock_entry_filters, _get_stock_entry_fields()):
		timeout_guard()
		has_rows = True
		entry_names = [entry.get("name") for entry in chunk if entry.get("name")]
		loss_rows = _get_stock_entry_loss_rows(entry_names)
		shift_names = _get_shift_names_for_chunk(chunk, loss_rows)
		shift_labels = _get_shift_labels(shift_names, shift_label_cache)
		entry_meta_by_name: dict[str, dict[str, str]] = {}
		quantity_maps = _get_entry_quantity_maps(entry_names)

		for entry in chunk:
			_add_stock_entry_to_group(
				groups,
				entry_meta_by_name,
				entry,
				quantity_maps,
				shift_labels,
			)

		_apply_loss_buckets_for_chunk(groups, entry_meta_by_name, loss_rows, shift_labels)

	if not has_rows:
		return {}

	return groups


def _get_stock_entry_filters(filters: dict) -> dict:
	return build_stock_entry_filters(filters, filter_keys=("custom_pea_workstation",))


def _get_stock_entry_fields() -> list[str]:
	return [
		"name",
		"posting_date",
		"custom_pea_shift",
		"custom_pea_workstation",
		"fg_completed_qty",
		"custom_pea_rejection_qty",
		"custom_pea_is_joint_lh_rh",
		"custom_pea_total_strokes",
		"custom_pea_lh_gross_qty",
		"custom_pea_lh_rejection_qty",
		"custom_pea_rh_gross_qty",
		"custom_pea_rh_rejection_qty",
		"custom_pea_standard_spm",
		"custom_pea_actual_duration_mins",
		"custom_pea_production_time_mins",
		"custom_pea_actual_start_date",
		"custom_pea_actual_end_date",
	]


def _get_entry_quantity_maps(
	entry_names: list[str],
) -> _EntryQuantityMaps:
	parent_quantity_metrics = get_parent_quantity_metrics(entry_names)
	good_qty_map = {
		parent: flt(metrics.get("good_qty") or 0) for parent, metrics in parent_quantity_metrics.items()
	}
	rejection_qty_map = {
		parent: flt(metrics.get("rejection_qty") or 0) for parent, metrics in parent_quantity_metrics.items()
	}
	total_rejected_qty_map = {
		parent: flt(metrics.get("total_rejected_qty") or 0)
		for parent, metrics in parent_quantity_metrics.items()
	}
	return _EntryQuantityMaps(good_qty_map, rejection_qty_map, total_rejected_qty_map)


def _get_stock_entry_loss_rows(entry_names: list[str]) -> list[dict]:
	if not entry_names:
		return []
	return get_report_rows(
		"Loss Entry",
		filters={"parenttype": "Stock Entry", "parent": ["in", entry_names]},
		fields=["parent", "downtime_reason", "shift", "start_time", "end_time"],
	)


def _get_shift_names_for_chunk(chunk: list[frappe._dict], loss_rows: list[dict]) -> set[str]:
	return {entry.get("custom_pea_shift") for entry in chunk if entry.get("custom_pea_shift")} | {
		row.get("shift") for row in loss_rows if row.get("shift")
	}


def _add_stock_entry_to_group(
	groups: dict[tuple[str, str], dict],
	entry_meta_by_name: dict[str, dict[str, str]],
	entry: frappe._dict,
	quantity_maps: _EntryQuantityMaps,
	shift_labels: dict[str, str],
) -> None:
	day = str(entry.get("production_date") or "")
	if not day:
		return
	workstation = entry.get("custom_pea_workstation") or "Unassigned"
	entry_name = entry.get("name")
	if entry_name:
		entry_meta_by_name[entry_name] = {
			"day": day,
			"workstation": workstation,
			"shift": entry.get("custom_pea_shift") or "",
		}
	group = groups.setdefault((day, workstation), _new_group(day, workstation))
	_add_entry_quantities_to_group(
		group,
		entry,
		quantity_maps,
		shift_labels,
	)


def _add_entry_quantities_to_group(
	group: dict,
	entry: frappe._dict,
	quantity_maps: _EntryQuantityMaps,
	shift_labels: dict[str, str],
) -> None:
	entry_name = entry.get("name")
	total_strokes, rejection_qty = get_entry_total_strokes(
		entry,
		rejection_qty_map=quantity_maps.rejection_qty,
	)
	good_qty = flt(quantity_maps.good_qty.get(entry_name) or 0)
	total_rejected_qty = flt(quantity_maps.total_rejected_qty.get(entry_name) or 0)
	shift_name = entry.get("custom_pea_shift")
	group["total_strokes"] += total_strokes
	if entry.get("custom_pea_is_joint_lh_rh"):
		group["quality_total"] += flt(entry.get("custom_pea_lh_gross_qty")) + flt(
			entry.get("custom_pea_rh_gross_qty")
		)
		group["quality_rejection"] += flt(entry.get("custom_pea_lh_rejection_qty")) + flt(
			entry.get("custom_pea_rh_rejection_qty")
		)
	else:
		group["quality_total"] += good_qty + total_rejected_qty
		group["quality_rejection"] += rejection_qty

	if shift_name:
		group["shift_names"].add(shift_name)
	shift_label = shift_labels.get(shift_name)
	if shift_label == "1":
		group["first_shift_strokes"] += total_strokes
	elif shift_label == "2":
		group["second_shift_strokes"] += total_strokes

	standard_spm = flt(entry.get("custom_pea_standard_spm") or 0)
	if standard_spm > 0 and group["standard_spm"] <= 0:
		group["standard_spm"] = standard_spm


def _get_availability_hours_by_group(
	groups: dict[tuple[str, str], dict],
	timeout_guard,
) -> dict[tuple[str, str], float]:
	timeout_guard()
	shift_names = sorted(
		{
			shift_name
			for group in groups.values()
			for shift_name in group.get("shift_names", set())
			if shift_name
		}
	)
	if not shift_names:
		return {(day, workstation): 0.0 for day, workstation in groups}

	timeout_guard()
	shift_duration_hours_by_name = _get_shift_duration_hours_by_name(shift_names)

	timeout_guard()
	planned_loss_hours_by_shift = _get_planned_loss_hours_by_shift(shift_duration_hours_by_name)

	availability_hours_by_group: dict[tuple[str, str], float] = {}
	for key, group in groups.items():
		timeout_guard()
		availability_hours_by_group[key] = _get_group_availability_hours(
			group,
			shift_duration_hours_by_name,
			planned_loss_hours_by_shift,
		)
	return availability_hours_by_group


def _get_shift_duration_hours_by_name(shift_names: list[str]) -> dict[str, float]:
	shift_rows = get_report_rows(
		"Shift",
		filters={
			"name": ["in", shift_names],
			"status": ["in", ["Running", "Completed"]],
		},
		fields=["name", "shift_duration"],
		limit_page_length=0,
	)
	return {row.get("name"): flt(row.get("shift_duration") or 0) for row in shift_rows if row.get("name")}


def _get_planned_loss_hours_by_shift(shift_duration_hours_by_name: dict[str, float]) -> dict[str, float]:
	loss_rows = get_report_rows(
		"Loss Entry",
		filters={"parenttype": "Shift", "parent": ["in", list(shift_duration_hours_by_name.keys())]},
		fields=["parent", "start_time", "end_time"],
	)
	planned_loss_hours_by_shift: dict[str, float] = {
		shift_name: 0.0 for shift_name in shift_duration_hours_by_name
	}
	for row in loss_rows:
		shift_name = row.get("parent")
		if not shift_name:
			continue
		duration_mins = get_loss_duration_minutes(row.get("start_time"), row.get("end_time"))
		if duration_mins <= 0:
			continue
		planned_loss_hours_by_shift[shift_name] = flt(
			planned_loss_hours_by_shift.get(shift_name, 0) + (duration_mins / 60)
		)
	return planned_loss_hours_by_shift


def _get_group_availability_hours(
	group: dict,
	shift_duration_hours_by_name: dict[str, float],
	planned_loss_hours_by_shift: dict[str, float],
) -> float:
	total_shift_hours = 0.0
	total_planned_loss_hours = 0.0
	for shift_name in group.get("shift_names", set()):
		total_shift_hours += flt(shift_duration_hours_by_name.get(shift_name) or 0)
		total_planned_loss_hours += flt(planned_loss_hours_by_shift.get(shift_name) or 0)
	return flt(max(total_shift_hours - total_planned_loss_hours, 0))


def _get_shift_label_map(
	entries: list[frappe._dict],
	shift_label_cache: dict[str, str],
) -> dict[str, str]:
	shift_names = sorted(
		{entry.get("custom_pea_shift") for entry in entries if entry.get("custom_pea_shift")}
	)
	return _get_shift_labels(shift_names, shift_label_cache)


def _get_shift_labels(
	shift_names: list[str] | set[str],
	shift_label_cache: dict[str, str],
) -> dict[str, str]:
	if not shift_names:
		return {}
	missing_shift_names = sorted(
		{shift_name for shift_name in shift_names if shift_name and shift_name not in shift_label_cache}
	)
	if missing_shift_names:
		rows = get_report_rows(
			"Shift",
			filters={"name": ["in", missing_shift_names]},
			fields=["name", "shift_label"],
			limit_page_length=0,
		)
		fetched_shift_labels = {
			row.get("name"): str(row.get("shift_label") or "") for row in rows if row.get("name")
		}
		shift_label_cache.update(fetched_shift_labels)
		for shift_name in missing_shift_names:
			shift_label_cache.setdefault(shift_name, "")
	return {
		shift_name: str(shift_label_cache.get(shift_name) or "") for shift_name in shift_names if shift_name
	}


def _new_group(day: str, workstation: str) -> dict:
	group = {
		"day": day,
		"workstation": workstation,
		"shift_names": set(),
		"first_shift_strokes": 0.0,
		"second_shift_strokes": 0.0,
		"total_strokes": 0.0,
		"quality_total": 0.0,
		"quality_rejection": 0.0,
		"standard_spm": 0.0,
	}
	for key, _label in LOSS_BUCKETS:
		group[f"{key}_1st"] = 0.0
		group[f"{key}_2nd"] = 0.0
	return group


def _apply_loss_buckets_for_chunk(
	groups: dict[tuple[str, str], dict],
	entry_meta_by_name: dict[str, dict[str, str]],
	loss_rows: list[dict],
	shift_label_by_name: dict[str, str],
) -> None:
	if not groups or not entry_meta_by_name or not loss_rows:
		return
	for row in loss_rows:
		_apply_loss_bucket_row(groups, entry_meta_by_name, row, shift_label_by_name)


def _apply_loss_bucket_row(
	groups: dict[tuple[str, str], dict],
	entry_meta_by_name: dict[str, dict[str, str]],
	row: dict,
	shift_label_by_name: dict[str, str],
) -> None:
	bucket = LOSS_REASON_TO_BUCKET.get(row.get("downtime_reason") or "")
	entry_meta = entry_meta_by_name.get(row.get("parent") or "")
	if not bucket or not entry_meta:
		return

	shift_label = _get_loss_shift_label(row, entry_meta, shift_label_by_name)
	hours = _get_loss_hours(row)
	if shift_label not in ("1", "2") or hours <= 0:
		return

	group = groups.get((entry_meta["day"], entry_meta["workstation"]))
	if not group:
		return
	fieldname = f"{bucket}_1st" if shift_label == "1" else f"{bucket}_2nd"
	group[fieldname] += hours


def _get_loss_shift_label(
	row: dict,
	entry_meta: dict[str, str],
	shift_label_by_name: dict[str, str],
) -> str:
	return shift_label_by_name.get(row.get("shift") or "") or shift_label_by_name.get(
		entry_meta.get("shift") or ""
	)


def _get_loss_hours(row: dict) -> float:
	start_time = row.get("start_time")
	end_time = row.get("end_time")
	if not start_time or not end_time:
		return 0.0
	start = get_time(start_time)
	end = get_time(end_time)
	start_mins = (start.hour * 60) + start.minute + (start.second / 60)
	end_mins = (end.hour * 60) + end.minute + (end.second / 60)
	duration_mins = end_mins - start_mins
	if duration_mins < 0:
		duration_mins += 24 * 60
	return flt(duration_mins / 60) if duration_mins > 0 else 0.0
