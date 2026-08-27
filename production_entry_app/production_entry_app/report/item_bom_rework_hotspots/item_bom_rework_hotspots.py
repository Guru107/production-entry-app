from __future__ import annotations

from frappe import _

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	get_item_bom_quality_hotspot_rows,
	new_interactive_report_timeout_guard,
)


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = _get_columns()
	rows = _get_rows(
		filters,
		timeout_guard=new_interactive_report_timeout_guard(_("Item BOM Rework Hotspots Report")),
	)
	return columns, rows


def _get_columns() -> list[dict]:
	return apply_system_precision(
		[
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
			{"label": _("Rework Qty"), "fieldname": "rework_qty", "fieldtype": "Float", "width": 130},
			{
				"label": _("Rework Rate %"),
				"fieldname": "rework_rate_pct",
				"fieldtype": "Percent",
				"width": 150,
			},
			{
				"label": _("Dominant Reason"),
				"fieldname": "dominant_reason",
				"fieldtype": "Data",
				"width": 240,
			},
		]
	)


def _get_rows(filters: dict, timeout_guard) -> list[dict]:
	return get_item_bom_quality_hotspot_rows(
		filters,
		is_rework=True,
		quantity_field="rework_qty",
		rate_field="rework_rate_pct",
		timeout_guard=timeout_guard,
	)
