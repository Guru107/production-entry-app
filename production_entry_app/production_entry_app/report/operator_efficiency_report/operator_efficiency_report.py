from __future__ import annotations

from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	accumulate_efficiency_aggregate,
	apply_system_precision,
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
		timeout_guard=new_interactive_report_timeout_guard(_("Operator Efficiency Report")),
	)
	return columns, rows


def _get_columns() -> list[dict]:
	return apply_system_precision([
		{
			"label": _("Operator"),
			"fieldname": "operator",
			"fieldtype": "Link",
			"options": "Operator",
			"width": 160,
		},
		{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 90},
		{"label": _("Good Qty"), "fieldname": "good_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Rejection Qty"), "fieldname": "rejection_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Rework Qty"), "fieldname": "rework_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Total Units"), "fieldname": "total_units", "fieldtype": "Float", "width": 120},
		{"label": _("Actual SPM"), "fieldname": "actual_spm", "fieldtype": "Float", "width": 110},
		{"label": _("Standard SPM"), "fieldname": "standard_spm", "fieldtype": "Float", "width": 120},
		{
			"label": _("Operator Efficiency %"),
			"fieldname": "operator_efficiency_pct",
			"fieldtype": "Percent",
			"width": 160,
		},
	])


def _get_rows(filters: dict, timeout_guard) -> list[dict]:
	aggregates = new_efficiency_aggregates()
	for entries in iter_stock_entries_in_chunks(
		_build_filters(filters),
		[
			"name",
			"custom_operator",
			"fg_completed_qty",
			"custom_rejection_qty",
			"custom_rework_qty",
			"custom_actual_spm",
			"custom_actual_duration_mins",
			"custom_production_time_mins",
			"custom_actual_start_date",
			"custom_actual_end_date",
			"custom_standard_spm",
		],
	):
		timeout_guard()
		entry_names = [entry.get("name") for entry in entries if entry.get("name")]
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
			entry_metrics = parent_quantity_metrics.get(entry.get("name") or "", {})
			loss_metrics = parent_loss_metrics.get(entry.get("name") or "", {})
			total_strokes, rejection_qty = get_entry_total_strokes(
				entry,
				good_qty_map=good_qty_map,
				rejection_qty_map=rejection_qty_map,
				total_rejected_qty_map=total_rejected_qty_map,
			)
			good_qty = flt(max(total_strokes - rejection_qty, 0))
			rework_qty = flt(entry.get("custom_rework_qty") or entry_metrics.get("rework_qty") or 0)
			production_time_mins = get_entry_production_minutes(
				entry,
				setup_mins=flt(loss_metrics.get("setup_mins") or 0),
				loss_mins=flt(loss_metrics.get("loss_mins") or 0),
			)
			raw_duration_mins = get_entry_raw_duration_minutes(entry)
			entry["_good_qty"] = good_qty
			entry["_rejection_qty"] = rejection_qty
			entry["_rework_qty"] = rework_qty
			entry["_duration_mins"] = raw_duration_mins
			entry["_production_time_mins"] = production_time_mins
			accumulate_efficiency_aggregate(aggregates, entry, "custom_operator")

	return build_efficiency_rows(
		aggregates=aggregates,
		group_result_field="operator",
		efficiency_result_field="operator_efficiency_pct",
	)


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_operator", "custom_shift", "custom_workstation"),
	)
