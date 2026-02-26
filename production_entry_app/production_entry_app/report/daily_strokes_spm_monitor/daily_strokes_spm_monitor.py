from __future__ import annotations

import calendar

import frappe
from frappe import _
from frappe.utils import flt, get_time, getdate

from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	get_entry_qty_maps,
)

SETUP_TIME_REASON: str = "Setup Time"

MONTH_OPTIONS: tuple[str, ...] = (
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
	"January",
	"February",
	"March",
)

MONTH_NAME_TO_NUMBER: dict[str, int] = {
	"January": 1,
	"February": 2,
	"March": 3,
	"April": 4,
	"May": 5,
	"June": 6,
	"July": 7,
	"August": 8,
	"September": 9,
	"October": 10,
	"November": 11,
	"December": 12,
}


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns(filters)
	rows = _get_rows(filters)
	return columns, rows


def _get_columns(filters: dict) -> list[dict]:
	columns: list[dict] = [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 120},
	]
	if not filters.get("custom_operator"):
		columns.append({"label": _("Operator"), "fieldname": "operator", "fieldtype": "Data", "width": 150})
	columns.extend(
		[
			{
				"label": _("Setup Time (Hrs.)"),
				"fieldname": "setup_time_hrs",
				"fieldtype": "Float",
				"width": 130,
			},
			{
				"label": _("Loss Time (Hrs.)"),
				"fieldname": "loss_time_hrs",
				"fieldtype": "Float",
				"width": 130,
			},
			{
				"label": _("Prod. Time (Hrs.)"),
				"fieldname": "prod_time_hrs",
				"fieldtype": "Float",
				"width": 130,
			},
			{"label": _("Total Strokes"), "fieldname": "total_strokes", "fieldtype": "Float", "width": 120},
			{"label": _("SPM"), "fieldname": "spm", "fieldtype": "Float", "width": 90},
			{"label": _("Rejection"), "fieldname": "rejection", "fieldtype": "Float", "width": 100},
		]
	)
	return columns


def _get_date_range(filters: dict) -> tuple[str, str]:
	fiscal_year = filters.get("fiscal_year")
	month_name = filters.get("month")
	if not fiscal_year or not month_name:
		frappe.throw(_("Fiscal Year and Month are required."))

	fy_start = getdate(frappe.db.get_value("Fiscal Year", fiscal_year, "year_start_date"))
	if not fy_start:
		frappe.throw(_("Fiscal Year {0} not found.").format(frappe.bold(fiscal_year)))

	month_num = MONTH_NAME_TO_NUMBER.get(month_name)
	if not month_num:
		frappe.throw(_("Invalid month: {0}").format(frappe.bold(month_name)))

	# April-December use FY start year; January-March use FY start year + 1
	if month_num >= 4:
		year = fy_start.year
	else:
		year = fy_start.year + 1

	last_day = calendar.monthrange(year, month_num)[1]
	from_date = f"{year}-{month_num:02d}-01"
	to_date = f"{year}-{month_num:02d}-{last_day:02d}"
	return from_date, to_date


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


