from __future__ import annotations

from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	PPM_MULTIPLIER,
	apply_system_precision,
	build_rate_overall_row,
	get_quality_ppm_rows,
)


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict], None, dict | None]:
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
	chart = _get_chart(rows)
	if rows:
		rows = [
			*rows,
			build_rate_overall_row(
				rows,
				"date",
				("entries", "total_qty", "rework_qty"),
				rate_field="ppm",
				numerator_field="rework_qty",
				scale=PPM_MULTIPLIER,
			),
		]
	return columns, rows, None, chart


def _get_columns() -> list[dict]:
	return apply_system_precision(
		[
			{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 120},
			{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 90},
			{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 120},
			{"label": _("Rework Qty"), "fieldname": "rework_qty", "fieldtype": "Float", "width": 130},
			{"label": _("PPM"), "fieldname": "ppm", "fieldtype": "Float", "width": 120},
		]
	)


def _get_rows(filters: dict) -> list[dict]:
	return get_quality_ppm_rows(filters, is_rework=True, quantity_field="rework_qty")


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
