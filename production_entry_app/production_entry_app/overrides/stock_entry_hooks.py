from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.utils import get_time


def validate_stock_entry(doc, method: str | None = None) -> None:
	"""Hook called on Stock Entry validate event.

	1. Auto-fills fields from linked Shift (if custom_shift is set).
	2. Handles rejection quantity logic (if custom_rejection_qty > 0).
	"""
	if doc.get("custom_shift"):
		_apply_shift_defaults(doc)

	_apply_rejection_entries(doc)


def _apply_shift_defaults(doc) -> None:
	"""Populate Stock Entry fields from the linked Shift document."""
	shift = frappe.get_doc("Shift", doc.custom_shift)

	if shift.branch:
		doc.custom_branch = shift.branch

	if shift.shift_date and shift.planned_start_time:
		doc.custom_planned_start_date = datetime.datetime.combine(
			frappe.utils.getdate(shift.shift_date),
			get_time(shift.planned_start_time),
		)

	end_date = shift.shift_end_date or shift.shift_date
	end_time = shift.planned_end_time
	if end_date and end_time:
		doc.custom_planned_end_date = datetime.datetime.combine(
			frappe.utils.getdate(end_date),
			get_time(end_time),
		)

	if shift.work_in_progress_warehouse:
		doc.from_warehouse = shift.work_in_progress_warehouse
		doc.to_warehouse = shift.work_in_progress_warehouse


def _apply_rejection_entries(doc) -> None:
	"""Handle rejection quantity: deduct from FG row and add rejection row."""
	rejection_qty = float(doc.get("custom_rejection_qty") or 0)

	# Step 1: Remove any existing rejection rows and restore FG qty
	_remove_existing_rejection_rows(doc)

	if rejection_qty <= 0:
		return

	# Step 2: Find the finished good row
	fg_row = _find_finished_good_row(doc)
	if not fg_row:
		return

	# Step 3: Validate rejection_qty does not exceed FG qty
	if rejection_qty > fg_row.qty:
		frappe.throw(
			_("Rejection Quantity ({0}) cannot exceed Finished Good quantity ({1}).").format(
				rejection_qty, fg_row.qty
			)
		)

	# Step 4: Resolve rejection warehouse
	rejection_warehouse = _get_rejection_warehouse(doc)

	# Step 5: Deduct from FG row
	fg_row.qty -= rejection_qty

	# Step 6: Add rejection row
	rejection_row = doc.append("items", {})
	rejection_row.item_code = fg_row.item_code
	rejection_row.item_name = fg_row.item_name
	rejection_row.description = fg_row.description
	rejection_row.uom = fg_row.uom
	rejection_row.stock_uom = fg_row.stock_uom
	rejection_row.conversion_factor = fg_row.conversion_factor
	rejection_row.qty = rejection_qty
	rejection_row.transfer_qty = rejection_qty * (fg_row.conversion_factor or 1)
	rejection_row.t_warehouse = rejection_warehouse
	rejection_row.s_warehouse = fg_row.s_warehouse
	# Copy accounting fields from FG row
	rejection_row.expense_account = fg_row.expense_account
	if hasattr(fg_row, "cost_center") and fg_row.cost_center:
		rejection_row.cost_center = fg_row.cost_center
	if hasattr(fg_row, "project") and fg_row.project:
		rejection_row.project = fg_row.project
	rejection_row.custom_is_rejection_item = 1
	rejection_row.is_scrap_item = 1
	rejection_row.is_finished_item = 0
	rejection_row.bom_no = ""


def _remove_existing_rejection_rows(doc) -> None:
	"""Remove rows marked as rejection items and restore their qty to the FG row."""
	items_to_keep = []
	total_rejection_qty = 0
	fg_row = None

	for row in doc.get("items", []):
		if row.get("custom_is_rejection_item"):
			total_rejection_qty += row.qty
		else:
			items_to_keep.append(row)
			if row.get("is_finished_item"):
				fg_row = row

	if total_rejection_qty and fg_row:
		fg_row.qty += total_rejection_qty

	if total_rejection_qty:
		doc.items = items_to_keep
		for idx, row in enumerate(doc.items, start=1):
			row.idx = idx


def _find_finished_good_row(doc):
	"""Find and return the finished good row from Stock Entry items."""
	for row in doc.get("items", []):
		if row.get("is_finished_item"):
			return row
	return None


def _get_rejection_warehouse(doc) -> str:
	"""Resolve rejection warehouse: Shift > Manufacturing Settings > error."""
	# Try from linked Shift
	if doc.get("custom_shift"):
		shift_rejection_wh = frappe.db.get_value("Shift", doc.custom_shift, "rejection_warehouse")
		if shift_rejection_wh:
			return shift_rejection_wh

	# Try from Manufacturing Settings
	settings_meta = frappe.get_meta("Manufacturing Settings", cached=True)
	if settings_meta.has_field("shift_rejection_warehouse"):
		wh = frappe.db.get_single_value("Manufacturing Settings", "shift_rejection_warehouse")
		if wh:
			return wh

	frappe.throw(_("Please set a Rejection Warehouse on the Shift or in Manufacturing Settings."))
