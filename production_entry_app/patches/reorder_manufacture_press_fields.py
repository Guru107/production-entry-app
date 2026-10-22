"""Move press/die tool Custom Fields after Operator (idx was stuck after joint-only layout)."""

from __future__ import annotations

import frappe

_MOVES_AFTER_OPERATOR: tuple[tuple[str, str], ...] = (
	("custom_pea_total_strokes", "custom_pea_operator"),
	("custom_pea_die_tool_item", "custom_pea_total_strokes"),
	("custom_pea_unplanned_losses_section", "custom_pea_die_tool_item"),
)


def execute() -> None:
	meta = frappe.get_meta("Stock Entry", cached=False)
	fieldnames = [df.fieldname for df in meta.fields]

	for fieldname, insert_after in _MOVES_AFTER_OPERATOR:
		if fieldname not in fieldnames or insert_after not in fieldnames:
			continue
		fieldnames.remove(fieldname)
		fieldnames.insert(fieldnames.index(insert_after) + 1, fieldname)

	for index, fieldname in enumerate(fieldnames, start=1):
		custom_field_name = frappe.db.get_value(
			"Custom Field", {"dt": "Stock Entry", "fieldname": fieldname}
		)
		if not custom_field_name:
			continue
		frappe.db.set_value(
			"Custom Field",
			custom_field_name,
			{"idx": index, "insert_after": fieldnames[index - 2] if index > 1 else None},
			update_modified=False,
		)

	frappe.clear_cache(doctype="Stock Entry")

