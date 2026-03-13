from __future__ import annotations

from frappe import _
from frappe.utils import flt, getdate

from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	get_parent_quantity_metrics,
	iter_stock_entries_in_chunks,
)

PPM_MULTIPLIER: int = 1_000_000


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
	chart = _get_chart(rows)
	return columns, rows, None, chart


def _get_columns() -> list[dict]:
	return [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 120},
		{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 90},
		{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Rework Qty"), "fieldname": "rework_qty", "fieldtype": "Float", "width": 130},
		{"label": _("PPM"), "fieldname": "ppm", "fieldtype": "Float", "width": 120},
	]


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_workstation", "custom_shift", "custom_operator", "bom_no"),
	)


def _get_rows(filters: dict) -> list[dict]:
	aggregates: dict = {}
	has_entries = False
	for entries in iter_stock_entries_in_chunks(
		_build_filters(filters),
		["name", "posting_date", "fg_completed_qty", "custom_rework_qty", "custom_rejection_qty"],
		order_by="posting_date asc, name asc",
	):
		has_entries = True
		entry_names = [entry.get("name") for entry in entries if entry.get("name")]
		parent_quantity_metrics = get_parent_quantity_metrics(entry_names, include_rework=True)
		for entry in entries:
			posting_date = getdate(entry.get("posting_date"))
			if not posting_date:
				continue
			entry_name = entry.get("name")
			entry_metrics = parent_quantity_metrics.get(entry_name or "", {})
			rework_qty = flt(entry.get("custom_rework_qty") or entry_metrics.get("rework_qty") or 0)
			total_qty = flt(entry.get("fg_completed_qty") or 0)
			if total_qty <= 0 and entry_name:
				total_qty = flt(entry_metrics.get("good_qty") or 0) + flt(
					entry_metrics.get("total_rejected_qty") or 0
				)

			aggregate = aggregates.setdefault(
				posting_date,
				{"date": posting_date.isoformat(), "entries": 0, "total_qty": 0.0, "rework_qty": 0.0},
			)
			aggregate["entries"] += 1
			aggregate["total_qty"] += total_qty
			aggregate["rework_qty"] += rework_qty

	if not has_entries:
		return []

	rows = []
	for key_date in sorted(aggregates):
		aggregate = aggregates[key_date]
		total_qty = flt(aggregate["total_qty"])
		rework_qty = flt(aggregate["rework_qty"])
		ppm = flt((rework_qty / total_qty) * PPM_MULTIPLIER) if total_qty > 0 else 0
		rows.append(
			{
				"date": aggregate["date"],
				"entries": aggregate["entries"],
				"total_qty": total_qty,
				"rework_qty": rework_qty,
				"ppm": ppm,
			}
		)

	return rows


def _get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	return {
		"data": {
			"labels": [row["date"] for row in rows],
			"datasets": [
				{
					"name": _("PPM"),
					"values": [flt(row["ppm"]) for row in rows],
				},
			],
		},
		"type": "bar",
		"height": 280,
		"axisOptions": {"xAxisMode": "tick", "xIsSeries": 1},
	}
