from __future__ import annotations

from frappe import _

from production_entry_app.production_entry_app.report.report_utils import (
	get_reason_matrix_columns,
	get_reason_matrix_report,
)


def execute(filters: dict | None = None):
	return get_reason_matrix_report(
		filters or {},
		is_rework=False,
		total_field="total_rejection_qty",
		total_label=_("Total Rejection Qty"),
	)


def _get_columns(reason_order: list[str]) -> list[dict]:
	return get_reason_matrix_columns(reason_order, "total_rejection_qty", _("Total Rejection Qty"))
