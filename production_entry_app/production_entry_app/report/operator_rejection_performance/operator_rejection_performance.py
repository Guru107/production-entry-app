from __future__ import annotations

from frappe import _

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	get_operator_quality_rows,
)


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
	filters = filters or {}
	columns = _get_columns()
	rows = get_operator_quality_rows(
		filters, is_rework=False, quantity_field="rejection_qty", rate_field="rejection_rate_pct"
	)
	return columns, rows


def _get_columns() -> list[dict]:
	return apply_system_precision(
		[
			{"label": _("Operator"), "fieldname": "operator", "fieldtype": "Data", "width": 180},
			{"label": _("Entries"), "fieldname": "entries", "fieldtype": "Int", "width": 90},
			{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 120},
			{"label": _("Rejection Qty"), "fieldname": "rejection_qty", "fieldtype": "Float", "width": 130},
			{
				"label": _("Rejection Rate %"),
				"fieldname": "rejection_rate_pct",
				"fieldtype": "Percent",
				"width": 150,
			},
			{"label": _("Top 3 Reasons"), "fieldname": "top_3_reasons", "fieldtype": "Data", "width": 260},
			{"label": _("Actual SPM"), "fieldname": "actual_spm", "fieldtype": "Float", "width": 130},
		]
	)
