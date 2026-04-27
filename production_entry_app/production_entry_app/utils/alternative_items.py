from __future__ import annotations

import frappe


def _get_bom_item_rows(bom_no: str) -> list[dict]:
	pending = [bom_no]
	seen: set[str] = set()
	rows: list[dict] = []
	while pending:
		current_bom = pending.pop()
		if not current_bom or current_bom in seen:
			continue
		seen.add(current_bom)
		current_rows = frappe.get_all(
			"BOM Item",
			filters={"parent": current_bom, "parenttype": "BOM"},
			fields=["item_code", "allow_alternative_item", "bom_no"],
		)
		rows.extend(current_rows)
		for row in current_rows:
			child_bom = row.get("bom_no")
			if child_bom and child_bom not in seen:
				pending.append(child_bom)
	return rows


def get_bom_item_codes(bom_no: str) -> set[str]:
	return {row.get("item_code") for row in _get_bom_item_rows(bom_no) if row.get("item_code")}


def get_bom_alternative_allowed_items(bom_no: str) -> set[str]:
	return {
		row.get("item_code")
		for row in _get_bom_item_rows(bom_no)
		if row.get("item_code") and row.get("allow_alternative_item")
	}
