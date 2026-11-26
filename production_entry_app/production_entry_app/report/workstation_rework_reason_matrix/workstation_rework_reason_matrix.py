from __future__ import annotations

from frappe import _

from production_entry_app.production_entry_app.report.report_utils import (
	get_reason_matrix_columns,
	get_reason_matrix_report,
)


def execute(filters: dict | None = None):
	return get_reason_matrix_report(
		filters or {}, is_rework=True, total_field="total_rework_qty", get_columns=_get_columns
	)


def _get_columns(reason_order: list[str]) -> list[dict]:
	return get_reason_matrix_columns(reason_order, "total_rework_qty", _("Total Rework Qty"))
