"""Declare the joint form layout: Fetch Items at the section end, rejection section after it.

Replaces the client-side repositioning (_position_joint_fetch_items /
_position_rejection_breakup_section): the joint Fetch Items button sits after
custom_pea_rh_rejection_qty (hidden LH/RH fields collapse in N-line mode, so it
renders right after the lines table there), and the rejection breakup section
slots between the joint section and Workstation & Operator.
"""

from __future__ import annotations

import json

import frappe

_FETCH_FIELD = "custom_pea_joint_fetch_items"
_ANCHOR_FIELD = "custom_pea_rh_rejection_qty"
# Section breaks travel with their fields: field_order is a flat list, so each
# block must move as a unit or the children render in the previous section.
_REJECTION_BLOCK: tuple[str, ...] = (
	"custom_pea_rejection_section",
	"custom_pea_rejection_breakup",
	"custom_pea_is_late_entry",
)
_WORKSTATION_BLOCK: tuple[str, ...] = (
	"custom_pea_workstation_operator_section",
	"custom_pea_workstation",
	"custom_pea_standard_spm",
	"custom_pea_workstation_operator_col_break",
	"custom_pea_operator",
	"custom_pea_total_strokes",
	"custom_pea_die_tool_item",
)


def execute() -> None:
	_update_field_order_property_setter()
	for fieldname, insert_after in (
		(_FETCH_FIELD, _ANCHOR_FIELD),
		(_REJECTION_BLOCK[0], _FETCH_FIELD),
		(_WORKSTATION_BLOCK[0], _REJECTION_BLOCK[0]),
	):
		if frappe.db.exists("Custom Field", f"Stock Entry-{fieldname}"):
			frappe.db.set_value(
				"Custom Field",
				f"Stock Entry-{fieldname}",
				"insert_after",
				insert_after,
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
	if not field_order or _FETCH_FIELD not in field_order or _ANCHOR_FIELD not in field_order:
		return
	block = [_FETCH_FIELD, *_REJECTION_BLOCK, *_WORKSTATION_BLOCK]
	movable = [fieldname for fieldname in block if fieldname in field_order]
	for fieldname in movable:
		field_order.remove(fieldname)
	index = field_order.index(_ANCHOR_FIELD) + 1
	field_order[index:index] = movable
	doc.value = json.dumps(field_order)
	doc.save(ignore_permissions=True)
