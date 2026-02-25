from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import build_stock_entry_filters


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
	return columns, rows


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
		{"label": _("Rejection Qty"), "fieldname": "rejection_qty", "fieldtype": "Float", "width": 130},
		{"label": _("Rejection %"), "fieldname": "rejection_pct", "fieldtype": "Percent", "width": 120},
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
	entry_rows = frappe.get_all(
		"Stock Entry",
		filters=_build_filters(filters),
		fields=["name", "custom_shift"],
	)
	entry_names = [row.get("name") for row in entry_rows if row.get("name")]
	if not entry_names:
		return []

	shift_by_entry = {row.get("name"): row.get("custom_shift") for row in entry_rows if row.get("name")}
	breakup_rows = frappe.get_all(
		"Rejection Breakup",
		filters={"parenttype": "Stock Entry", "parent": ["in", entry_names]},
		fields=["parent", "rejection_reason", "qty"],
	)
	if not breakup_rows:
		return []

	reason_totals: dict[str, float] = {}
	entry_sets: dict[str, set[str]] = {}
	shift_sets: dict[str, set[str]] = {}
	total_rejection_qty = 0.0

	for row in breakup_rows:
		reason = row.get("rejection_reason")
		qty = flt(row.get("qty") or 0, 3)
		parent = row.get("parent")
		if not reason or qty <= 0 or not parent:
			continue
		total_rejection_qty += qty
		reason_totals[reason] = flt(reason_totals.get(reason) or 0, 3) + qty
		entry_sets.setdefault(reason, set()).add(parent)
		shift_name = shift_by_entry.get(parent)
		if shift_name:
			shift_sets.setdefault(reason, set()).add(shift_name)

	if total_rejection_qty <= 0:
		return []

	sorted_reasons = sorted(reason_totals.items(), key=lambda row: (-flt(row[1], 3), row[0]))
	rows = []
	cumulative = 0.0
	for index, (reason, qty) in enumerate(sorted_reasons, start=1):
		reason_pct = flt((qty / total_rejection_qty) * 100, 2)
		cumulative = flt(cumulative + reason_pct, 2)
		rows.append(
			{
				"rank": index,
				"rejection_reason": reason,
				"rejection_qty": flt(qty, 3),
				"rejection_pct": reason_pct,
				"cumulative_pct": cumulative,
				"entries": len(entry_sets.get(reason, set())),
				"shifts": len(shift_sets.get(reason, set())),
			}
		)

	return rows
