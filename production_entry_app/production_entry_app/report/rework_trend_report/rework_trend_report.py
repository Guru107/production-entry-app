from __future__ import annotations

from frappe import _

from production_entry_app.production_entry_app.report.report_utils import (
	PERCENT_SCALE,
	apply_system_precision,
	build_rate_overall_row,
	get_bar_line_chart,
	get_quality_trend_rows,
)


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict], None, dict | None]:
	filters = filters or {}
	columns = _get_columns()
	rows = get_quality_trend_rows(
		filters, is_rework=True, quantity_field="rework_qty", rate_field="rework_rate_pct"
	)
	chart = get_bar_line_chart(
		rows, "period", ("rework_qty", _("Rework Qty")), ("rework_rate_pct", _("Rework Rate %"))
	)
	if rows:
		rows = [
			*rows,
			build_rate_overall_row(
				rows,
				"period",
				("entries", "total_qty", "rework_qty", "non_rework_rejection_qty"),
				rate_field="rework_rate_pct",
				numerator_field="rework_qty",
				scale=PERCENT_SCALE,
			),
		]
	return columns, rows, None, chart


def _get_columns() -> list[dict]:
	return apply_system_precision(
		[
			{"label": _("Period"), "fieldname": "period", "fieldtype": "Data", "width": 150},
			{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 90},
			{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 120},
			{"label": _("Rework Qty"), "fieldname": "rework_qty", "fieldtype": "Float", "width": 130},
			{
				"label": _("Non-Rework Rejection Qty"),
				"fieldname": "non_rework_rejection_qty",
				"fieldtype": "Float",
				"width": 180,
			},
			{
				"label": _("Rework Rate %"),
				"fieldname": "rework_rate_pct",
				"fieldtype": "Percent",
				"width": 140,
			},
		]
	)
