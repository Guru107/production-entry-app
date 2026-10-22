"""Align Stock Entry field_order (if frozen) and Custom Field insert_after for press/die tool fields."""

from __future__ import annotations

import json

import frappe

_MOVES_AFTER_OPERATOR: tuple[tuple[str, str], ...] = (
	("custom_pea_total_strokes", "custom_pea_operator"),
	("custom_pea_die_tool_item", "custom_pea_total_strokes"),
	("custom_pea_unplanned_losses_section", "custom_pea_die_tool_item"),
)


def execute() -> None:
	_update_field_order_property_setter()
	_sync_custom_field_insert_after()
	frappe.clear_cache(doctype="Stock Entry")


def _move_after(field_order: list[str], fieldname: str, insert_after: str) -> None:
	if fieldname not in field_order or insert_after not in field_order:
		return
	field_order.remove(fieldname)
	field_order.insert(field_order.index(insert_after) + 1, fieldname)


def _update_field_order_property_setter() -> None:
	name = frappe.db.get_value(
		"Property Setter",
		{"doc_type": "Stock Entry", "property": "field_order", "doctype_or_field": "DocType"},
		"name",
	)
	if not name:
		return
	doc = frappe.get_doc("Property Setter", name)
	field_order = json.loads(doc.value or "[]")
	if not field_order:
		return
	for fieldname, insert_after in _MOVES_AFTER_OPERATOR:
		_move_after(field_order, fieldname, insert_after)
	doc.value = json.dumps(field_order)
	doc.save(ignore_permissions=True)


def _sync_custom_field_insert_after() -> None:
	for fieldname, insert_after in _MOVES_AFTER_OPERATOR:
		custom_field_name = f"Stock Entry-{fieldname}"
		if not frappe.db.exists("Custom Field", custom_field_name):
			continue
		frappe.db.set_value(
			"Custom Field",
			custom_field_name,
			"insert_after",
			insert_after,
			update_modified=False,
		)
