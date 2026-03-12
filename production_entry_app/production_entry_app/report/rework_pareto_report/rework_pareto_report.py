from __future__ import annotations

from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	get_parent_breakup_reason_rows,
	iter_stock_entries_in_chunks,
)


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
	chart = _get_chart(rows)
	return columns, rows, None, chart


def _get_columns() -> list[dict]:
	return [
		{"label": _("Rank"), "fieldname": "rank", "fieldtype": "Int", "width": 70},
		{
			"label": _("Rejection Reason"),
			"fieldname": "rejection_reason",
			"fieldtype": "Link",
			"options": "Rejection Reason",
			"width": 220,
		},
		{"label": _("Rework Qty"), "fieldname": "rework_qty", "fieldtype": "Float", "width": 130},
		{"label": _("Rework %"), "fieldname": "rework_pct", "fieldtype": "Percent", "width": 120},
		{"label": _("Cumulative %"), "fieldname": "cumulative_pct", "fieldtype": "Percent", "width": 120},
		{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 100},
		{"label": _("Shifts"), "fieldname": "shifts", "fieldtype": "Int", "width": 90},
	]


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_workstation", "custom_shift", "custom_operator", "bom_no"),
	)


def _get_rows(filters: dict) -> list[dict]:
	has_entries = False
	reason_totals: dict[str, float] = {}
	entry_sets: dict[str, set[str]] = {}
	shift_sets: dict[str, set[str]] = {}
	total_rework_qty = 0.0

	for entry_rows in iter_stock_entries_in_chunks(_build_filters(filters), ["name", "custom_shift"]):
		has_entries = True
		entry_names = [row.get("name") for row in entry_rows if row.get("name")]
		if not entry_names:
			continue
		shift_by_entry = {row.get("name"): row.get("custom_shift") for row in entry_rows if row.get("name")}
		breakup_rows = get_parent_breakup_reason_rows(entry_names, is_rework=True)
		for row in breakup_rows:
			reason = row.get("rejection_reason")
			qty = flt(row.get("qty") or 0)
			parent = row.get("parent")
			if not reason or qty <= 0 or not parent:
				continue
			total_rework_qty += qty
			reason_totals[reason] = flt(reason_totals.get(reason) or 0) + qty
			entry_sets.setdefault(reason, set()).add(parent)
			shift_name = shift_by_entry.get(parent)
			if shift_name:
				shift_sets.setdefault(reason, set()).add(shift_name)

	if not has_entries or total_rework_qty <= 0:
		return []

	sorted_reasons = sorted(reason_totals.items(), key=lambda row: (-flt(row[1]), row[0]))
	rows = []
	cumulative = 0.0
	for index, (reason, qty) in enumerate(sorted_reasons, start=1):
		rework_pct = flt((qty / total_rework_qty) * 100)
		cumulative = flt(cumulative + rework_pct)
		if index == len(sorted_reasons):
			cumulative = 100.0
		rows.append(
			{
				"rank": index,
				"rejection_reason": reason,
				"rework_qty": flt(qty),
				"rework_pct": rework_pct,
				"cumulative_pct": cumulative,
				"entries": len(entry_sets.get(reason, set())),
				"shifts": len(shift_sets.get(reason, set())),
			}
		)

	return rows


def _get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	return {
		"data": {
			"labels": [row["rejection_reason"] for row in rows],
			"datasets": [
				{
					"name": _("Rework Qty"),
					"values": [flt(row["rework_qty"]) for row in rows],
					"chartType": "bar",
				},
				{
					"name": _("Cumulative %"),
					"values": [flt(row["cumulative_pct"]) for row in rows],
					"chartType": "line",
				},
			],
		},
		"type": "axis-mixed",
		"height": 280,
		"axisOptions": {"xAxisMode": "tick", "xIsSeries": 1},
	}
