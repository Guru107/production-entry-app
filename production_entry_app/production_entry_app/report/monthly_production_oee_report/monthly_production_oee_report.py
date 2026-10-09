from __future__ import annotations

import calendar
from collections.abc import Callable

import frappe
from frappe import _
from frappe.utils import flt, getdate

from production_entry_app.production_entry_app.report.production_oee_report import (
	production_oee_report as daily_oee,
)
from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	new_interactive_report_timeout_guard,
)

_SUM_FIELDS = (
	"first_shift_strokes",
	"second_shift_strokes",
	"total_strokes",
	"rejection",
	"avl_time_hrs",
	"machine_downtime",
	"total_loss_time",
	"running_time",
	"quality_total",
	"production_mins_sum",
	"standard_spm_weighted_sum",
)


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
	filters = filters or {}
	reason_codes = daily_oee._get_selected_reason_codes(filters)
	columns = _get_columns(filters, reason_codes)
	timeout_guard = new_interactive_report_timeout_guard(_("Monthly Production OEE Report"))
	rows = _get_rows(filters, timeout_guard, reason_codes)
	return columns, rows


def _get_columns(filters: dict | None = None, reason_codes: list[str] | None = None) -> list[dict]:
	if reason_codes is None:
		reason_codes = daily_oee._get_selected_reason_codes(filters or {})
	daily_columns = daily_oee._get_columns(filters, reason_codes)
	columns: list[dict] = []
	for column in daily_columns:
		if column.get("fieldname") == "day":
			columns.append(
				{
					"label": _("Month"),
					"fieldname": "month",
					"fieldtype": "Data",
					"width": 110,
				}
			)
			continue
		columns.append(column)
	return apply_system_precision(columns)


def _get_rows(
	filters: dict,
	timeout_guard: Callable[[], None],
	reason_codes: list[str],
) -> list[dict]:
	month_key, daily_filters = _month_filters(filters)
	timeout_guard()
	daily_rows = daily_oee.get_rows_with_rollup_bases(daily_filters, timeout_guard, reason_codes)
	timeout_guard()
	if not daily_rows:
		return []

	aggregates: dict[str, dict] = {}
	reason_fieldnames = [
		fieldname
		for code in reason_codes
		for fieldname in (
			daily_oee._reason_fieldname(code, "1st"),
			daily_oee._reason_fieldname(code, "2nd"),
		)
	]

	for daily_row in daily_rows:
		workstation = str(daily_row.get("workstation") or "Unassigned")
		if workstation not in aggregates:
			aggregates[workstation] = _new_month_aggregate(month_key, workstation, reason_fieldnames)
		agg = aggregates[workstation]
		for fieldname in _SUM_FIELDS:
			agg[fieldname] = flt(agg[fieldname] + flt(daily_row.get(fieldname) or 0))
		for fieldname in reason_fieldnames:
			agg[fieldname] = flt(agg[fieldname] + flt(daily_row.get(fieldname) or 0))
		fallback_spm = flt(daily_row.get("std_spm") or 0)
		if fallback_spm > 0 and flt(agg.get("fallback_std_spm") or 0) <= 0:
			agg["fallback_std_spm"] = fallback_spm

	rows = []
	for workstation in sorted(aggregates):
		timeout_guard()
		rows.append(_finalize_month_row(aggregates[workstation], reason_fieldnames))
	return rows


def _month_filters(filters: dict) -> tuple[str, dict]:
	year = _require_int_filter(filters, "year", _("Year"))
	month = _require_int_filter(filters, "month", _("Month"))
	if month < 1 or month > 12:
		frappe.throw(_("Month must be between 1 and 12."))
	last_day = calendar.monthrange(year, month)[1]
	from_date = getdate(f"{year:04d}-{month:02d}-01")
	to_date = getdate(f"{year:04d}-{month:02d}-{last_day:02d}")
	month_key = f"{year:04d}-{month:02d}"
	daily_filters = {
		key: value for key, value in filters.items() if key not in {"year", "month", "from_date", "to_date"}
	}
	daily_filters["from_date"] = from_date
	daily_filters["to_date"] = to_date
	return month_key, daily_filters


def _require_int_filter(filters: dict, fieldname: str, label: str) -> int:
	value = filters.get(fieldname)
	if value in (None, ""):
		frappe.throw(_("{0} is required.").format(label))
	try:
		return int(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be a whole number.").format(label))


def _new_month_aggregate(month_key: str, workstation: str, reason_fieldnames: list[str]) -> dict:
	agg: dict = {
		"month": month_key,
		"workstation": workstation,
		"fallback_std_spm": 0.0,
	}
	for fieldname in _SUM_FIELDS:
		agg[fieldname] = 0.0
	for fieldname in reason_fieldnames:
		agg[fieldname] = 0.0
	return agg


def _finalize_month_row(agg: dict, reason_fieldnames: list[str]) -> dict:
	avl_time_hrs = flt(agg["avl_time_hrs"])
	running_time = flt(agg["running_time"])
	production_mins = flt(agg["production_mins_sum"])
	weighted_sum = flt(agg["standard_spm_weighted_sum"])
	if production_mins > 0 and weighted_sum > 0:
		std_spm = flt(weighted_sum / production_mins)
	else:
		std_spm = flt(agg.get("fallback_std_spm") or 0)

	total_strokes = flt(agg["total_strokes"])
	rejection = flt(agg["rejection"])
	quality_total = flt(agg["quality_total"])
	rate_fields = daily_oee.compute_oee_rate_fields(
		running_time=running_time,
		avl_time_hrs=avl_time_hrs,
		total_strokes=total_strokes,
		std_spm=std_spm,
		quality_total=quality_total,
		rejection=rejection,
	)

	row = {
		"month": agg["month"],
		"workstation": agg["workstation"],
		"first_shift_strokes": flt(agg["first_shift_strokes"]),
		"second_shift_strokes": flt(agg["second_shift_strokes"]),
		"total_strokes": total_strokes,
		"rejection": rejection,
		"std_spm": std_spm,
		"avl_time_hrs": avl_time_hrs,
		"machine_downtime": flt(agg["machine_downtime"]),
		"total_loss_time": flt(agg["total_loss_time"]),
		"running_time": running_time,
		**rate_fields,
	}
	for fieldname in reason_fieldnames:
		row[fieldname] = flt(agg[fieldname])
	return row
