from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

from production_entry_app.production_entry_app.joint_production import JOINT_PRODUCTION_LINES_FIELD
from production_entry_app.production_entry_app.utils.stock_entry_type_flags import (
	is_joint_lh_rh_stock_entry_type,
	is_joint_production_stock_entry_type,
)

DIE_TOOL_ITEM_FIELD = "custom_pea_die_tool_item"


def _distinct_nonblank_die_tool_items(die_tool_items: Iterable[str | None]) -> list[str]:
	distinct: list[str] = []
	for item_code in die_tool_items:
		code = cstr(item_code).strip()
		if code and code not in distinct:
			distinct.append(code)
	return distinct


def prescribed_die_tool_item(die_tool_items: Iterable[str | None]) -> str:
	"""Return the one Die Tool Item shared by the selected BOMs, or blank."""
	distinct = _distinct_nonblank_die_tool_items(die_tool_items)
	if len(distinct) != 1:
		return ""
	return distinct[0]


def validate_production_bom_die_tool_consistency(doc: Document | Any) -> None:
	"""Require one Die Tool Item across all BOMs on multi-BOM production entries."""
	if not doc.get("custom_pea_shift"):
		return
	bom_names = _production_bom_names(doc)
	if len(bom_names) < 2:
		return
	if not frappe.get_meta("BOM", cached=True).has_field(DIE_TOOL_ITEM_FIELD):
		return

	rows = frappe.get_all(
		"BOM",
		filters={"name": ["in", bom_names]},
		fields=["name", DIE_TOOL_ITEM_FIELD],
	)
	by_name = {row.name: row.get(DIE_TOOL_ITEM_FIELD) for row in rows}
	die_tools = [by_name.get(name) for name in bom_names]
	if len(_distinct_nonblank_die_tool_items(die_tools)) > 1:
		frappe.throw(_("All BOMs on this production entry must use the same Die Tool Item."))
	prescribed = prescribed_die_tool_item(die_tools)
	entry_die = cstr(doc.get(DIE_TOOL_ITEM_FIELD)).strip()
	if prescribed and entry_die and entry_die != prescribed:
		frappe.throw(_("Die Tool Item must match the Die Tool Item on all selected BOMs."))


def apply_bom_die_tool_item(doc: Document | Any) -> None:
	"""Set the production entry Die Tool Item when the BOMs name one.

	A blank result leaves the field unchanged so the user can keep or enter a value.
	"""
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
	if is_joint_production_stock_entry_type(doc):
		return [
			cstr(row.get("bom_no")).strip()
			for row in (doc.get(JOINT_PRODUCTION_LINES_FIELD) or [])
			if cstr(row.get("bom_no")).strip()
		]
	if is_joint_lh_rh_stock_entry_type(doc):
		return [name for name in (doc.get("custom_pea_lh_bom"), doc.get("custom_pea_rh_bom")) if name]
	if doc.get("purpose") == "Manufacture" and doc.get("from_bom") and doc.get("bom_no"):
		return [doc.get("bom_no")]
	return []