def _get_rows(filters: dict) -> list[dict]:
	from_date, to_date = _get_date_range(filters)
	filters["from_date"] = from_date
	filters["to_date"] = to_date

	db_filters = build_stock_entry_filters(filters, filter_keys=("custom_operator",))
	entries = frappe.get_all(
		"Stock Entry",
		filters=db_filters,
		fields=[
			"name",
			"posting_date",
			"custom_operator",
			"fg_completed_qty",
			"custom_rejection_qty",
			"custom_actual_duration_mins",
		],
		order_by="posting_date asc",
	)
	if not entries:
		return []

	entry_names = [e.get("name") for e in entries if e.get("name")]
	group_by_operator = not filters.get("custom_operator")

	# Fallback qty maps for entries without fg_completed_qty / custom_rejection_qty
	good_qty_map, rejection_qty_map, _ = get_entry_qty_maps(entry_names)

	# Fetch loss entries from Stock Entry unplanned losses only
	loss_rows = frappe.get_all(
		"Loss Entry",
		filters={"parenttype": "Stock Entry", "parent": ["in", entry_names]},
		fields=["parent", "downtime_reason", "start_time", "end_time"],
	)

	# Build loss maps keyed by SE name
	setup_time_map: dict[str, float] = {}
	loss_time_map: dict[str, float] = {}
	for row in loss_rows:
		parent = row.get("parent")
		if not parent:
			continue
		hours = _get_loss_duration_hours(row.get("start_time"), row.get("end_time"))
		if hours <= 0:
			continue
		if row.get("downtime_reason") == SETUP_TIME_REASON:
			setup_time_map[parent] = flt(setup_time_map.get(parent, 0) + hours, 3)
		else:
			loss_time_map[parent] = flt(loss_time_map.get(parent, 0) + hours, 3)

	# Aggregate by group key
	aggregates: dict[tuple, dict] = {}
	for entry in entries:
		posting_date = str(entry.get("posting_date") or "")
		operator = entry.get("custom_operator") or "Unassigned"
		group_key = (posting_date, operator) if group_by_operator else (posting_date,)

		if group_key not in aggregates:
			agg: dict = {
				"date": posting_date,
				"setup_time_hrs": 0.0,
				"loss_time_hrs": 0.0,
				"prod_time_hrs": 0.0,
				"total_strokes": 0.0,
				"rejection": 0.0,
			}
			if group_by_operator:
				agg["operator"] = operator
			aggregates[group_key] = agg

		agg = aggregates[group_key]
		entry_name = entry.get("name")
		rejection_qty = flt(entry.get("custom_rejection_qty") or 0, 3)
		if rejection_qty <= 0 and entry_name:
			rejection_qty = flt(rejection_qty_map.get(entry_name) or 0, 3)
		# fg_completed_qty is the total production quantity (good + rejection).
		# When available, it IS total_strokes directly. When zero (from_bom not
		# set), fall back to good_qty_map (good only) + rejection.
		fg_completed = flt(entry.get("fg_completed_qty") or 0, 3)
		if fg_completed > 0:
			total_strokes = fg_completed
		elif entry_name:
			total_strokes = flt(good_qty_map.get(entry_name, 0) + rejection_qty, 3)
		else:
			total_strokes = rejection_qty
		duration_mins = flt(entry.get("custom_actual_duration_mins") or 0, 3)
		prod_time_hrs = flt(duration_mins / 60, 3) if duration_mins > 0 else 0.0

		agg["setup_time_hrs"] += flt(setup_time_map.get(entry_name, 0), 3)
		agg["loss_time_hrs"] += flt(loss_time_map.get(entry_name, 0), 3)
		agg["prod_time_hrs"] += prod_time_hrs
		agg["total_strokes"] += total_strokes
		agg["rejection"] += rejection_qty

	# Build sorted rows
	rows: list[dict] = []
	for key in sorted(aggregates):
		agg = aggregates[key]
		setup_hrs = flt(agg["setup_time_hrs"], 3)
		loss_hrs = flt(agg["loss_time_hrs"], 3)
		prod_hrs = flt(agg["prod_time_hrs"], 3)
		strokes = flt(agg["total_strokes"], 3)
		rejection = flt(agg["rejection"], 3)
		spm = flt(strokes / (prod_hrs * 60), 3) if prod_hrs > 0 else 0.0

		row: dict = {"date": agg["date"]}
		if group_by_operator:
			row["operator"] = agg.get("operator", "")
		row["setup_time_hrs"] = setup_hrs
		row["loss_time_hrs"] = loss_hrs
		row["prod_time_hrs"] = prod_hrs
		row["total_strokes"] = strokes
		row["spm"] = spm
		row["rejection"] = rejection
		rows.append(row)

	# Append totals row
	if rows:
		rows.append(_build_totals_row(rows, group_by_operator))

	return rows


def _build_totals_row(rows: list[dict], group_by_operator: bool) -> dict:
	total_setup = sum(flt(r["setup_time_hrs"], 3) for r in rows)
	total_loss = sum(flt(r["loss_time_hrs"], 3) for r in rows)
	total_prod = sum(flt(r["prod_time_hrs"], 3) for r in rows)
	total_strokes = sum(flt(r["total_strokes"], 3) for r in rows)
	total_rejection = sum(flt(r["rejection"], 3) for r in rows)
	total_spm = flt(total_strokes / (total_prod * 60), 3) if total_prod > 0 else 0.0

	totals: dict = {"date": _("Total")}
	if group_by_operator:
		totals["operator"] = ""
	totals["setup_time_hrs"] = flt(total_setup, 3)
	totals["loss_time_hrs"] = flt(total_loss, 3)
	totals["prod_time_hrs"] = flt(total_prod, 3)
	totals["total_strokes"] = flt(total_strokes, 3)
	totals["spm"] = total_spm
	totals["rejection"] = flt(total_rejection, 3)
	return totals
