from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import flt, format_datetime, get_datetime, get_time

from production_entry_app.production_entry_app.utils.die_tool_counter import (
	get_counter_health,
	update_counter_for_stock_entry,
)
from production_entry_app.production_entry_app.utils.shift_time import get_shift_planned_end_datetime


def validate_stock_entry(doc, method: str | None = None) -> None:
	"""Hook called on Stock Entry validate event.

	1. Auto-fills fields from linked Shift (if custom_shift is set).
	2. Handles rejection quantity logic (if custom_rejection_qty > 0).
	"""
	if doc.get("custom_shift"):
		_apply_shift_defaults(doc)

	_validate_actual_times(doc)
	_validate_workstation_overlap(doc)
	_validate_operator_overlap(doc)
	_validate_workstation_downtime_overlap(doc)
	_validate_rejection_breakup(doc)
	_apply_rejection_entries(doc)
	_set_entry_metrics(doc)


def on_submit_stock_entry(doc, method: str | None = None) -> None:
	update_counter_for_stock_entry(doc, direction=1)


def on_cancel_stock_entry(doc, method: str | None = None) -> None:
	update_counter_for_stock_entry(doc, direction=-1)


def _apply_shift_defaults(doc) -> None:
	"""Populate Stock Entry fields from the linked Shift document."""
	shift = frappe.get_doc("Shift", doc.custom_shift)

	if shift.branch:
		doc.branch = shift.branch

	if shift.shift_date and shift.planned_start_time:
		doc.custom_planned_start_date = datetime.datetime.combine(
			frappe.utils.getdate(shift.shift_date),
			get_time(shift.planned_start_time),
		)

	planned_end = get_shift_planned_end_datetime(
		shift_date=shift.shift_date,
		planned_start_time=shift.planned_start_time,
		planned_end_time=shift.planned_end_time,
		shift_end_date=shift.shift_end_date,
		shift_duration=shift.shift_duration,
	)
	if planned_end:
		doc.custom_planned_end_date = planned_end

	if shift.work_in_progress_warehouse:
		doc.from_warehouse = shift.work_in_progress_warehouse
		doc.to_warehouse = shift.work_in_progress_warehouse


def _validate_actual_times(doc) -> None:
	"""Validate that actual start/end are within planned window plus configured buffers."""
	planned_start = _as_datetime(doc.get("custom_planned_start_date"))
	planned_end = _as_datetime(doc.get("custom_planned_end_date"))
	actual_start = _as_datetime(doc.get("custom_actual_start_date"))
	actual_end = _as_datetime(doc.get("custom_actual_end_date"))

	if not planned_start or not planned_end:
		return

	start_buffer = _get_shift_buffer_minutes("shift_start_buffer_mins", 60)
	end_buffer = _get_shift_buffer_minutes("shift_end_buffer_mins", 60)

	allowed_start = planned_start - datetime.timedelta(minutes=start_buffer)
	allowed_end = planned_end + datetime.timedelta(minutes=end_buffer)

	if actual_start and actual_end and actual_end < actual_start:
		frappe.throw(_("Actual End Date cannot be before Actual Start Date."))

	if actual_start and (actual_start < allowed_start or actual_start > allowed_end):
		frappe.throw(
			_("Actual Start Date must be between {0} and {1}.").format(
				format_datetime(allowed_start), format_datetime(allowed_end)
			)
		)

	if actual_end and (actual_end < allowed_start or actual_end > allowed_end):
		frappe.throw(
			_("Actual End Date must be between {0} and {1}.").format(
				format_datetime(allowed_start), format_datetime(allowed_end)
			)
		)


def _get_shift_buffer_minutes(fieldname: str, default_value: int) -> int:
	settings_meta = frappe.get_meta("Manufacturing Settings", cached=True)
	if settings_meta.has_field(fieldname):
		value = frappe.db.get_single_value("Manufacturing Settings", fieldname)
		if value is not None:
			return int(value)
	return default_value


def _as_datetime(value) -> datetime.datetime | None:
	if not value:
		return None
	return get_datetime(value)


def _should_check_overlap(doc) -> bool:
	return bool(
		doc.get("purpose") == "Manufacture"
		and doc.get("custom_shift")
		and doc.get("custom_actual_start_date")
		and doc.get("custom_actual_end_date")
	)


