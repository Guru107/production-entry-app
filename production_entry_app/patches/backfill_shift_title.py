from __future__ import annotations

import frappe

from production_entry_app.production_entry_app.doctype.shift.shift import _build_shift_title


def execute() -> None:
	if not frappe.db.has_column("Shift", "shift_title"):
		return

	rows = frappe.get_all(
		"Shift",
		fields=[
			"name",
			"shift_date",
			"planned_start_time",
			"shift_end_date",
			"planned_end_time",
			"shift_title",
		],
		limit_page_length=0,
	)
	for row in rows:
		title = _build_shift_title(
			row.get("shift_date"),
			row.get("planned_start_time"),
			row.get("shift_end_date"),
			row.get("planned_end_time"),
		)
		if row.get("shift_title") != title:
			frappe.db.set_value("Shift", row.name, "shift_title", title, update_modified=False)
