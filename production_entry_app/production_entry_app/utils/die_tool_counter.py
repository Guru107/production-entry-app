from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.query_builder import DocType as QBDocType
from frappe.query_builder.functions import CustomFunction
from frappe.utils import cint, flt, get_datetime, now_datetime


def update_counter_for_stock_entry(doc, direction: int = 1) -> None:
	if doc.get("purpose") != "Manufacture":
		return

	item_code = _get_fg_item_code(doc)
	if not item_code:
		return
	if not is_die_tool_enabled(item_code):
		return

	strokes_per_unit = float(frappe.db.get_value("Item", item_code, "custom_strokes_per_unit") or 0)
	if strokes_per_unit <= 0:
		return

	total_units = _get_total_units(doc)
	if total_units <= 0:
		return

	stroke_delta = total_units * strokes_per_unit * direction
	counter_name = _ensure_counter_exists(item_code)
	die_tool_counter = QBDocType("Die Tool Counter")

	frappe.qb.update(die_tool_counter).set(
		die_tool_counter.current_stroke_count, die_tool_counter.current_stroke_count + stroke_delta
	).where(die_tool_counter.name == counter_name).run()

	if stroke_delta < 0:
		greatest = CustomFunction("GREATEST", ["value", "minimum"])
		frappe.qb.update(die_tool_counter).set(
			die_tool_counter.current_stroke_count,
			greatest(die_tool_counter.current_stroke_count, 0),
		).where(die_tool_counter.name == counter_name).run()

	frappe.db.set_value(
		"Die Tool Counter",
		counter_name,
		"stroke_capacity",
		float(frappe.db.get_value("Item", item_code, "custom_stroke_capacity") or 0),
		update_modified=False,
	)


def reset_counter_from_maintenance_log(item_code: str, maintenance_date: str | datetime.datetime) -> None:
	if not item_code:
		frappe.throw(_("Die Tool Item is required to reset stroke count."))

	counter_name = _ensure_counter_exists(item_code)
	frappe.db.set_value(
		"Die Tool Counter",
		counter_name,
		{
			"current_stroke_count": 0,
			"last_reset_on": get_datetime(maintenance_date) if maintenance_date else now_datetime(),
			"last_reset_by": frappe.session.user,
		},
		update_modified=False,
	)


def get_counter_health(
	current_strokes: float,
	stroke_capacity: float,
	warning_threshold_pct: float = 90,
	precision: int = 3,
) -> tuple[float, int]:
	utilization_pct = flt((current_strokes / stroke_capacity) * 100, precision) if stroke_capacity > 0 else 0
	is_maintenance_due = 1 if stroke_capacity > 0 and utilization_pct >= warning_threshold_pct else 0
	return utilization_pct, is_maintenance_due


def _ensure_counter_exists(item_code: str) -> str:
	if frappe.db.exists("Die Tool Counter", item_code):
		return item_code

	doc = frappe.get_doc(
		{
			"doctype": "Die Tool Counter",
			"die_tool_item": item_code,
			"current_stroke_count": 0,
		}
	)

	try:
		return doc.insert(ignore_permissions=True).name
	except frappe.DuplicateEntryError:
		# Concurrent requests can race here; read the winning row.
		if frappe.db.exists("Die Tool Counter", item_code):
			return item_code
		existing_name = frappe.db.get_value(
			"Die Tool Counter",
			{"die_tool_item": item_code},
			"name",
		)
		if existing_name:
			return existing_name
		raise


def _get_or_create_counter(item_code: str):
	return frappe.get_doc("Die Tool Counter", _ensure_counter_exists(item_code))


def is_die_tool_enabled(item_code: str | None) -> bool:
	if not item_code:
		return False

	item_meta = frappe.get_meta("Item", cached=True)
	if not item_meta.has_field("custom_has_die_tool"):
		return True

	has_die_tool = frappe.db.get_value("Item", item_code, "custom_has_die_tool")
	if has_die_tool is None:
		return True
	return cint(has_die_tool) == 1


def _get_fg_item_code(doc) -> str | None:
	if doc.get("fg_item"):
		return doc.get("fg_item")
	for row in doc.get("items", []):
		if row.get("is_finished_item"):
			return row.get("item_code")
	return None


def _get_total_units(doc) -> float:
	rejection_qty = float(doc.get("custom_rejection_qty") or 0)
	if doc.get("fg_completed_qty"):
		return float(doc.get("fg_completed_qty") or 0) + rejection_qty
	fg_row = _get_fg_row(doc)
	if not fg_row:
		return 0.0
	return float(fg_row.get("qty") or 0) + rejection_qty


def _get_fg_row(doc):
	for row in doc.get("items", []):
		if row.get("is_finished_item"):
			return row
	return None