def _validate_workstation_overlap(doc) -> None:
	workstation = doc.get("custom_workstation")
	conflict = _find_overlapping_stock_entry(doc, "custom_workstation", workstation)
	if not conflict:
		return

	frappe.throw(
		_("Workstation {0} is already in use by {1} during this time period.").format(
			frappe.bold(workstation), frappe.bold(conflict["name"])
		)
	)


def _validate_operator_overlap(doc) -> None:
	operator = doc.get("custom_operator")
	conflict = _find_overlapping_stock_entry(doc, "custom_operator", operator)
	if not conflict:
		return

	frappe.throw(
		_("Operator {0} is already assigned to {1} during this time period.").format(
			frappe.bold(operator), frappe.bold(conflict["name"])
		)
	)


def _validate_workstation_downtime_overlap(doc) -> None:
	if not _should_check_overlap(doc):
		return
	workstation = doc.get("custom_workstation")
	if not workstation:
		return

	start = _as_datetime(doc.get("custom_actual_start_date"))
	end = _as_datetime(doc.get("custom_actual_end_date"))

	downtime_entry = DocType("Downtime Entry")
	query = (
		frappe.qb.from_(downtime_entry)
		.select(downtime_entry.name, downtime_entry.from_time, downtime_entry.to_time)
		.where(downtime_entry.workstation == workstation)
		.where(downtime_entry.from_time < end)
		.where(downtime_entry.to_time > start)
	)
	if frappe.get_meta("Downtime Entry", cached=True).is_submittable:
		query = query.where(downtime_entry.docstatus != 2)

	conflict = query.limit(1).run(as_dict=True)
	if not conflict:
		return

	row = conflict[0]
	frappe.throw(
		_(
			"Workstation {0} has a downtime entry ({1}) from {2} to {3} that overlaps with this production entry."
		).format(
			frappe.bold(workstation),
			frappe.bold(row["name"]),
			format_datetime(row["from_time"]),
			format_datetime(row["to_time"]),
		)
	)


def _find_overlapping_stock_entry(doc, fieldname: str, fieldvalue: str | None) -> dict | None:
	if not _should_check_overlap(doc) or not fieldvalue:
		return None

	start = _as_datetime(doc.get("custom_actual_start_date"))
	end = _as_datetime(doc.get("custom_actual_end_date"))
	stock_entry = DocType("Stock Entry")
	query = (
		frappe.qb.from_(stock_entry)
		.select(stock_entry.name)
		.where(stock_entry.docstatus != 2)
		.where(stock_entry.purpose == "Manufacture")
		.where(stock_entry.custom_shift.isnotnull())
		.where(stock_entry[fieldname] == fieldvalue)
		.where(stock_entry.custom_actual_start_date < end)
		.where(stock_entry.custom_actual_end_date > start)
	)
	if doc.name:
		query = query.where(stock_entry.name != doc.name)

	conflict = query.limit(1).run(as_dict=True)
	return conflict[0] if conflict else None


def _validate_rejection_breakup(doc) -> None:
	rejection_qty = float(doc.get("custom_rejection_qty") or 0)
	if rejection_qty <= 0:
		return

	breakup_rows = doc.get("custom_rejection_breakup") or []
	if not breakup_rows:
		frappe.throw(_("Rejection Breakup is mandatory when Rejection Quantity is greater than 0."))

	total_qty = 0.0
	for row in breakup_rows:
		row_qty = float(row.get("qty") or 0)
		if row_qty <= 0:
			frappe.throw(_("Rejection Breakup rows must have a quantity greater than 0."))
		if not row.get("rejection_reason"):
			frappe.throw(_("Rejection Breakup rows must have a rejection reason."))
		total_qty += row_qty

	if flt(total_qty, 3) != flt(rejection_qty, 3):
		frappe.throw(
			_("Total rejection breakup quantity ({0}) must equal Rejection Quantity ({1}).").format(
				total_qty, rejection_qty
			)
		)


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
	# Copy rate and accounting fields from FG row
	rejection_row.basic_rate = fg_row.basic_rate
	rejection_row.basic_amount = (fg_row.basic_rate or 0) * rejection_qty
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


