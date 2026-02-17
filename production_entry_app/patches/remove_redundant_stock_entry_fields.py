from __future__ import annotations

import frappe


def execute() -> None:
	redundant_custom_fields = [
		"Stock Entry-custom_planned_actual_dates_section",
	]

	for custom_field_name in redundant_custom_fields:
		if not frappe.db.exists("Custom Field", custom_field_name):
			continue
		frappe.db.delete("Custom Field", {"name": custom_field_name})

	frappe.clear_cache(doctype="Stock Entry")
