from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	build_stock_entry_filters,
	format_numeric_summary,
	get_parent_quantity_metrics,
	iter_stock_entries_in_chunks,
)


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
	return columns, rows


def _get_columns() -> list[dict]:
	return apply_system_precision(
		[
			{"label": _("Operator"), "fieldname": "operator", "fieldtype": "Data", "width": 180},
			{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 90},
			{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 120},
			{"label": _("Rework Qty"), "fieldname": "rework_qty", "fieldtype": "Float", "width": 130},
			{
				"label": _("Rework Rate %"),
				"fieldname": "rework_rate_pct",
				"fieldtype": "Percent",
				"width": 150,
			},
			{"label": _("Top 3 Reasons"), "fieldname": "top_3_reasons", "fieldtype": "Data", "width": 260},
			{"label": _("Avg Actual SPM"), "fieldname": "avg_actual_spm", "fieldtype": "Float", "width": 130},
		]
	)


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_pea_workstation", "custom_pea_shift", "custom_pea_operator", "bom_no"),
	)


def _empty_agg() -> dict:
	return {
		"entries": 0,
		"total_qty": 0.0,
		"rework_qty": 0.0,
		"actual_spm_sum": 0.0,
		"actual_spm_count": 0,
		"reason_totals": {},
	}


def _get_rows(filters: dict) -> list[dict]:
	agg_by_operator: dict[str, dict] = {}
	has_entries = False
	for entries in iter_stock_entries_in_chunks(
		_build_filters(filters),
		[
			"name",
			"custom_pea_operator",
			"fg_completed_qty",
			"custom_pea_rejection_qty",
			"custom_pea_rework_qty",
			"custom_pea_actual_spm",
		],
	):
		has_entries = True
		entry_names = [entry.get("name") for entry in entries if entry.get("name")]
		if not entry_names:
			continue
		parent_quantity_metrics = get_parent_quantity_metrics(entry_names, include_rework=True)
		breakup_rows = frappe.get_all(
			"Rejection Breakup",
			filters={"parenttype": "Stock Entry", "parent": ["in", entry_names], "is_rework": 1},
			fields=["parent", "rejection_reason", "qty"],
		)
		for entry in entries:
			entry_name = entry.get("name")
			entry_metrics = parent_quantity_metrics.get(entry_name or "", {})
			operator = entry.get("custom_pea_operator") or "Unassigned"
			total_qty = flt(entry.get("fg_completed_qty") or 0)
			if total_qty <= 0 and entry_name:
				total_qty = flt(entry_metrics.get("good_qty") or 0) + flt(
					entry_metrics.get("total_rejected_qty") or 0
				)
			rework_qty = flt(entry.get("custom_pea_rework_qty") or entry_metrics.get("rework_qty") or 0)
			agg = agg_by_operator.setdefault(operator, _empty_agg())
			agg["entries"] += 1
			agg["total_qty"] += total_qty
			agg["rework_qty"] += rework_qty
			actual_spm = flt(entry.get("custom_pea_actual_spm") or 0)
			if actual_spm > 0:
				agg["actual_spm_sum"] += actual_spm
				agg["actual_spm_count"] += 1

		operator_by_entry = {
			entry.get("name"): (entry.get("custom_pea_operator") or "Unassigned")
			for entry in entries
			if entry.get("name")
		}
		for row in breakup_rows:
			parent = row.get("parent")
			reason = row.get("rejection_reason")
			qty = flt(row.get("qty") or 0)
			if not parent or not reason or qty <= 0:
				continue
			operator = operator_by_entry.get(parent, "Unassigned")
			reason_totals = agg_by_operator.setdefault(operator, _empty_agg())["reason_totals"]
			reason_totals[reason] = flt(reason_totals.get(reason) or 0) + qty

	if not has_entries:
		return []

	rows = []
	for operator in sorted(agg_by_operator.keys()):
		agg = agg_by_operator[operator]
		total_qty = flt(agg["total_qty"])
		rework_qty = flt(agg["rework_qty"])
		rework_rate_pct = flt((rework_qty / total_qty) * 100) if total_qty > 0 else 0
		avg_actual_spm = (
			flt(agg["actual_spm_sum"] / agg["actual_spm_count"]) if agg["actual_spm_count"] > 0 else 0
		)
		reason_totals = agg.get("reason_totals") or {}
		top_reasons = sorted(reason_totals.items(), key=lambda item: (-flt(item[1]), item[0]))[:3]
		top_3_reasons = ", ".join(f"{reason} ({format_numeric_summary(qty)})" for reason, qty in top_reasons)
		rows.append(
			{
				"operator": operator,
				"entries": int(agg["entries"]),
				"total_qty": total_qty,
				"rework_qty": rework_qty,
				"rework_rate_pct": rework_rate_pct,
				"top_3_reasons": top_3_reasons,
				"avg_actual_spm": avg_actual_spm,
			}
		)

	return rows