def _set_entry_metrics(doc) -> None:
	"""Compute read-only entry metrics used by operators and supervisors."""
	meta = frappe.get_meta("Stock Entry", cached=True)
	_set_die_tool_health_metrics(doc, meta)
	actual_start = _as_datetime(doc.get("custom_actual_start_date"))
	actual_end = _as_datetime(doc.get("custom_actual_end_date"))

	if not actual_start or not actual_end:
		_set_if_field(doc, meta, "custom_actual_duration_mins", None)
		_set_if_field(doc, meta, "custom_actual_spm", None)
		_set_if_field(doc, meta, "custom_cycle_time_sec", None)
		_set_if_field(doc, meta, "custom_operator_efficiency_pct", None)
		return

	duration_mins = (actual_end - actual_start).total_seconds() / 60
	if duration_mins <= 0:
		_set_if_field(doc, meta, "custom_actual_duration_mins", None)
		_set_if_field(doc, meta, "custom_actual_spm", None)
		_set_if_field(doc, meta, "custom_cycle_time_sec", None)
		_set_if_field(doc, meta, "custom_operator_efficiency_pct", None)
		return

	total_units = _get_total_units_for_metrics(doc)
	actual_spm = (total_units / duration_mins) if total_units > 0 else 0
	cycle_time_sec = ((duration_mins * 60) / total_units) if total_units > 0 else 0
	standard_spm = flt(doc.get("custom_standard_spm") or 0)
	operator_efficiency = ((actual_spm / standard_spm) * 100) if standard_spm > 0 else 0

	_set_if_field(doc, meta, "custom_actual_duration_mins", flt(duration_mins, 3))
	_set_if_field(doc, meta, "custom_actual_spm", flt(actual_spm, 3))
	_set_if_field(doc, meta, "custom_cycle_time_sec", flt(cycle_time_sec, 3))
	_set_if_field(doc, meta, "custom_operator_efficiency_pct", flt(operator_efficiency, 2))


def _get_total_units_for_metrics(doc) -> float:
	fg_completed_qty = flt(doc.get("fg_completed_qty") or 0)
	rejection_qty_field = flt(doc.get("custom_rejection_qty") or 0)
	if fg_completed_qty > 0:
		return fg_completed_qty + rejection_qty_field

	fg_qty = 0.0
	rejection_qty = 0.0
	for row in doc.get("items", []):
		if row.get("custom_is_rejection_item"):
			rejection_qty += flt(row.get("qty") or 0)
		elif row.get("is_finished_item"):
			fg_qty += flt(row.get("qty") or 0)
	if rejection_qty <= 0:
		rejection_qty = rejection_qty_field
	return fg_qty + rejection_qty


def _set_if_field(doc, meta, fieldname: str, value) -> None:
	if meta.has_field(fieldname):
		doc.set(fieldname, value)


def _set_die_tool_health_metrics(doc, meta) -> None:
	item_code = _get_fg_item_code_for_metrics(doc)
	if not item_code:
		_set_if_field(doc, meta, "custom_die_tool_utilization_pct", 0)
		_set_if_field(doc, meta, "custom_die_tool_maintenance_due", 0)
		return

	counter = frappe.db.get_value(
		"Die Tool Counter",
		item_code,
		["current_stroke_count", "stroke_capacity", "warning_threshold_pct"],
		as_dict=True,
	)

	current_strokes = flt((counter or {}).get("current_stroke_count") or 0, 3)
	stroke_capacity = flt((counter or {}).get("stroke_capacity") or 0, 3)
	warning_threshold = flt((counter or {}).get("warning_threshold_pct") or 90, 3)
	utilization_pct, maintenance_due = get_counter_health(
		current_strokes=current_strokes,
		stroke_capacity=stroke_capacity,
		warning_threshold_pct=warning_threshold,
		precision=3,
	)

	_set_if_field(doc, meta, "custom_die_tool_utilization_pct", utilization_pct)
	_set_if_field(doc, meta, "custom_die_tool_maintenance_due", maintenance_due)


def _get_fg_item_code_for_metrics(doc) -> str | None:
	if doc.get("fg_item"):
		return doc.get("fg_item")
	for row in doc.get("items", []):
		if row.get("is_finished_item"):
			return row.get("item_code")
	return None
