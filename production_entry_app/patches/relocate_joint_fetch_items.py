"""Move joint Fetch Items into the Joint Production block and drop the resources section."""

from __future__ import annotations

import json

import frappe

_REMOVED_FIELDS: tuple[str, ...] = (
	"custom_pea_joint_resources_section",
	"custom_pea_joint_resources_col_break",
)
_FETCH_FIELD = "custom_pea_joint_fetch_items"
_FETCH_INSERT_AFTER = "custom_pea_rh_rejection_qty"


def execute() -> None:
	_update_field_order_property_setter()
	for fieldname in _REMOVED_FIELDS:
		custom_field_name = f"Stock Entry-{fieldname}"
		if frappe.db.exists("Custom Field", custom_field_name):
			frappe.delete_doc("Custom Field", custom_field_name, force=True)
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
	if not field_order:
		return
	for fieldname in _REMOVED_FIELDS:
		if fieldname in field_order:
			field_order.remove(fieldname)
	if _FETCH_FIELD in field_order and _FETCH_INSERT_AFTER in field_order:
		field_order.remove(_FETCH_FIELD)
		field_order.insert(field_order.index(_FETCH_INSERT_AFTER) + 1, _FETCH_FIELD)
	doc.value = json.dumps(field_order)
	doc.save(ignore_permissions=True)
