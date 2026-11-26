from __future__ import annotations

import datetime
from collections.abc import Callable, Sequence

import frappe
from frappe import _
from frappe.utils import flt, get_datetime

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	build_overall_row,
	build_stock_entry_filters,
	completed_shift_filters,
	get_entry_output_quantities,
	get_entry_production_minutes,
	get_entry_total_strokes,
	get_loss_duration_minutes,
	get_parent_quantity_metrics,
	get_report_rows,
	iter_stock_entries_in_chunks,
	new_interactive_report_timeout_guard,
	require_date_range,
)
from production_entry_app.production_entry_app.utils.loss_time import (
	build_interval_overlap_filters,
	get_interval_minutes,
	get_interval_overlap,
	merge_intervals,
	resolve_time_interval_in_window,
)
from production_entry_app.production_entry_app.utils.shift_time import (
	combine_date_time,
	get_shift_planned_end_datetime,
)

_SHIFT_WINDOW_FIELDS = [
	"name",
	"shift_date",
	"planned_start_time",
	"shift_end_date",
	"planned_end_time",
	"shift_duration",
]


_ROLLUP_BASE_FIELDS = (
	"quality_total",
	"production_mins_sum",
	"standard_spm_weighted_sum",
)

# Additive columns: a day row, a month row and the Overall Row all carry these sums.
OEE_SUM_FIELDS = (
	"first_shift_strokes",
	"second_shift_strokes",
	"total_strokes",
	"rejection",
	"avl_time_hrs",
	"machine_downtime",
	"total_loss_time",
	"running_time",
	*_ROLLUP_BASE_FIELDS,
)


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
	filters = filters or {}
	require_date_range(filters.get("from_date"), filters.get("to_date"))
	reason_codes = _get_selected_reason_codes(filters)
	columns = _get_columns(filters, reason_codes)
	timeout_guard = new_interactive_report_timeout_guard(_("Production OEE Report"))
	rows = get_rows_with_rollup_bases(filters, timeout_guard, reason_codes)
	if rows:
		rows = [*rows, build_oee_overall_row(rows, "day", get_reason_fieldnames(reason_codes))]
	return columns, [public_row(row) for row in rows]


def get_rows_with_rollup_bases(
	filters: dict,
	timeout_guard: Callable[[], None],
	reason_codes: list[str],
) -> list[dict]:
	"""Return day/workstation OEE rows including bases needed for monthly rollup."""
	return _get_rows(filters, timeout_guard, reason_codes)


def compute_oee_rate_fields(
	*,
	running_time: float,
	avl_time_hrs: float,
	total_strokes: float,
	std_spm: float,
	quality_total: float,
	rejection: float,
) -> dict[str, float]:
	"""Derive SPM and A/Q/P/OEE percentages from summed or daily bases."""
	raw_running_time = flt(running_time)
	act_spm = flt(total_strokes / (raw_running_time * 60)) if raw_running_time > 0 else 0
	productivity_pct = flt((act_spm / std_spm) * 100) if std_spm > 0 else 0
	quality_pct = flt(((quality_total - rejection) / quality_total) * 100) if quality_total > 0 else 0
	availability_pct = flt((raw_running_time / avl_time_hrs) * 100) if avl_time_hrs > 0 else 0
	oee_avg_pct = flt((availability_pct + quality_pct + productivity_pct) / 3)
	oee_mult_pct = flt((availability_pct * quality_pct * productivity_pct) / 10000)
	return {
		"stroke_required": flt(raw_running_time * std_spm * 60),
		"act_spm": act_spm,
		"productivity_pct": productivity_pct,
		"quality_pct": quality_pct,
		"availability_pct": availability_pct,
		"oee_avg_pct": oee_avg_pct,
		"oee_mult_pct": oee_mult_pct,
	}


def get_reason_fieldnames(reason_codes: list[str]) -> list[str]:
	return [_reason_fieldname(code, shift) for code in reason_codes for shift in ("1st", "2nd")]


