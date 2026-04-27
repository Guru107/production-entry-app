from __future__ import annotations

import frappe


def get_bom_alternative_allowed_items(bom_no: str) -> set[str]:
	rows = frappe.get_all(
		"BOM Item",
		filters={"parent": bom_no, "allow_alternative_item": 1},
		pluck="item_code",
	)
	return {item_code for item_code in rows if item_code}
