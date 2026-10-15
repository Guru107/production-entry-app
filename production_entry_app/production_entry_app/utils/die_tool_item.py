from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import frappe
from frappe.model.document import Document
from frappe.utils import cstr

from production_entry_app.production_entry_app.joint_production import is_joint_lh_rh_production

DIE_TOOL_ITEM_FIELD = "custom_pea_die_tool_item"


def prescribed_die_tool_item(die_tool_items: Iterable[str | None]) -> str:
	"""Return the one Die Tool Item shared by the selected BOMs.

	An empty result means the BOMs do not share one die, so the production entry
	may keep an item the user selected.
	"""
	prescribed: list[str] = []
	for item_code in die_tool_items:
		code = cstr(item_code).strip()
		if code and code not in prescribed:
			prescribed.append(code)
	if len(prescribed) != 1:
		return ""
	return prescribed[0]


def apply_bom_die_tool_item(doc: Document | Any) -> None:
	"""Copy a BOM Die Tool Item onto a shift-based production entry."""
	if not doc.get("custom_pea_shift"):
		return
	if not frappe.get_meta("Stock Entry", cached=True).has_field(DIE_TOOL_ITEM_FIELD):
		return
	bom_names = _production_bom_names(doc)
	if not bom_names:
		return
	if not frappe.get_meta("BOM", cached=True).has_field(DIE_TOOL_ITEM_FIELD):
		return

	rows = frappe.get_all(
		"BOM",
		filters={"name": ["in", bom_names]},
		fields=["name", DIE_TOOL_ITEM_FIELD],
	)
	by_name = {row.name: row.get(DIE_TOOL_ITEM_FIELD) for row in rows}
	prescribed = prescribed_die_tool_item(by_name.get(name) for name in bom_names)
	if prescribed:
		doc.set(DIE_TOOL_ITEM_FIELD, prescribed)


def _production_bom_names(doc: Document | Any) -> list[str]:
	if is_joint_lh_rh_production(doc):
		return [name for name in (doc.get("custom_pea_lh_bom"), doc.get("custom_pea_rh_bom")) if name]
	if doc.get("purpose") == "Manufacture" and doc.get("from_bom") and doc.get("bom_no"):
		return [doc.get("bom_no")]
	return []
