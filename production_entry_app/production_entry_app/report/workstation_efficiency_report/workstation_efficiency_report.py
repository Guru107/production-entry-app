from __future__ import annotations

from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	accumulate_efficiency_aggregate,
	build_efficiency_rows,
	build_stock_entry_filters,
	get_entry_production_minutes,
	get_entry_raw_duration_minutes,
	get_entry_total_strokes,
	get_parent_loss_metrics,
	get_parent_quantity_metrics,
	iter_stock_entries_in_chunks,
	new_efficiency_aggregates,
	new_interactive_report_timeout_guard,
)


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(
		filters,
		timeout_guard=new_interactive_report_timeout_guard(_("Workstation Efficiency Report")),
	)
	return columns, rows


def _get_columns() -> list[dict]:
	return [
		{
			"label": _("Workstation"),
			"fieldname": "workstation",
			"fieldtype": "Link",
			"options": "Workstation",
			"width": 180,
		},
		{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 90},
		{"label": _("Good Qty"), "fieldname": "good_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Rejection Qty"), "fieldname": "rejection_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Rework Qty"), "fieldname": "rework_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Total Units"), "fieldname": "total_units", "fieldtype": "Float", "width": 120},
		{"label": _("Actual SPM"), "fieldname": "actual_spm", "fieldtype": "Float", "width": 110},
		{"label": _("Standard SPM"), "fieldname": "standard_spm", "fieldtype": "Float", "width": 120},
		{
			"label": _("Workstation Efficiency %"),
			"fieldname": "workstation_efficiency_pct",
			"fieldtype": "Percent",
			"width": 170,
		},
	]


def _get_rows(filters: dict, timeout_guard) -> list[dict]:
	stock_entry_filters = _build_filters(filters)
	entry_fields = [
		"name",
		"custom_workstation",
		"fg_completed_qty",
		"custom_rejection_qty",
		"custom_rework_qty",
		"custom_actual_spm",
		"custom_actual_duration_mins",
		"custom_production_time_mins",
		"custom_actual_start_date",
		"custom_actual_end_date",
		"custom_standard_spm",
	]
	aggregates = new_efficiency_aggregates()
	for chunk in iter_stock_entries_in_chunks(stock_entry_filters, entry_fields):
		timeout_guard()
		entry_names = [entry.get("name") for entry in chunk if entry.get("name")]
		parent_quantity_metrics = get_parent_quantity_metrics(entry_names, include_rework=True)
		parent_loss_metrics = get_parent_loss_metrics(entry_names)
		good_qty_map = {
			parent: flt(metrics.get("good_qty") or 0, 3)
			for parent, metrics in parent_quantity_metrics.items()
		}
		rejection_qty_map = {
			parent: flt(metrics.get("rejection_qty") or 0, 3)
			for parent, metrics in parent_quantity_metrics.items()
		}

		for entry in chunk:
			entry_metrics = parent_quantity_metrics.get(entry.get("name") or "", {})
			loss_metrics = parent_loss_metrics.get(entry.get("name") or "", {})
			total_strokes, rejection_qty = get_entry_total_strokes(
				entry,
				good_qty_map=good_qty_map,
				rejection_qty_map=rejection_qty_map,
			)
			good_qty = flt(max(total_strokes - rejection_qty, 0), 3)
			rework_qty = flt(entry.get("custom_rework_qty") or entry_metrics.get("rework_qty") or 0, 3)
			production_time_mins = get_entry_production_minutes(
				entry,
				setup_mins=flt(loss_metrics.get("setup_mins") or 0, 3),
				loss_mins=flt(loss_metrics.get("loss_mins") or 0, 3),
			)
			raw_duration_mins = get_entry_raw_duration_minutes(entry)
			entry["_good_qty"] = good_qty
			entry["_rejection_qty"] = rejection_qty
			entry["_rework_qty"] = rework_qty
			entry["_duration_mins"] = raw_duration_mins
			entry["_production_time_mins"] = production_time_mins
			accumulate_efficiency_aggregate(aggregates, entry, "custom_workstation")

	return build_efficiency_rows(
		aggregates=aggregates,
		group_result_field="workstation",
		efficiency_result_field="workstation_efficiency_pct",
	)


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_workstation", "custom_shift", "custom_operator"),
	)
