from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	aggregate_efficiency_by_field,
	build_efficiency_rows,
	build_stock_entry_filters,
	get_duration_minutes,
	get_entry_qty_maps,
	get_rework_qty_map,
)


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
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


def _get_rows(filters: dict) -> list[dict]:
	entries = frappe.get_all(
		"Stock Entry",
		filters=_build_filters(filters),
		fields=[
			"name",
			"custom_workstation",
			"fg_completed_qty",
			"custom_rejection_qty",
			"custom_rework_qty",
			"custom_actual_spm",
			"custom_actual_duration_mins",
			"custom_actual_start_date",
			"custom_actual_end_date",
			"custom_standard_spm",
		],
	)
	entry_names = [entry.get("name") for entry in entries if entry.get("name")]
	good_qty_map, rejection_qty_map, _ = get_entry_qty_maps(entry_names)
	rework_qty_map = get_rework_qty_map(entry_names)

	for entry in entries:
		good_qty = flt(entry.get("fg_completed_qty") or 0, 3)
		if good_qty <= 0:
			good_qty = good_qty_map.get(entry.get("name"), 0)
		rejection_qty = flt(entry.get("custom_rejection_qty") or 0, 3)
		if rejection_qty <= 0:
			rejection_qty = rejection_qty_map.get(entry.get("name"), 0)
		rework_qty = flt(entry.get("custom_rework_qty") or 0, 3)
		if rework_qty <= 0:
			rework_qty = rework_qty_map.get(entry.get("name"), 0)
		duration_mins = flt(entry.get("custom_actual_duration_mins") or 0, 3)
		if duration_mins <= 0:
			duration_mins = get_duration_minutes(
				entry.get("custom_actual_start_date"), entry.get("custom_actual_end_date")
			)
		entry["_good_qty"] = good_qty
		entry["_rejection_qty"] = rejection_qty
		entry["_rework_qty"] = rework_qty
		entry["_duration_mins"] = duration_mins

	aggregates = aggregate_efficiency_by_field(entries, "custom_workstation")
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
