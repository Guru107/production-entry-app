from __future__ import annotations

from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	PERCENT_SCALE,
	apply_system_precision,
	build_overall_row,
	build_stock_entry_filters,
	format_numeric_summary,
	get_entry_production_minutes,
	get_entry_total_strokes,
	get_parent_loss_metrics,
	get_parent_quantity_metrics,
	get_report_rows,
	iter_stock_entries_in_chunks,
	merge_aggregates,
	safe_ratio,
)


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
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
			{"label": _("Actual SPM"), "fieldname": "actual_spm", "fieldtype": "Float", "width": 130},
		]
	)


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=(
			"custom_pea_workstation",
			"custom_pea_shift",
			"custom_pea_operator",
			"custom_pea_operation",
			"bom_no",
		),
	)


def _empty_agg() -> dict:
	return {
		"entries": 0,
		"total_qty": 0.0,
		"rework_qty": 0.0,
		"total_strokes": 0.0,
		"production_mins": 0.0,
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
			"custom_pea_total_strokes",
			"custom_pea_production_time_mins",
			"custom_pea_actual_duration_mins",
			"custom_pea_actual_start_date",
			"custom_pea_actual_end_date",
		],
	):
		has_entries = True
		entry_names = [entry.get("name") for entry in entries if entry.get("name")]
		if not entry_names:
			continue
		parent_quantity_metrics = get_parent_quantity_metrics(entry_names, include_rework=True)
		parent_loss_metrics = get_parent_loss_metrics(entry_names)
		breakup_rows = get_report_rows(
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
			loss_metrics = parent_loss_metrics.get(entry_name or "", {})
			agg["total_strokes"] += get_entry_total_strokes(entry)[0]
			agg["production_mins"] += get_entry_production_minutes(
				entry,
				setup_mins=flt(loss_metrics.get("setup_mins") or 0),
				loss_mins=flt(loss_metrics.get("loss_mins") or 0),
			)

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

	rows = [_build_row(operator, agg_by_operator[operator]) for operator in sorted(agg_by_operator)]
	overall = _build_row("", merge_aggregates(agg_by_operator.values()))
	overall.pop("operator")
	return [*rows, build_overall_row("operator", **overall)]


def _build_row(operator: str, agg: dict) -> dict:
	total_qty = flt(agg["total_qty"])
	rework_qty = flt(agg["rework_qty"])
	reason_totals = agg.get("reason_totals") or {}
	top_reasons = sorted(reason_totals.items(), key=lambda item: (-flt(item[1]), item[0]))[:3]
	return {
		"operator": operator,
		"entries": int(agg["entries"]),
		"total_qty": total_qty,
		"rework_qty": rework_qty,
		"rework_rate_pct": safe_ratio(rework_qty, total_qty, PERCENT_SCALE),
		"top_3_reasons": ", ".join(
			f"{reason} ({format_numeric_summary(qty)})" for reason, qty in top_reasons
		),
		# Effective SPM: total strokes over total production time (ADR 0010).
		"actual_spm": safe_ratio(agg["total_strokes"], agg["production_mins"]),
	}
