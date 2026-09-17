from __future__ import annotations

import frappe


def execute() -> None:
	"""Copy header rework windows onto Rework Operator rows that lack times (#123)."""
	if not (
		frappe.db.has_column("Stock Entry", "custom_pea_rework_actual_start")
		and frappe.db.has_column("Stock Entry", "custom_pea_rework_actual_end")
		and frappe.db.has_column("Rework Operator", "actual_start")
		and frappe.db.has_column("Rework Operator", "actual_end")
	):
		return

	candidates = frappe.get_all(
		"Rework Operator",
		filters={
			"parenttype": "Stock Entry",
			"parentfield": "custom_pea_rework_operators",
			"actual_start": ["is", "not set"],
			"actual_end": ["is", "not set"],
		},
		fields=["name", "parent"],
	)
	if not candidates:
		return

	header_by_parent = {
		row.name: row
		for row in frappe.get_all(
			"Stock Entry",
			filters={"name": ["in", list({candidate.parent for candidate in candidates})]},
			fields=["name", "custom_pea_rework_actual_start", "custom_pea_rework_actual_end"],
		)
	}
	for candidate in candidates:
		header = header_by_parent.get(candidate.parent)
		if not header or not header.custom_pea_rework_actual_start or not header.custom_pea_rework_actual_end:
			continue
		frappe.db.set_value(
			"Rework Operator",
			candidate.name,
			{
				"actual_start": header.custom_pea_rework_actual_start,
				"actual_end": header.custom_pea_rework_actual_end,
			},
			update_modified=False,
		)
