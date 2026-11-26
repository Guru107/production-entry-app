from __future__ import annotations

from frappe import _

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	get_bar_line_chart,
	get_reason_pareto_rows,
)


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(filters)
	chart = _get_chart(rows)
	return columns, rows, None, chart


def _get_columns() -> list[dict]:
	return apply_system_precision(
		[
			{"label": _("Rank"), "fieldname": "rank", "fieldtype": "Int", "width": 70},
			{
				"label": _("Rejection Reason"),
				"fieldname": "rejection_reason",
				"fieldtype": "Data",
				"width": 220,
			},
			{"label": _("Rejection Qty"), "fieldname": "rejection_qty", "fieldtype": "Float", "width": 130},
			{"label": _("Rejection %"), "fieldname": "rejection_pct", "fieldtype": "Percent", "width": 120},
			{"label": _("Cumulative %"), "fieldname": "cumulative_pct", "fieldtype": "Percent", "width": 120},
			{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 100},
			{"label": _("Shifts"), "fieldname": "shifts", "fieldtype": "Int", "width": 90},
		]
	)


def _get_rows(filters: dict) -> list[dict]:
	return get_reason_pareto_rows(
		filters, is_rework=False, quantity_field="rejection_qty", pct_field="rejection_pct"
	)


def _get_chart(rows: list[dict]) -> dict | None:
	return get_bar_line_chart(
		rows, "rejection_reason", ("rejection_qty", _("Rejection Qty")), ("cumulative_pct", _("Cumulative %"))
	)
