from __future__ import annotations

from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	get_finished_item_map,
	get_parent_breakup_reason_rows,
	get_parent_quantity_metrics,
	iter_stock_entries_in_chunks,
	new_interactive_report_timeout_guard,
)


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(
		filters,
		timeout_guard=new_interactive_report_timeout_guard(_("Item BOM Rejection Hotspots Report")),
	)
	return columns, rows


def _get_columns() -> list[dict]:
	return [
		{
			"label": _("Item Code"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 180,
		},
		{"label": _("BOM"), "fieldname": "bom_no", "fieldtype": "Link", "options": "BOM", "width": 220},
		{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 90},
		{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Rejection Qty"), "fieldname": "rejection_qty", "fieldtype": "Float", "width": 130},
		{
			"label": _("Rejection Rate %"),
			"fieldname": "rejection_rate_pct",
			"fieldtype": "Percent",
			"width": 150,
		},
		{"label": _("Dominant Reason"), "fieldname": "dominant_reason", "fieldtype": "Data", "width": 240},
	]


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_workstation", "custom_shift", "custom_operator", "bom_no"),
	)


def _group_key(item_code: str | None, bom_no: str | None) -> tuple[str, str]:
	return (item_code or "Unknown", bom_no or "")


def _get_rows(filters: dict, timeout_guard) -> list[dict]:
	agg: dict[tuple[str, str], dict] = {}
	has_entries = False
	for entries in iter_stock_entries_in_chunks(
		_build_filters(filters),
		["name", "fg_completed_qty", "custom_rejection_qty", "bom_no"],
	):
		timeout_guard()
		has_entries = True
		entry_names = [entry.get("name") for entry in entries if entry.get("name")]
		if not entry_names:
			continue
		entry_by_name = {entry.get("name"): entry for entry in entries if entry.get("name")}
		parent_metrics = get_parent_quantity_metrics(entry_names)
		item_by_entry = get_finished_item_map(entry_names)
		breakup_rows = get_parent_breakup_reason_rows(entry_names)

		for entry in entries:
			entry_name = entry.get("name")
			if not entry_name:
				continue
			item_code = item_by_entry.get(entry_name)
			group = _group_key(item_code, entry.get("bom_no"))
			rejection_qty = flt(entry.get("custom_rejection_qty") or 0, 3)
			if rejection_qty <= 0:
				rejection_qty = flt(parent_metrics.get(entry_name, {}).get("rejection_qty") or 0, 3)
			total_qty = flt(entry.get("fg_completed_qty") or 0, 3)
			if total_qty <= 0:
				total_qty = flt(parent_metrics.get(entry_name, {}).get("good_qty") or 0, 3) + rejection_qty
			row = agg.setdefault(
				group,
				{"entries": set(), "total_qty": 0.0, "rejection_qty": 0.0, "reason_totals": {}},
			)
			row["entries"].add(entry_name)
			row["total_qty"] += total_qty
			row["rejection_qty"] += rejection_qty

		for breakup in breakup_rows:
			parent = breakup.get("parent")
			reason = breakup.get("rejection_reason")
			qty = flt(breakup.get("qty") or 0, 3)
			if not parent or not reason or qty <= 0:
				continue
			entry = entry_by_name.get(parent)
			if not entry:
				continue
			group = _group_key(item_by_entry.get(parent), entry.get("bom_no"))
			reasons = agg.setdefault(
				group,
				{"entries": set(), "total_qty": 0.0, "rejection_qty": 0.0, "reason_totals": {}},
			)["reason_totals"]
			reasons[reason] = flt(reasons.get(reason) or 0, 3) + qty

	if not has_entries:
		return []

	rows: list[dict] = []
	for (item_code, bom_no), values in agg.items():
		total_qty = flt(values["total_qty"], 3)
		rejection_qty = flt(values["rejection_qty"], 3)
		rejection_rate_pct = flt((rejection_qty / total_qty) * 100, 2) if total_qty > 0 else 0
		reasons = values.get("reason_totals") or {}
		dominant_reason = ""
		if reasons:
			reason, qty = sorted(reasons.items(), key=lambda item: (-flt(item[1], 3), item[0]))[0]
			dominant_reason = f"{reason} ({flt(qty, 3)})"
		rows.append(
			{
				"item_code": item_code,
				"bom_no": bom_no,
				"entries": len(values["entries"]),
				"total_qty": total_qty,
				"rejection_qty": rejection_qty,
				"rejection_rate_pct": rejection_rate_pct,
				"dominant_reason": dominant_reason,
			}
		)

	rows.sort(key=lambda row: (-flt(row["rejection_qty"], 3), row["item_code"], row["bom_no"] or ""))
	return rows
