from __future__ import annotations

from typing import Any

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


def get_bom_secondary_item_codes(bom_no: str) -> set[str]:
	if not frappe.db.exists("DocType", "BOM Secondary Item"):
		return set()
	return set(
		frappe.get_all(
			"BOM Secondary Item",
			filters={"parent": bom_no, "parenttype": "BOM"},
			pluck="item_code",
		)
	)


def should_skip_direct_manufacture_alternative_row(
	row: Any, bom_secondary_item_codes: set[str] | None = None
) -> bool:
	return bool(
		row.get("is_finished_item")
		or row.get("is_scrap_item")
		or row.get("is_legacy_scrap_item")
		or row.get("custom_pea_is_rejection_item")
		or row.get("item_code") in (bom_secondary_item_codes or set())
	)


def apply_direct_manufacture_alternative_flags(
	doc: Any, bom_secondary_item_codes: set[str] | None = None
) -> None:
	if doc.get("purpose") != "Manufacture" or not doc.get("from_bom") or doc.get("work_order"):
		return
	if not doc.get("bom_no"):
		return

	allowed_items = get_bom_alternative_allowed_items(doc.get("bom_no"))
	if not allowed_items:
		return
	if bom_secondary_item_codes is None:
		bom_secondary_item_codes = get_bom_secondary_item_codes(doc.get("bom_no"))

	for row in doc.get("items") or []:
		if should_skip_direct_manufacture_alternative_row(row, bom_secondary_item_codes):
			continue
		item_code = row.get("original_item") or row.get("item_code")
		if item_code in allowed_items:
			row.allow_alternative_item = 1