def build_oee_overall_row(rows: list[dict], label_field: str, reason_fieldnames: Sequence[str] = ()) -> dict:
	"""Overall Row: sum the bases across rows, then recompute the rates (ADR 0010).

	`rows` must still carry the rollup bases. STD SPM is production-time-weighted (ADR 0006); when no
	row has an eligible entry it falls back to the running-time-weighted mean of the row rates.
	"""
	totals = {
		fieldname: flt(sum(flt(row.get(fieldname)) for row in rows))
		for fieldname in (*OEE_SUM_FIELDS, *reason_fieldnames)
	}
	running_time = totals["running_time"]
	if totals["production_mins_sum"] > 0 and totals["standard_spm_weighted_sum"] > 0:
		std_spm = flt(totals["standard_spm_weighted_sum"] / totals["production_mins_sum"])
	elif running_time > 0:
		std_spm = flt(sum(flt(row.get("stroke_required")) for row in rows) / (running_time * 60))
	else:
		std_spm = 0.0
	rate_fields = compute_oee_rate_fields(
		running_time=running_time,
		avl_time_hrs=totals["avl_time_hrs"],
		total_strokes=totals["total_strokes"],
		std_spm=std_spm,
		quality_total=totals["quality_total"],
		rejection=totals["rejection"],
	)
	return build_overall_row(label_field, workstation="", std_spm=std_spm, **totals, **rate_fields)


def public_row(row: dict) -> dict:
	return {key: value for key, value in row.items() if key not in _ROLLUP_BASE_FIELDS}


def _get_selected_reason_codes(filters: dict) -> list[str]:
	value = filters.get("downtime_reason")
	if not value:
		return []
	if isinstance(value, str):
		try:
			parsed = frappe.parse_json(value)
		except ValueError:
			parsed = None
		if isinstance(parsed, list):
			value = parsed
		else:
			value = value.split(",")
	if not isinstance(value, list | tuple | set):
		value = [value]
	return sorted({str(code).strip() for code in value if str(code or "").strip()})


def _get_reason_descriptions(reason_codes: list[str]) -> dict[str, str]:
	if not reason_codes:
		return {}
	rows = get_report_rows(
		"Downtime Reason",
		filters={"name": ["in", reason_codes]},
		fields=["name", "description"],
	)
	return {row.get("name"): str(row.get("description") or "") for row in rows if row.get("name")}


def _reason_fieldname(code: str, shift_suffix: str) -> str:
	return f"reason_{code}_{shift_suffix}"


