"""Place joint Fetch Items after Joint Production Lines (N-line visibility)."""

from __future__ import annotations

import json

import frappe

_FETCH_FIELD = "custom_pea_joint_fetch_items"
_FETCH_INSERT_AFTER = "custom_pea_joint_production_lines"


def execute() -> None:
	_update_field_order_property_setter()
	if frappe.db.exists("Custom Field", f"Stock Entry-{_FETCH_FIELD}"):
		frappe.db.set_value(
			"Custom Field",
			f"Stock Entry-{_FETCH_FIELD}",
			"insert_after",
			_FETCH_INSERT_AFTER,
			update_modified=False,
		)
	frappe.clear_cache(doctype="Stock Entry")


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
	if not field_order or _FETCH_FIELD not in field_order or _FETCH_INSERT_AFTER not in field_order:
		return
	field_order.remove(_FETCH_FIELD)
	field_order.insert(field_order.index(_FETCH_INSERT_AFTER) + 1, _FETCH_FIELD)
	doc.value = json.dumps(field_order)
	doc.save(ignore_permissions=True)
