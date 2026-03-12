from __future__ import annotations

import calendar

import frappe
from frappe import _
from frappe.utils import flt, getdate

from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	get_entry_production_minutes,
	get_entry_total_strokes,
	get_parent_loss_metrics,
	get_parent_quantity_metrics,
	iter_stock_entries_in_chunks,
)

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
			{"label": _("Rework"), "fieldname": "rework", "fieldtype": "Float", "width": 100},
		]
	)
	return columns


def _get_date_range(filters: dict) -> tuple[str, str]:
	fiscal_year = filters.get("fiscal_year")
	month_name = filters.get("month")
	if not fiscal_year or not month_name:
		frappe.throw(_("Fiscal Year and Month are required."))

	fy_dates = frappe.db.get_value(
		"Fiscal Year",
		fiscal_year,
		["year_start_date", "year_end_date"],
		as_dict=True,
	)
	if not fy_dates or not fy_dates.get("year_start_date") or not fy_dates.get("year_end_date"):
		frappe.throw(_("Fiscal Year {0} not found.").format(frappe.bold(fiscal_year)))
	fy_start = getdate(fy_dates.get("year_start_date"))
	fy_end = getdate(fy_dates.get("year_end_date"))
	if fy_end < fy_start:
		frappe.throw(_("Fiscal Year {0} has invalid date boundaries.").format(frappe.bold(fiscal_year)))

	month_num = MONTH_NAME_TO_NUMBER.get(month_name)
	if not month_num:
		frappe.throw(_("Invalid month: {0}").format(frappe.bold(month_name)))

	start_month = fy_start.month
	end_month = fy_end.month
	if fy_start.year == fy_end.year:
		if not (start_month <= month_num <= end_month):
			frappe.throw(
				_("Month {0} is outside Fiscal Year {1}.").format(
					frappe.bold(month_name), frappe.bold(fiscal_year)
				)
			)
		year = fy_start.year
	elif month_num >= start_month:
		year = fy_start.year
	elif month_num <= end_month:
		year = fy_end.year
	else:
		frappe.throw(
			_("Month {0} is outside Fiscal Year {1}.").format(
				frappe.bold(month_name), frappe.bold(fiscal_year)
			)
		)

	last_day = calendar.monthrange(year, month_num)[1]
	from_date = f"{year}-{month_num:02d}-01"
	to_date = f"{year}-{month_num:02d}-{last_day:02d}"
	return from_date, to_date


def _get_rows(filters: dict) -> list[dict]:
	from_date, to_date = _get_date_range(filters)
	filters["from_date"] = from_date
	filters["to_date"] = to_date

	db_filters = build_stock_entry_filters(filters, filter_keys=("custom_operator",))
	group_by_operator = not filters.get("custom_operator")

	# Aggregate by group key
	aggregates: dict[tuple, dict] = {}
	has_entries = False
	for entries in iter_stock_entries_in_chunks(
		db_filters,
		[
			"name",
			"posting_date",
			"custom_operator",
			"fg_completed_qty",
			"custom_rejection_qty",
			"custom_rework_qty",
			"custom_actual_duration_mins",
			"custom_production_time_mins",
		],
		order_by="posting_date asc, name asc",
	):
		has_entries = True
		entry_names = [e.get("name") for e in entries if e.get("name")]
		parent_quantity_metrics = get_parent_quantity_metrics(entry_names, include_rework=True)
		parent_loss_metrics = get_parent_loss_metrics(entry_names)
		good_qty_map = {
			parent: flt(metrics.get("good_qty") or 0)
			for parent, metrics in parent_quantity_metrics.items()
		}
		rejection_qty_map = {
			parent: flt(metrics.get("rejection_qty") or 0)
			for parent, metrics in parent_quantity_metrics.items()
		}
		total_rejected_qty_map = {
			parent: flt(metrics.get("total_rejected_qty") or 0)
			for parent, metrics in parent_quantity_metrics.items()
		}

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
					"rework": 0.0,
				}
				if group_by_operator:
					agg["operator"] = operator
				aggregates[group_key] = agg

			agg = aggregates[group_key]
			entry_name = entry.get("name")
			entry_metrics = parent_quantity_metrics.get(entry_name or "", {})
			loss_metrics = parent_loss_metrics.get(entry_name or "", {})
			setup_mins = flt(loss_metrics.get("setup_mins") or 0)
			loss_mins = flt(loss_metrics.get("loss_mins") or 0)
			setup_hrs = flt(setup_mins / 60)
			loss_hrs = flt(loss_mins / 60)
			rework_qty = flt(entry.get("custom_rework_qty") or entry_metrics.get("rework_qty") or 0)
			total_strokes, rejection_qty = get_entry_total_strokes(
				entry,
				good_qty_map=good_qty_map,
				rejection_qty_map=rejection_qty_map,
				total_rejected_qty_map=total_rejected_qty_map,
			)
			production_time_mins = get_entry_production_minutes(
				entry,
				setup_mins=setup_mins,
				loss_mins=loss_mins,
			)
			production_time_hrs = flt(production_time_mins / 60) if production_time_mins > 0 else 0.0

			agg["setup_time_hrs"] += setup_hrs
			agg["loss_time_hrs"] += loss_hrs
			agg["prod_time_hrs"] += production_time_hrs
			agg["total_strokes"] += total_strokes
			agg["rejection"] += rejection_qty
			agg["rework"] += rework_qty

	if not has_entries:
		return []

	# Build sorted rows
	rows: list[dict] = []
	for key in sorted(aggregates):
		agg = aggregates[key]
		setup_hrs = flt(agg["setup_time_hrs"])
		loss_hrs = flt(agg["loss_time_hrs"])
		prod_hrs = flt(agg["prod_time_hrs"])
		strokes = flt(agg["total_strokes"])
		rejection = flt(agg["rejection"])
		rework = flt(agg["rework"])
		spm = flt(strokes / (prod_hrs * 60)) if prod_hrs > 0 else 0.0

		row: dict = {"date": agg["date"]}
		if group_by_operator:
			row["operator"] = agg.get("operator", "")
		row["setup_time_hrs"] = setup_hrs
		row["loss_time_hrs"] = loss_hrs
		row["prod_time_hrs"] = prod_hrs
		row["total_strokes"] = strokes
		row["spm"] = spm
		row["rejection"] = rejection
		row["rework"] = rework
		rows.append(row)

	# Append totals row
	if rows:
		rows.append(_build_totals_row(rows, group_by_operator))

	return rows


def _build_totals_row(rows: list[dict], group_by_operator: bool) -> dict:
	total_setup = sum(flt(r["setup_time_hrs"]) for r in rows)
	total_loss = sum(flt(r["loss_time_hrs"]) for r in rows)
	total_prod = sum(flt(r["prod_time_hrs"]) for r in rows)
	total_strokes = sum(flt(r["total_strokes"]) for r in rows)
	total_rejection = sum(flt(r["rejection"]) for r in rows)
	total_rework = sum(flt(r["rework"]) for r in rows)
	total_spm = flt(total_strokes / (total_prod * 60)) if total_prod > 0 else 0.0

	totals: dict = {"date": _("Total")}
	if group_by_operator:
		totals["operator"] = ""
	totals["setup_time_hrs"] = flt(total_setup)
	totals["loss_time_hrs"] = flt(total_loss)
	totals["prod_time_hrs"] = flt(total_prod)
	totals["total_strokes"] = flt(total_strokes)
	totals["spm"] = total_spm
	totals["rejection"] = flt(total_rejection)
	totals["rework"] = flt(total_rework)
	return totals
