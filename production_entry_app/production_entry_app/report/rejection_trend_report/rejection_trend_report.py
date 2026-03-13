from __future__ import annotations

import datetime

from frappe import _
from frappe.utils import flt, getdate

from production_entry_app.production_entry_app.report.report_utils import (
	build_stock_entry_filters,
	get_parent_quantity_metrics,
	iter_stock_entries_in_chunks,
)

_TIME_GRAINS: frozenset[str] = frozenset({"Daily", "Weekly", "Monthly"})


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
	chart = _get_chart(rows)
	return columns, rows, None, chart


def _get_columns() -> list[dict]:
	return [
		{"label": _("Period"), "fieldname": "period", "fieldtype": "Data", "width": 150},
		{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 90},
		{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Rejection Qty"), "fieldname": "rejection_qty", "fieldtype": "Float", "width": 130},
		{"label": _("OK Qty"), "fieldname": "ok_qty", "fieldtype": "Float", "width": 110},
		{
			"label": _("Rejection Rate %"),
			"fieldname": "rejection_rate_pct",
			"fieldtype": "Percent",
			"width": 150,
		},
	]


def _build_filters(filters: dict) -> dict:
	return build_stock_entry_filters(
		filters,
		filter_keys=("custom_workstation", "custom_shift", "custom_operator", "bom_no"),
	)


def _normalize_time_grain(value: str | None) -> str:
	time_grain = (value or "Daily").title()
	if time_grain not in _TIME_GRAINS:
		return "Daily"
	return time_grain


def _period_key(posting_date: datetime.date, time_grain: str) -> tuple[datetime.date, str]:
	if time_grain == "Weekly":
		period_start = posting_date - datetime.timedelta(days=posting_date.weekday())
		period_end = period_start + datetime.timedelta(days=6)
		return period_start, f"{period_start.isoformat()} to {period_end.isoformat()}"
	if time_grain == "Monthly":
		period_start = posting_date.replace(day=1)
		return period_start, period_start.strftime("%Y-%m")
	return posting_date, posting_date.isoformat()


def _get_rows(filters: dict) -> list[dict]:
	time_grain = _normalize_time_grain(filters.get("time_grain"))

	aggregates: dict[datetime.date, dict] = {}
	has_entries = False
	for entries in iter_stock_entries_in_chunks(
		_build_filters(filters),
		["name", "posting_date", "fg_completed_qty", "custom_rejection_qty"],
		order_by="posting_date asc, name asc",
	):
		has_entries = True
		entry_names = [entry.get("name") for entry in entries if entry.get("name")]
		parent_quantity_metrics = get_parent_quantity_metrics(entry_names)
		for entry in entries:
			posting_date = getdate(entry.get("posting_date"))
			if not posting_date:
				continue
			entry_name = entry.get("name")
			entry_metrics = parent_quantity_metrics.get(entry_name or "", {})
			rejection_qty = flt(entry_metrics.get("rejection_qty") or 0)
			total_qty = flt(entry.get("fg_completed_qty") or 0)
			if total_qty <= 0 and entry_name:
				total_qty = flt(entry_metrics.get("good_qty") or 0) + flt(entry_metrics.get("total_rejected_qty") or 0)
			key_date, period_label = _period_key(posting_date, time_grain)
			aggregate = aggregates.setdefault(
				key_date,
				{"period": period_label, "entries": 0, "total_qty": 0.0, "rejection_qty": 0.0},
			)
			aggregate["entries"] += 1
			aggregate["total_qty"] += total_qty
			aggregate["rejection_qty"] += rejection_qty

	if not has_entries:
		return []

	rows = []
	for key_date in sorted(aggregates):
		aggregate = aggregates[key_date]
		total_qty = flt(aggregate["total_qty"])
		rejection_qty = flt(aggregate["rejection_qty"])
		ok_qty = flt(total_qty - rejection_qty)
		rejection_rate_pct = flt((rejection_qty / total_qty) * 100) if total_qty > 0 else 0
		rows.append(
			{
				"period": aggregate["period"],
				"entries": aggregate["entries"],
				"total_qty": total_qty,
				"rejection_qty": rejection_qty,
				"ok_qty": ok_qty,
				"rejection_rate_pct": rejection_rate_pct,
			}
		)

	return rows


def _get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	return {
		"data": {
			"labels": [row["period"] for row in rows],
			"datasets": [
				{
					"name": _("Rejection Qty"),
					"values": [flt(row["rejection_qty"]) for row in rows],
					"chartType": "bar",
				},
				{
					"name": _("Rejection Rate %"),
					"values": [flt(row["rejection_rate_pct"]) for row in rows],
					"chartType": "line",
				},
			],
		},
		"type": "axis-mixed",
		"height": 280,
		"axisOptions": {"xAxisMode": "tick", "xIsSeries": 1},
	}
