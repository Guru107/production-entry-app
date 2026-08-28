from __future__ import annotations

from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
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
	columns = _get_columns(filters)
	rows = _get_rows(filters)
	return columns, rows


def _get_columns(filters: dict) -> list[dict]:
	columns: list[dict] = [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 120},
	]
	if not filters.get("custom_pea_operator"):
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
	return apply_system_precision(columns)


def _get_rows(filters: dict) -> list[dict]:
	db_filters = build_stock_entry_filters(filters, filter_keys=("custom_pea_operator",))
	group_by_operator = not filters.get("custom_pea_operator")

	# Aggregate by group key
	aggregates: dict[tuple, dict] = {}
	has_entries = False
	for entries in iter_stock_entries_in_chunks(
		db_filters,
		[
			"name",
			"posting_date",
			"custom_pea_operator",
			"fg_completed_qty",
			"custom_pea_rejection_qty",
			"custom_pea_rework_qty",
			"custom_pea_actual_duration_mins",
			"custom_pea_production_time_mins",
		],
		order_by="posting_date asc, name asc",
	):
		has_entries = True
		entry_names = [e.get("name") for e in entries if e.get("name")]
		parent_quantity_metrics = get_parent_quantity_metrics(entry_names, include_rework=True)
		parent_loss_metrics = get_parent_loss_metrics(entry_names)
		good_qty_map = {
			parent: flt(metrics.get("good_qty") or 0) for parent, metrics in parent_quantity_metrics.items()
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
			production_date = str(entry.get("production_date") or "")
			operator = entry.get("custom_pea_operator") or "Unassigned"
			group_key = (production_date, operator) if group_by_operator else (production_date,)

			if group_key not in aggregates:
				agg: dict = {
					"date": production_date,
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
			setup_mins = float(loss_metrics.get("setup_mins") or 0)
			loss_mins = float(loss_metrics.get("loss_mins") or 0)
			setup_hrs = setup_mins / 60
			loss_hrs = loss_mins / 60
			rework_qty = float(entry.get("custom_pea_rework_qty") or entry_metrics.get("rework_qty") or 0)
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
			if production_time_mins <= 0 and entry.get("custom_pea_production_time_mins") is not None:
				raw_duration_mins = get_entry_raw_duration_minutes(entry)
				production_time_mins = max(raw_duration_mins - setup_mins - loss_mins, 0)
			production_time_hrs = (production_time_mins / 60) if production_time_mins > 0 else 0.0

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
		setup_hrs = float(agg["setup_time_hrs"])
		loss_hrs = float(agg["loss_time_hrs"])
		prod_hrs = float(agg["prod_time_hrs"])
		strokes = float(agg["total_strokes"])
		rejection = float(agg["rejection"])
		rework = float(agg["rework"])
		spm = (strokes / (prod_hrs * 60)) if prod_hrs > 0 else 0.0

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
	total_setup = sum(float(r["setup_time_hrs"]) for r in rows)
	total_loss = sum(float(r["loss_time_hrs"]) for r in rows)
	total_prod = sum(float(r["prod_time_hrs"]) for r in rows)
	total_strokes = sum(float(r["total_strokes"]) for r in rows)
	total_rejection = sum(float(r["rejection"]) for r in rows)
	total_rework = sum(float(r["rework"]) for r in rows)
	total_spm = (total_strokes / (total_prod * 60)) if total_prod > 0 else 0.0

	totals: dict = {"date": _("Total")}
	if group_by_operator:
		totals["operator"] = ""
	totals["setup_time_hrs"] = total_setup
	totals["loss_time_hrs"] = total_loss
	totals["prod_time_hrs"] = total_prod
	totals["total_strokes"] = total_strokes
	totals["spm"] = total_spm
	totals["rejection"] = total_rejection
	totals["rework"] = total_rework
	return totals
