from __future__ import annotations

import re

from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	build_stock_entry_filters,
	get_parent_breakup_reason_rows,
	iter_stock_entries_in_chunks,
)

_DEFAULT_TOP_N = 10


def execute(filters: dict | None = None):
	filters = filters or {}
	top_n = _normalize_top_n(filters.get("top_n_reasons"))
	rows, reason_order = _get_rows(filters, top_n)
	columns = _get_columns(reason_order)
	return columns, rows


def _normalize_top_n(value) -> int:
	try:
		top_n = int(value) if value is not None else _DEFAULT_TOP_N
	except (TypeError, ValueError):
		return _DEFAULT_TOP_N
	return min(max(top_n, 1), 20)


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_pea_workstation", "custom_pea_shift", "custom_pea_operator", "bom_no"),
	)


def _sanitize_reason_fieldname(reason: str) -> str:
	slug = re.sub(r"[^a-z0-9]+", "_", (reason or "").lower()).strip("_")
	if not slug:
		slug = "unknown"
	return f"reason_{slug}"


def _get_columns(reason_order: list[str]) -> list[dict]:
	columns = [
		{
			"label": _("Workstation"),
			"fieldname": "workstation",
			"fieldtype": "Data",
			"width": 220,
		},
		{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 90},
		{
			"label": _("Total Rework Qty"),
			"fieldname": "total_rework_qty",
			"fieldtype": "Float",
			"width": 150,
		},
	]
	for reason in reason_order:
		columns.append(
			{
				"label": _(reason),
				"fieldname": _sanitize_reason_fieldname(reason),
				"fieldtype": "Float",
				"width": 130,
			}
		)
	return apply_system_precision(columns)


def _get_rows(filters: dict, top_n: int) -> tuple[list[dict], list[str]]:
	reason_totals: dict[str, float] = {}
	matrix: dict[str, dict[str, float]] = {}
	entry_sets: dict[str, set[str]] = {}
	has_entries = False
	for entry_rows in iter_stock_entries_in_chunks(
		_build_filters(filters), ["name", "custom_pea_workstation"]
	):
		has_entries = True
		entry_names = [row.get("name") for row in entry_rows if row.get("name")]
		if not entry_names:
			continue
		workstation_by_entry = {
			row.get("name"): (row.get("custom_pea_workstation") or _("Unassigned"))
			for row in entry_rows
			if row.get("name")
		}
		breakup_rows = get_parent_breakup_reason_rows(entry_names, is_rework=True)
		for row in breakup_rows:
			parent = row.get("parent")
			reason = row.get("rejection_reason")
			qty = flt(row.get("qty") or 0)
			if not parent or not reason or qty <= 0:
				continue
			workstation = workstation_by_entry.get(parent, _("Unassigned"))
			reason_totals[reason] = flt(reason_totals.get(reason) or 0) + qty
			matrix.setdefault(workstation, {})
			matrix[workstation][reason] = flt(matrix[workstation].get(reason) or 0) + qty
			entry_sets.setdefault(workstation, set()).add(parent)

	if not has_entries or not reason_totals:
		return [], []

	reason_order = [
		reason
		for reason, _qty in sorted(reason_totals.items(), key=lambda item: (-flt(item[1]), item[0]))[:top_n]
	]
	rows: list[dict] = []
	for workstation in sorted(matrix.keys()):
		reason_map = matrix[workstation]
		row = {
			"workstation": workstation,
			"entries": len(entry_sets.get(workstation, set())),
			"total_rework_qty": flt(sum(reason_map.values())),
		}
		for reason in reason_order:
			row[_sanitize_reason_fieldname(reason)] = flt(reason_map.get(reason) or 0)
		rows.append(row)

	return rows, reason_order