def _get_columns(filters: dict | None = None, reason_codes: list[str] | None = None) -> list[dict]:
	if reason_codes is None:
		reason_codes = _get_selected_reason_codes(filters or {})
	reason_descriptions = _get_reason_descriptions(reason_codes)
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
		{"label": _("Avg. OEE"), "fieldname": "oee_avg_pct", "fieldtype": "Percent", "width": 90},
		{
			"label": _("OEE %"),
			"fieldname": "oee_mult_pct",
			"fieldtype": "Percent",
			"width": 100,
		},
		{"label": _("Avl. time (hrs)"), "fieldname": "avl_time_hrs", "fieldtype": "Float", "width": 110},
	]

	for code in reason_codes:
		reason_label = reason_descriptions.get(code) or code
		columns.append(
			{
				"label": _("1st Shift {0}").format(reason_label),
				"fieldname": _reason_fieldname(code, "1st"),
				"fieldtype": "Float",
				"width": 145,
			}
		)
		columns.append(
			{
				"label": _("2nd Shift {0}").format(reason_label),
				"fieldname": _reason_fieldname(code, "2nd"),
				"fieldtype": "Float",
				"width": 145,
			}
		)

	columns.extend(
		[
			{
				"label": _("Machine Downtime"),
				"fieldname": "machine_downtime",
				"fieldtype": "Float",
				"width": 140,
			},
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


def _get_rows(
	filters: dict,
	timeout_guard: Callable[[], None],
	reason_codes: list[str],
) -> list[dict]:
	shift_label_cache: dict[str, str] = {}
	groups = _get_stock_entry_groups(filters, shift_label_cache, timeout_guard)
	windows, shift_dates = _completed_windows_for_report(groups, filters)
	_add_downtime_only_groups(groups, filters, timeout_guard, windows, shift_dates)
	if not groups:
		return []

	_finalize_group_metrics(groups, windows)
	timeout_guard()
	planned_by_shift = _planned_loss_intervals_by_shift(windows)
	downtime_by_group = _get_machine_downtime_by_group(
		groups, timeout_guard, windows, shift_dates, planned_by_shift
	)
	# A shift whose linked downtime counts adds its available time, like a production shift (ADR 0004).
	summed_shifts_by_group = {
		key: group["shift_names"] | downtime_by_group[key][1] for key, group in groups.items()
	}
	availability_hours_by_group = _get_availability_hours_by_group(summed_shifts_by_group, timeout_guard)

	rows = []
	for group in sorted(groups.values(), key=lambda row: (str(row["day"]), str(row["workstation"]))):
		group_key = (group["day"], group["workstation"])
		machine_downtime, _linked_shifts, unlinked_shifts = downtime_by_group[group_key]
		avl_time_hrs = flt(
			(availability_hours_by_group.get(group_key) or 0)
			+ _unlinked_downtime_available_hours(
				summed_shifts_by_group[group_key], unlinked_shifts, windows, planned_by_shift
			)
		)
		if group.get("downtime_only") and machine_downtime <= 0:
			continue
		total_loss_time = flt(machine_downtime + sum(group["reason_hours"].values()))

		raw_running_time = 0.0 if group.get("downtime_only") else flt(max(avl_time_hrs - total_loss_time, 0))
		running_time = flt(raw_running_time)
		std_spm = flt(group["standard_spm"])
		total_strokes = flt(group["total_strokes"])
		rejection = flt(group["quality_rejection"])
		quality_total = flt(group["quality_total"])
		rate_fields = compute_oee_rate_fields(
			running_time=raw_running_time,
			avl_time_hrs=avl_time_hrs,
			total_strokes=total_strokes,
			std_spm=std_spm,
			quality_total=quality_total,
			rejection=rejection,
		)

		row = {
			"day": group["day"],
			"workstation": group["workstation"],
			"first_shift_strokes": flt(group["first_shift_strokes"]),
			"second_shift_strokes": flt(group["second_shift_strokes"]),
			"total_strokes": total_strokes,
			"rejection": rejection,
			"std_spm": std_spm,
			"avl_time_hrs": avl_time_hrs,
			"machine_downtime": machine_downtime,
			"total_loss_time": total_loss_time,
			"running_time": running_time,
			"quality_total": quality_total,
			"production_mins_sum": flt(group.get("production_mins_sum") or 0),
			"standard_spm_weighted_sum": flt(group.get("standard_spm_weighted_sum") or 0),
			**rate_fields,
		}

		for code in reason_codes:
			row[_reason_fieldname(code, "1st")] = flt(group["reason_hours"].get((code, "1"), 0))
			row[_reason_fieldname(code, "2nd")] = flt(group["reason_hours"].get((code, "2"), 0))

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
		parent_quantity_metrics = get_parent_quantity_metrics(entry_names)
		for entry in chunk:
			_add_stock_entry_to_group(
				groups,
				entry_meta_by_name,
				entry,
				parent_quantity_metrics,
				shift_labels,
			)

		_apply_loss_reasons_for_chunk(groups, entry_meta_by_name, loss_rows, shift_labels)
		_keep_loss_rows_on_groups(groups, entry_meta_by_name, loss_rows)

	if not has_rows:
		return {}

	return groups


def _finalize_group_metrics(
	groups: dict[tuple[str, str], dict],
	windows: dict[str, tuple[datetime.datetime, datetime.datetime]],
) -> None:
	workstation_spm = _get_workstation_standard_spm(
		{str(group.get("workstation") or "") for group in groups.values()}
	)
	for group in groups.values():
		group["reason_hours"] = {
			key: _merged_interval_hours(
				[
					interval
					for start_time, end_time, shift_name in loss_times
					if (window := windows.get(shift_name))
					and (interval := _clip_clock_times_to_window(start_time, end_time, window))
				]
			)
			for key, loss_times in (group.get("reason_intervals") or {}).items()
		}
		production_mins = flt(group.get("production_mins_sum") or 0)
		weighted_sum = flt(group.get("standard_spm_weighted_sum") or 0)
		if production_mins > 0 and weighted_sum > 0:
			group["standard_spm"] = flt(weighted_sum / production_mins)
		else:
			workstation = str(group.get("workstation") or "")
			group["standard_spm"] = flt(workstation_spm.get(workstation) or 0)


def _get_workstation_standard_spm(workstations: set[str]) -> dict[str, float]:
	names = sorted({name for name in workstations if name and name != "Unassigned"})
	if not names:
		return {}
	rows = get_report_rows(
		"Workstation",
		filters={"name": ["in", names]},
		fields=["name", "custom_pea_standard_spm"],
		limit_page_length=0,
	)
	return {
		str(row.get("name")): flt(row.get("custom_pea_standard_spm") or 0) for row in rows if row.get("name")
	}


def _merged_interval_hours(intervals: list[tuple[datetime.datetime, datetime.datetime]]) -> float:
	return flt(sum(get_interval_minutes(*interval) for interval in merge_intervals(intervals)) / 60)


def _get_stock_entry_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_pea_workstation", "custom_pea_operation"),
	)


def _get_stock_entry_fields() -> list[str]:
	return [
		"name",
		"posting_date",
		"custom_pea_shift",
		"custom_pea_workstation",
		"fg_completed_qty",
		"custom_pea_rejection_qty",
		"custom_pea_total_strokes",
		"custom_pea_lh_gross_qty",
		"custom_pea_lh_rejection_qty",
		"custom_pea_rh_gross_qty",
		"custom_pea_rh_rejection_qty",
		"custom_pea_operation",
		"custom_pea_standard_spm",
		"custom_pea_actual_duration_mins",
		"custom_pea_production_time_mins",
		"custom_pea_actual_start_date",
		"custom_pea_actual_end_date",
	]


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
	parent_quantity_metrics: dict[str, dict[str, float]],
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
	if entry_name:
		group["entry_shifts"][entry_name] = entry.get("custom_pea_shift") or ""
	_add_entry_quantities_to_group(
		group,
		entry,
		parent_quantity_metrics,
		shift_labels,
	)


def _add_entry_quantities_to_group(
	group: dict,
	entry: frappe._dict,
	parent_quantity_metrics: dict[str, dict[str, float]],
	shift_labels: dict[str, str],
) -> None:
	quantities = get_entry_output_quantities(
		entry,
		normal_metrics=parent_quantity_metrics.get(entry.get("name")),
	)
	total_strokes, _rejection_qty = get_entry_total_strokes(entry)
	shift_name = entry.get("custom_pea_shift")
	group["total_strokes"] += total_strokes
	group["quality_total"] += quantities.total_qty
	group["quality_rejection"] += quantities.rejection_qty

	if shift_name:
		group["shift_names"].add(shift_name)
	shift_label = shift_labels.get(shift_name)
	if shift_label == "1":
		group["first_shift_strokes"] += total_strokes
	elif shift_label == "2":
		group["second_shift_strokes"] += total_strokes

	standard_spm = flt(entry.get("custom_pea_standard_spm") or 0)
	production_mins = flt(get_entry_production_minutes(entry))
	if standard_spm > 0 and production_mins > 0:
		group["production_mins_sum"] = flt(group["production_mins_sum"] + production_mins)
		group["standard_spm_weighted_sum"] = flt(
			group["standard_spm_weighted_sum"] + (standard_spm * production_mins)
		)


def _get_availability_hours_by_group(
	shift_names_by_group: dict[tuple[str, str], set[str]],
	timeout_guard,
) -> dict[tuple[str, str], float]:
	timeout_guard()
	shift_names = sorted(
		{
			shift_name
			for group_shift_names in shift_names_by_group.values()
			for shift_name in group_shift_names
			if shift_name
		}
	)
	if not shift_names:
		return {key: 0.0 for key in shift_names_by_group}

	timeout_guard()
	shift_duration_hours_by_name = _get_shift_duration_hours_by_name(shift_names)

	timeout_guard()
	planned_loss_hours_by_shift = _get_planned_loss_hours_by_shift(shift_duration_hours_by_name)

	availability_hours_by_group: dict[tuple[str, str], float] = {}
	for key, group_shift_names in shift_names_by_group.items():
		timeout_guard()
		availability_hours_by_group[key] = _get_group_availability_hours(
			group_shift_names,
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
	shift_names: set[str],
	shift_duration_hours_by_name: dict[str, float],
	planned_loss_hours_by_shift: dict[str, float],
) -> float:
	total_shift_hours = 0.0
	total_planned_loss_hours = 0.0
	for shift_name in shift_names:
		total_shift_hours += flt(shift_duration_hours_by_name.get(shift_name) or 0)
		total_planned_loss_hours += flt(planned_loss_hours_by_shift.get(shift_name) or 0)
	return flt(max(total_shift_hours - total_planned_loss_hours, 0))


def _completed_windows_for_report(
	groups: dict[tuple[str, str], dict],
	filters: dict,
) -> tuple[dict[str, tuple[datetime.datetime, datetime.datetime]], dict[str, str]]:
	if filters.get("custom_pea_operation"):
		days = sorted({str(group.get("day") or "") for group in groups.values() if group.get("day")})
		return _get_completed_shift_windows(days)
	return _get_completed_shift_windows_in_range(filters)


def _get_machine_downtime_by_group(
	groups: dict[tuple[str, str], dict],
	timeout_guard: Callable[[], None],
	windows: dict[str, tuple[datetime.datetime, datetime.datetime]],
	shift_dates: dict[str, str],
	planned_by_shift: dict[str, list[tuple[datetime.datetime, datetime.datetime]]],
) -> dict[tuple[str, str], tuple[float, set[str], set[str]]]:
	"""Per group: Machine Downtime hours, linked shifts and unlinked shifts whose downtime counts."""
	timeout_guard()
	if not windows:
		return {key: (0.0, set(), set()) for key in groups}

	workstations = sorted({str(group.get("workstation") or "") for group in groups.values()})
	overall_start = min(start for start, _end in windows.values())
	overall_end = max(end for _start, end in windows.values())
	timeout_guard()
	downtime_rows = _get_downtime_rows(workstations, overall_start, overall_end)
	covered_by_group = _get_covered_loss_intervals_by_group(groups, windows)
	rows_by_workstation: dict[str | None, list[dict]] = {}
	for row in downtime_rows:
		rows_by_workstation.setdefault(row.get("workstation"), []).append(row)
	downtime_by_group: dict[tuple[str, str], tuple[float, set[str], set[str]]] = {}
	for key, group in groups.items():
		timeout_guard()
		downtime_by_group[key] = _sum_machine_downtime_hours(
			group,
			windows,
			shift_dates,
			rows_by_workstation.get(group.get("workstation"), []),
			covered_by_group.get(key, []),
			planned_by_shift,
		)
	return downtime_by_group


def _get_completed_shift_windows(
	days: list[str],
) -> tuple[dict[str, tuple[datetime.datetime, datetime.datetime]], dict[str, str]]:
	if not days:
		return {}, {}
	return _load_shift_windows({"shift_date": ["in", days], "status": "Completed"})


def _add_downtime_only_groups(
	groups: dict[tuple[str, str], dict],
	filters: dict,
	timeout_guard: Callable[[], None],
	windows: dict[str, tuple[datetime.datetime, datetime.datetime]],
	shift_dates: dict[str, str],
) -> None:
	if filters.get("custom_pea_operation") or not windows:
		return
	timeout_guard()
	overall_start = min(start for start, _end in windows.values())
	overall_end = max(end for _start, end in windows.values())
	workstation_filter = filters.get("custom_pea_workstation")
	downtime_rows = _get_downtime_rows(
		[workstation_filter] if workstation_filter else None,
		overall_start,
		overall_end,
	)
	for row in downtime_rows:
		workstation = row.get("workstation") or "Unassigned"
		for shift_name in _shifts_joined_by_downtime(row, windows):
			day = shift_dates.get(shift_name or "")
			if not day:
				continue
			key = (day, workstation)
			existing = groups.get(key)
			if existing and not existing.get("downtime_only"):
				continue
			group = existing or _new_group(day, workstation)
			group["downtime_only"] = True
			groups[key] = group


def _get_completed_shift_windows_in_range(
	filters: dict,
) -> tuple[dict[str, tuple[datetime.datetime, datetime.datetime]], dict[str, str]]:
	return _load_shift_windows(completed_shift_filters(filters.get("from_date"), filters.get("to_date")))


def _load_shift_windows(
	filters: dict,
) -> tuple[dict[str, tuple[datetime.datetime, datetime.datetime]], dict[str, str]]:
	rows = get_report_rows(
		"Shift",
		filters=filters,
		fields=_SHIFT_WINDOW_FIELDS,
		limit_page_length=0,
	)
	return _shift_windows_from_rows(rows)


def _shift_windows_from_rows(
	rows: list[dict],
) -> tuple[dict[str, tuple[datetime.datetime, datetime.datetime]], dict[str, str]]:
	windows: dict[str, tuple[datetime.datetime, datetime.datetime]] = {}
	shift_dates: dict[str, str] = {}
	for row in rows:
		shift_name = row.get("name")
		shift_date = str(row.get("shift_date") or "")
		if not shift_name or not shift_date or not row.get("planned_start_time"):
			continue
		start_dt = combine_date_time(row.get("shift_date"), row.get("planned_start_time"))
		end_dt = get_shift_planned_end_datetime(
			shift_date=row.get("shift_date"),
			planned_start_time=row.get("planned_start_time"),
			planned_end_time=row.get("planned_end_time"),
			shift_end_date=row.get("shift_end_date"),
			shift_duration=row.get("shift_duration"),
		)
		if end_dt and end_dt > start_dt:
			windows[shift_name] = (start_dt, end_dt)
			shift_dates[shift_name] = shift_date
	return windows, shift_dates


def _shifts_joined_by_downtime(
	row: dict,
	windows: dict[str, tuple[datetime.datetime, datetime.datetime]],
) -> list[str]:
	return [shift_name for shift_name, _overlap in _downtime_overlaps_by_shift(row, windows)]


def _downtime_overlaps_by_shift(
	row: dict,
	windows: dict[str, tuple[datetime.datetime, datetime.datetime]],
) -> list[tuple[str, tuple[datetime.datetime, datetime.datetime]]]:
	start_dt = get_datetime(row.get("from_time")) if row.get("from_time") else None
	end_dt = get_datetime(row.get("to_time")) if row.get("to_time") else None
	if not start_dt or not end_dt or end_dt <= start_dt:
		return []
	linked_shift = row.get("custom_pea_shift")
	candidates = [linked_shift] if linked_shift else list(windows)
	overlaps: list[tuple[str, tuple[datetime.datetime, datetime.datetime]]] = []
	for shift_name in candidates:
		window = windows.get(shift_name or "")
		if not window:
			continue
		overlap = get_interval_overlap(start_dt, end_dt, window[0], window[1])
		if overlap and shift_name:
			overlaps.append((shift_name, overlap))
	return overlaps


def _get_downtime_rows(
	workstations: list[str] | None,
	overall_start: datetime.datetime,
	overall_end: datetime.datetime,
) -> list[dict]:
	if workstations is not None and not workstations:
		return []
	filters: list = [
		*build_interval_overlap_filters("from_time", "to_time", overall_start, overall_end),
		["docstatus", "!=", 2],
	]
	if workstations:
		filters.insert(0, ["workstation", "in", workstations])
	return get_report_rows(
		"Downtime Entry",
		filters=filters,
		fields=["name", "workstation", "from_time", "to_time", "custom_pea_shift"],
		limit_page_length=0,
	)


def _sum_machine_downtime_hours(
	group: dict,
	windows: dict[str, tuple[datetime.datetime, datetime.datetime]],
	shift_dates: dict[str, str],
	downtime_rows: list[dict],
	covered_intervals: list[tuple[datetime.datetime, datetime.datetime]],
	planned_by_shift: dict[str, list[tuple[datetime.datetime, datetime.datetime]]],
) -> tuple[float, set[str], set[str]]:
	"""Return Machine Downtime hours and the linked / unlinked shifts whose downtime counts.

	downtime_rows must already be limited to the group's workstation.
	"""
	day = str(group.get("day") or "")
	day_windows = {
		shift_name: windows[shift_name]
		for shift_name, shift_day in shift_dates.items()
		if shift_day == day and shift_name in windows
	}
	uncovered: list[tuple[datetime.datetime, datetime.datetime]] = []
	linked_shifts: set[str] = set()
	unlinked_shifts: set[str] = set()
	for row in downtime_rows:
		for shift_name, overlap in _downtime_overlaps_by_shift(row, day_windows):
			blockers = [*covered_intervals, *planned_by_shift.get(shift_name, [])]
			counted = _subtract_intervals(overlap, blockers)
			if counted:
				(linked_shifts if row.get("custom_pea_shift") else unlinked_shifts).add(shift_name)
			uncovered.extend(counted)
	total_mins = sum(get_interval_minutes(*interval) for interval in merge_intervals(uncovered))
	return flt(total_mins / 60), linked_shifts, unlinked_shifts


def _unlinked_downtime_available_hours(
	summed_shifts: set[str],
	unlinked_shifts: set[str],
	windows: dict[str, tuple[datetime.datetime, datetime.datetime]],
	planned_by_shift: dict[str, list[tuple[datetime.datetime, datetime.datetime]]],
) -> float:
	"""Union of the unlinked-downtime shifts' windows less planned losses and the summed shifts' windows."""
	counted_windows = [windows[name] for name in summed_shifts if name in windows]
	available: list[tuple[datetime.datetime, datetime.datetime]] = []
	for shift_name in unlinked_shifts:
		blockers = [*planned_by_shift.get(shift_name, []), *counted_windows]
		available.extend(_subtract_intervals(windows[shift_name], blockers))
	return _merged_interval_hours(available)


def _get_covered_loss_intervals_by_group(
	groups: dict[tuple[str, str], dict],
	windows: dict[str, tuple[datetime.datetime, datetime.datetime]],
) -> dict[tuple[str, str], list[tuple[datetime.datetime, datetime.datetime]]]:
	intervals: dict[tuple[str, str], list[tuple[datetime.datetime, datetime.datetime]]] = {
		key: [] for key in groups
	}
	for key, group in groups.items():
		entry_shifts = group.get("entry_shifts") or {}
		for row in group.pop("loss_rows", []):  # free the rows once consumed
			shift_name = row.get("shift") or entry_shifts.get(row.get("parent") or "")
			window = windows.get(shift_name or "")
			if not window:
				continue
			overlap = _clip_clock_times_to_window(row.get("start_time"), row.get("end_time"), window)
			if overlap:
				intervals[key].append(overlap)
	return intervals


def _planned_loss_intervals_by_shift(
	windows: dict[str, tuple[datetime.datetime, datetime.datetime]],
) -> dict[str, list[tuple[datetime.datetime, datetime.datetime]]]:
	if not windows:
		return {}
	loss_rows = get_report_rows(
		"Loss Entry",
		filters={"parenttype": "Shift", "parent": ["in", list(windows)]},
		fields=["parent", "start_time", "end_time"],
	)
	intervals: dict[str, list[tuple[datetime.datetime, datetime.datetime]]] = {}
	for row in loss_rows:
		shift_name = row.get("parent")
		window = windows.get(shift_name or "")
		if not shift_name or not window:
			continue
		overlap = _clip_clock_times_to_window(row.get("start_time"), row.get("end_time"), window)
		if overlap:
			intervals.setdefault(shift_name, []).append(overlap)
	return intervals


def _clip_clock_times_to_window(
	start_time: str | datetime.time | None,
	end_time: str | datetime.time | None,
	window: tuple[datetime.datetime, datetime.datetime],
) -> tuple[datetime.datetime, datetime.datetime] | None:
	resolved = resolve_time_interval_in_window(start_time, end_time, window[0], window[1])
	if not resolved:
		return None
	return get_interval_overlap(resolved[0], resolved[1], window[0], window[1])


def _subtract_intervals(
	interval: tuple[datetime.datetime, datetime.datetime],
	blockers: list[tuple[datetime.datetime, datetime.datetime]],
) -> list[tuple[datetime.datetime, datetime.datetime]]:
	remaining = [interval]
	for block_start, block_end in blockers:
		next_remaining: list[tuple[datetime.datetime, datetime.datetime]] = []
		for start_dt, end_dt in remaining:
			overlap = get_interval_overlap(start_dt, end_dt, block_start, block_end)
			if not overlap:
				next_remaining.append((start_dt, end_dt))
				continue
			if start_dt < overlap[0]:
				next_remaining.append((start_dt, overlap[0]))
			if overlap[1] < end_dt:
				next_remaining.append((overlap[1], end_dt))
		remaining = next_remaining
	return remaining


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
	return {
		"day": day,
		"workstation": workstation,
		"shift_names": set(),
		"first_shift_strokes": 0.0,
		"second_shift_strokes": 0.0,
		"total_strokes": 0.0,
		"quality_total": 0.0,
		"quality_rejection": 0.0,
		"standard_spm": 0.0,
		"standard_spm_weighted_sum": 0.0,
		"production_mins_sum": 0.0,
		"entry_shifts": {},
		"reason_intervals": {},
		"reason_hours": {},
		"loss_rows": [],
	}


def _apply_loss_reasons_for_chunk(
	groups: dict[tuple[str, str], dict],
	entry_meta_by_name: dict[str, dict[str, str]],
	loss_rows: list[dict],
	shift_label_by_name: dict[str, str],
) -> None:
	if not groups or not entry_meta_by_name or not loss_rows:
		return
	for row in loss_rows:
		_apply_loss_reason_row(groups, entry_meta_by_name, row, shift_label_by_name)


def _apply_loss_reason_row(
	groups: dict[tuple[str, str], dict],
	entry_meta_by_name: dict[str, dict[str, str]],
	row: dict,
	shift_label_by_name: dict[str, str],
) -> None:
	reason_code = str(row.get("downtime_reason") or "").strip()
	entry_meta = entry_meta_by_name.get(row.get("parent") or "")
	if not reason_code or not entry_meta:
		return

	shift_label = _get_loss_shift_label(row, entry_meta, shift_label_by_name)
	if shift_label not in ("1", "2"):
		return

	group = groups.get((entry_meta["day"], entry_meta["workstation"]))
	if not group:
		return
	key = (reason_code, shift_label)
	# Resolved to datetimes in _finalize_group_metrics, once the shift windows are loaded.
	loss_times = (row.get("start_time"), row.get("end_time"), entry_meta["shift"])
	group.setdefault("reason_intervals", {}).setdefault(key, []).append(loss_times)


def _keep_loss_rows_on_groups(
	groups: dict[tuple[str, str], dict],
	entry_meta_by_name: dict[str, dict[str, str]],
	loss_rows: list[dict],
) -> None:
	"""Keep each Stock Entry Loss Entry row on its group so covered intervals need no re-read."""
	for row in loss_rows:
		entry_meta = entry_meta_by_name.get(row.get("parent") or "")
		group = entry_meta and groups.get((entry_meta["day"], entry_meta["workstation"]))
		if group:
			group["loss_rows"].append(row)


def _get_loss_shift_label(
	row: dict,
	entry_meta: dict[str, str],
	shift_label_by_name: dict[str, str],
) -> str:
	return shift_label_by_name.get(row.get("shift") or "") or shift_label_by_name.get(
		entry_meta.get("shift") or ""
	)
