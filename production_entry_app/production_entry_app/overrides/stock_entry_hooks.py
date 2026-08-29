from __future__ import annotations

import datetime
import math
from typing import Any

import frappe
from frappe import _
from frappe.exceptions import ValidationError
from frappe.model.document import Document
from frappe.model.meta import get_field_precision
from frappe.query_builder import DocType
from frappe.utils import flt, format_datetime, get_datetime, get_time

from production_entry_app.production_entry_app.api_timeline import invalidate_timeline_cache_for_stock_entry
from production_entry_app.production_entry_app.doctype.rejection_breakup.rejection_breakup import (
	validate_rejection_breakup_row,
)
from production_entry_app.production_entry_app.doctype.shift.shift import invalidate_shift_summary_cache
from production_entry_app.production_entry_app.joint_production import (
	is_joint_lh_rh_production,
	validate_and_apply_joint_production,
)
from production_entry_app.production_entry_app.utils.alternative_items import (
	apply_direct_manufacture_alternative_flags,
	get_bom_alternative_allowed_items,
	get_bom_item_codes,
	should_skip_direct_manufacture_alternative_row,
)
from production_entry_app.production_entry_app.utils.alternative_items import (
	get_bom_secondary_item_codes as _get_bom_secondary_item_codes,
)
from production_entry_app.production_entry_app.utils.die_tool_counter import (
	get_counter_health,
	is_die_tool_enabled,
	update_counter_for_stock_entry,
)
from production_entry_app.production_entry_app.utils.loss_time import (
	build_interval_overlap_criterion,
	get_interval_minutes,
	get_interval_overlap,
	merge_intervals,
	resolve_time_interval_in_window,
)
from production_entry_app.production_entry_app.utils.rejection_warehouse import resolve_rejection_warehouse
from production_entry_app.production_entry_app.utils.shift_time import (
	combine_date_time,
	get_shift_planned_end_datetime,
)
from production_entry_app.production_entry_app.utils.system_precision import get_system_float_precision

_DEFAULT_START_BUFFER_MINS: int = 60
_DEFAULT_END_BUFFER_MINS: int = 60
_MAX_BUFFER_MINS: int = 480
_ALLOWED_STOCK_ENTRY_SHIFT_STATUSES: tuple[str, ...] = ("Running", "Completed")


def _safe_bold(value: Any) -> str:
	return frappe.bold(frappe.utils.escape_html(str(value)))


_COMMON_OVERLAP_FIELDS: tuple[str, ...] = (
	"purpose",
	"custom_pea_shift",
	"custom_pea_actual_start_date",
	"custom_pea_actual_end_date",
)
_OVERLAP_DATETIME_FIELDS: frozenset[str] = frozenset(
	{"custom_pea_actual_start_date", "custom_pea_actual_end_date"}
)


def validate_stock_entry(doc: Document, method: str | None = None) -> None:
	"""Hook called on Stock Entry validate event.

	1. Auto-fills fields from linked Shift (if custom_pea_shift is set).
	2. Handles rejection quantity logic (if custom_pea_rejection_qty > 0).
	"""
	if doc.get("custom_pea_shift"):
		_validate_linked_shift_can_accept_stock_entry(doc)
		_apply_shift_defaults(doc)
	_stamp_late_entry_flag(doc)
	_sync_unplanned_loss_shift_links(doc)

	_validate_actual_times(doc)
	_validate_unplanned_losses_within_actual_window(doc)
	_validate_workstation_overlap(doc)
	_validate_operator_overlap(doc)
	_validate_workstation_downtime_overlap(doc)
	_default_total_strokes(doc)
	if is_joint_lh_rh_production(doc):
		validate_and_apply_joint_production(doc)
	else:
		_validate_rejection_breakup(doc)
		_set_direct_manufacture_alternative_flags(doc)
		_validate_direct_manufacture_alternative_items(doc)
		_apply_rejection_entries(doc)
	_validate_rejection_target_warehouses(doc)
	_set_entry_metrics(doc)


def _default_total_strokes(doc: Document) -> None:
	if doc.get("purpose") != "Manufacture" or is_joint_lh_rh_production(doc):
		return
	total_strokes = doc.get("custom_pea_total_strokes")
	if total_strokes in (None, "") or flt(total_strokes) == 0:
		doc.set("custom_pea_total_strokes", flt(doc.get("fg_completed_qty")))
		return
	if flt(total_strokes) <= 0:
		frappe.throw(_("Total Press Strokes must be greater than zero."))


def _stamp_late_entry_flag(doc: Document) -> None:
	"""Flag entries submitted against a Completed shift (status-at-submit)."""
	meta = frappe.get_meta("Stock Entry", cached=True)
	if not meta.has_field("custom_pea_is_late_entry"):
		return

	shift_name = doc.get("custom_pea_shift")
	is_late = 0
	if doc.docstatus == 1 and shift_name:
		if frappe.db.get_value("Shift", shift_name, "status") == "Completed":
			is_late = 1
	doc.custom_pea_is_late_entry = is_late


def on_submit_stock_entry(doc, method: str | None = None) -> None:
	update_counter_for_stock_entry(doc, direction=1)
	_invalidate_shift_dependent_caches(doc)


def on_cancel_stock_entry(doc, method: str | None = None) -> None:
	update_counter_for_stock_entry(doc, direction=-1)
	_invalidate_shift_dependent_caches(doc)


def on_trash_stock_entry(doc, method: str | None = None) -> None:
	"""Defensively delete Stock Entry loss rows in case table cleanup misses them."""
	frappe.db.delete(
		"Loss Entry",
		{
			"parenttype": "Stock Entry",
			"parent": doc.name,
		},
	)


def _invalidate_shift_dependent_caches(doc: Document) -> None:
	invalidate_shift_summary_cache(doc.get("custom_pea_shift"))
	invalidate_timeline_cache_for_stock_entry(doc)


def _apply_shift_defaults(doc) -> None:
	"""Populate Stock Entry fields from the linked Shift document.

	For draft/new Stock Entries, applies current Shift values.
	For submitted Stock Entries, only applies warehouse defaults (not planned dates),
	preserving the immutable planned dates that were locked at submission time.
	"""
	shift = frappe.get_doc("Shift", doc.custom_pea_shift)

	if frappe.get_meta("Stock Entry", cached=True).has_field("branch") and shift.branch:
		doc.branch = shift.branch

	# Only update planned dates for draft/new Stock Entries.
	# Submitted entries have their planned dates locked at submission time
	# and must not be rewritten when the Shift duration changes.
	is_submitted = doc.docstatus == 1
	if not is_submitted:
		if shift.shift_date and shift.planned_start_time:
			doc.custom_pea_planned_start_date = datetime.datetime.combine(
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
			doc.custom_pea_planned_end_date = planned_end

	if shift.work_in_progress_warehouse:
		# Shift warehouse values are defaults only; preserve explicit user choices.
		if not doc.from_warehouse:
			doc.from_warehouse = shift.work_in_progress_warehouse
		if not doc.to_warehouse:
			doc.to_warehouse = shift.work_in_progress_warehouse


def _validate_linked_shift_can_accept_stock_entry(doc) -> None:
	"""Allow linking finalized or active shifts on Stock Entry."""
	shift_name = doc.get("custom_pea_shift")
	if not shift_name:
		return
	if not frappe.has_permission("Shift", "read", shift_name):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)

	status = frappe.db.get_value("Shift", shift_name, "status")
	if status not in _ALLOWED_STOCK_ENTRY_SHIFT_STATUSES:
		frappe.throw(
			_(
				"Only Running or Completed shifts can be linked in Stock Entry. Selected shift {0} is {1}."
			).format(
				_safe_bold(shift_name),
				_safe_bold(status or _("not found")),
			)
		)


def _sync_unplanned_loss_shift_links(doc) -> None:
	"""Keep unplanned loss rows linked to the currently selected shift."""
	shift_name = doc.get("custom_pea_shift") or ""
	for row in doc.get("custom_pea_unplanned_losses") or []:
		row.shift = shift_name


def _validate_actual_times(doc) -> None:
	"""Validate that actual start/end are within planned window plus configured buffers."""
	planned_start, planned_end, actual_start, actual_end = _get_planned_actual_windows(doc)
	if not planned_start or not planned_end:
		return

	allowed_start, allowed_end = _get_actual_time_limits(planned_start, planned_end)

	if actual_start and actual_end and actual_end < actual_start:
		frappe.throw(_("Actual End Date cannot be before Actual Start Date."))

	_validate_time_within_limits(actual_start, allowed_start, allowed_end, _("Actual Start Date"))
	_validate_time_within_limits(actual_end, allowed_start, allowed_end, _("Actual End Date"))


def _get_planned_actual_windows(
	doc: Document,
) -> tuple[
	datetime.datetime | None,
	datetime.datetime | None,
	datetime.datetime | None,
	datetime.datetime | None,
]:
	return (
		_as_datetime(doc.get("custom_pea_planned_start_date")),
		_as_datetime(doc.get("custom_pea_planned_end_date")),
		_as_datetime(doc.get("custom_pea_actual_start_date")),
		_as_datetime(doc.get("custom_pea_actual_end_date")),
	)


def _get_actual_time_limits(
	planned_start: datetime.datetime,
	planned_end: datetime.datetime,
) -> tuple[datetime.datetime, datetime.datetime]:
	start_buffer = _get_shift_buffer_minutes("shift_start_buffer_mins", _DEFAULT_START_BUFFER_MINS)
	end_buffer = _get_shift_buffer_minutes("shift_end_buffer_mins", _DEFAULT_END_BUFFER_MINS)
	return (
		planned_start - datetime.timedelta(minutes=start_buffer),
		planned_end + datetime.timedelta(minutes=end_buffer),
	)


def _validate_time_within_limits(
	value: datetime.datetime | None,
	allowed_start: datetime.datetime,
	allowed_end: datetime.datetime,
	label: str,
) -> None:
	if not value or allowed_start <= value <= allowed_end:
		return
	frappe.throw(
		_("{0} must be between {1} and {2}.").format(
			label, format_datetime(allowed_start), format_datetime(allowed_end)
		)
	)


def _validate_unplanned_losses_within_actual_window(doc: Document) -> None:
	actual_start = _as_datetime(doc.get("custom_pea_actual_start_date"))
	actual_end = _as_datetime(doc.get("custom_pea_actual_end_date"))
	if not actual_start or not actual_end or actual_end < actual_start:
		return

	for row in doc.get("custom_pea_unplanned_losses") or []:
		_validate_unplanned_loss_row_within_actual_window(row, actual_start, actual_end)


def _validate_unplanned_loss_row_within_actual_window(
	row: Any,
	actual_start: datetime.datetime,
	actual_end: datetime.datetime,
) -> None:
	if not row.get("start_time") or not row.get("end_time"):
		return
	interval = resolve_time_interval_in_window(
		row.get("start_time"), row.get("end_time"), actual_start, actual_end
	)
	if interval and actual_start <= interval[0] and interval[1] <= actual_end:
		return
	frappe.throw(
		_("Row {0}: Unplanned loss must be within the Stock Entry actual time window.").format(row.idx),
		ValidationError,
	)


def _get_shift_buffer_minutes(fieldname: str, default_value: int) -> int:
	settings_meta = frappe.get_meta("Production Entry Settings", cached=True)
	if settings_meta.has_field(fieldname):
		value = frappe.db.get_single_value("Production Entry Settings", fieldname)
		if value is not None:
			buffer_mins = int(value)
			if buffer_mins < 0:
				frappe.log_error(
					title="Invalid Production Entry Settings buffer",
					message=f"{fieldname} had negative value {buffer_mins}; clamped to 0.",
				)
				return 0
			if buffer_mins > _MAX_BUFFER_MINS:
				frappe.log_error(
					title="Invalid Production Entry Settings buffer",
					message=f"{fieldname} had oversized value {buffer_mins}; clamped to {_MAX_BUFFER_MINS}.",
				)
				return _MAX_BUFFER_MINS
			return buffer_mins
	if default_value < 0:
		return 0
	if default_value > _MAX_BUFFER_MINS:
		return _MAX_BUFFER_MINS
	return default_value


def _as_datetime(value) -> datetime.datetime | None:
	if not value:
		return None
	return get_datetime(value)


def _should_check_overlap(doc) -> bool:
	return bool(
		doc.get("purpose") == "Manufacture"
		and doc.get("custom_pea_shift")
		and doc.get("custom_pea_actual_start_date")
		and doc.get("custom_pea_actual_end_date")
	)


def _did_overlap_inputs_change(doc, fieldnames: tuple[str, ...]) -> bool:
	if doc.is_new():
		return True

	previous_doc = doc.get_doc_before_save()
	if not previous_doc:
		return True

	for fieldname in fieldnames:
		current_value = doc.get(fieldname)
		previous_value = previous_doc.get(fieldname)
		if fieldname in _OVERLAP_DATETIME_FIELDS:
			current_value = _as_datetime(current_value)
			previous_value = _as_datetime(previous_value)
		if current_value != previous_value:
			return True
	return False


def _validate_workstation_overlap(doc) -> None:
	workstation = doc.get("custom_pea_workstation")
	if not workstation:
		return
	if not _did_overlap_inputs_change(doc, (*_COMMON_OVERLAP_FIELDS, "custom_pea_workstation")):
		return
	conflict = _find_overlapping_stock_entry(doc, "custom_pea_workstation", workstation)
	if not conflict:
		return

	frappe.throw(
		_("Workstation {0} is already in use by {1} during this time period.").format(
			_safe_bold(workstation),
			_safe_bold(conflict["name"]),
		)
	)


def _validate_operator_overlap(doc) -> None:
	operator = doc.get("custom_pea_operator")
	if not operator:
		return
	if not _did_overlap_inputs_change(doc, (*_COMMON_OVERLAP_FIELDS, "custom_pea_operator")):
		return
	conflict = _find_overlapping_stock_entry(doc, "custom_pea_operator", operator)
	if not conflict:
		return

	frappe.throw(
		_("Operator {0} is already assigned to {1} during this time period.").format(
			_safe_bold(operator),
			_safe_bold(conflict["name"]),
		)
	)


def _validate_workstation_downtime_overlap(doc) -> None:
	if not _should_check_overlap(doc):
		return
	workstation = doc.get("custom_pea_workstation")
	if not workstation:
		return
	if not _did_overlap_inputs_change(doc, (*_COMMON_OVERLAP_FIELDS, "custom_pea_workstation")):
		return

	start = _as_datetime(doc.get("custom_pea_actual_start_date"))
	end = _as_datetime(doc.get("custom_pea_actual_end_date"))
	conflict = _find_overlapping_downtime_entry(workstation, start, end)
	if not conflict:
		return

	frappe.throw(
		_(
			"Workstation {0} has a downtime entry ({1}) from {2} to {3} that overlaps with this production entry."
		).format(
			_safe_bold(workstation),
			_safe_bold(conflict["name"]),
			format_datetime(conflict["from_time"]),
			format_datetime(conflict["to_time"]),
		)
	)


def _find_overlapping_stock_entry(doc, fieldname: str, fieldvalue: str | None) -> dict | None:
	if not _should_check_overlap(doc) or not fieldvalue:
		return None

	start = _as_datetime(doc.get("custom_pea_actual_start_date"))
	end = _as_datetime(doc.get("custom_pea_actual_end_date"))
	stock_entry = DocType("Stock Entry")
	query = (
		frappe.qb.from_(stock_entry)
		.select(stock_entry.name)
		.where(stock_entry.docstatus != 2)
		.where(stock_entry.purpose == "Manufacture")
		.where(stock_entry.custom_pea_shift.isnotnull())
		.where(stock_entry[fieldname] == fieldvalue)
		.where(
			build_interval_overlap_criterion(
				stock_entry.custom_pea_actual_start_date,
				stock_entry.custom_pea_actual_end_date,
				start,
				end,
			)
		)
	)
	if doc.name:
		query = query.where(stock_entry.name != doc.name)

	conflict = query.limit(1).run(as_dict=True)
	return conflict[0] if conflict else None


def _find_overlapping_downtime_entry(
	workstation: str,
	start: datetime.datetime | None,
	end: datetime.datetime | None,
) -> dict | None:
	if not workstation or not start or not end:
		return None

	downtime_entry = DocType("Downtime Entry")
	query = (
		frappe.qb.from_(downtime_entry)
		.select(downtime_entry.name, downtime_entry.from_time, downtime_entry.to_time)
		.where(downtime_entry.workstation == workstation)
		.where(build_interval_overlap_criterion(downtime_entry.from_time, downtime_entry.to_time, start, end))
	)
	if frappe.get_meta("Downtime Entry", cached=True).is_submittable:
		query = query.where(downtime_entry.docstatus != 2)

	conflict = query.limit(1).run(as_dict=True)
	return conflict[0] if conflict else None


def _validate_direct_manufacture_alternative_items(doc: Document) -> None:
	if doc.get("purpose") != "Manufacture" or not doc.get("from_bom") or doc.get("work_order"):
		return
	if not doc.get("bom_no"):
		return

	bom_no = doc.get("bom_no")
	bom_item_codes = get_bom_item_codes(bom_no)
	bom_allowed_items = get_bom_alternative_allowed_items(bom_no)
	bom_secondary_item_codes = _get_bom_secondary_item_codes(bom_no)
	for row in doc.get("items") or []:
		_validate_direct_manufacture_alternative_row(
			row,
			bom_no,
			bom_item_codes,
			bom_allowed_items,
			bom_secondary_item_codes,
		)


def _set_direct_manufacture_alternative_flags(doc: Document) -> None:
	apply_direct_manufacture_alternative_flags(doc)


def _validate_direct_manufacture_alternative_row(
	row: Any,
	bom_no: str,
	bom_item_codes: set[str],
	bom_allowed_items: set[str],
	bom_secondary_item_codes: set[str] | None = None,
) -> None:
	if should_skip_direct_manufacture_alternative_row(row, bom_secondary_item_codes):
		return

	original_item = row.get("original_item")
	item_code = row.get("item_code")
	if not original_item:
		_validate_bom_contains_item(row, item_code, bom_no, bom_item_codes)
		return
	if original_item == item_code:
		_validate_bom_contains_item(row, item_code, bom_no, bom_item_codes)
		return
	if original_item not in bom_allowed_items:
		frappe.throw(
			_("Row {0}: BOM item {1} does not allow alternative items.").format(
				row.idx,
				_safe_bold(original_item),
			),
			ValidationError,
		)
	if not _is_configured_item_alternative(original_item, item_code):
		frappe.throw(
			_("Row {0}: Item {1} is not configured as an alternative for BOM item {2}.").format(
				row.idx,
				_safe_bold(item_code),
				_safe_bold(original_item),
			),
			ValidationError,
		)


def _validate_bom_contains_item(
	row: Any, item_code: str | None, bom_no: str, bom_item_codes: set[str]
) -> None:
	if not item_code or item_code in bom_item_codes:
		return
	frappe.throw(
		_("Row {0}: Item {1} is not part of BOM {2}.").format(
			row.idx,
			_safe_bold(item_code),
			_safe_bold(bom_no),
		),
		ValidationError,
	)


def _is_configured_item_alternative(original_item: str, alternative_item: str) -> bool:
	if not original_item or not alternative_item:
		return False
	if frappe.db.exists(
		"Item Alternative",
		{"item_code": original_item, "alternative_item_code": alternative_item},
	):
		return True
	return bool(
		frappe.db.exists(
			"Item Alternative",
			{"item_code": alternative_item, "alternative_item_code": original_item, "two_way": 1},
		)
	)


def _validate_rejection_breakup(doc) -> None:
	rejection_qty = float(doc.get("custom_pea_rejection_qty") or 0)
	if rejection_qty <= 0:
		doc.custom_pea_rework_qty = 0
		return

	breakup_rows = doc.get("custom_pea_rejection_breakup") or []
	if not breakup_rows:
		frappe.throw(_("Rejection Breakup is mandatory when Rejection Quantity is greater than 0."))

	total_qty = 0.0
	rework_qty = 0.0
	for row in breakup_rows:
		row_qty = validate_rejection_breakup_row(row)
		total_qty += row_qty
		if row.get("is_rework"):
			rework_qty += row_qty

	derived_abs_tol = _get_rejection_breakup_abs_tol(doc, breakup_rows)
	if not math.isclose(total_qty, rejection_qty, rel_tol=0.0, abs_tol=derived_abs_tol):
		frappe.throw(
			_("Total rejection breakup quantity ({0}) must equal Rejection Quantity ({1}).").format(
				total_qty, rejection_qty
			)
		)
	doc.custom_pea_rework_qty = flt(rework_qty)


def _get_rejection_breakup_abs_tol(doc: Document, breakup_rows: list[Any]) -> float:
	parent_precision = _get_docfield_precision("Stock Entry", "custom_pea_rejection_qty", doc)
	child_precision = (
		_get_docfield_precision("Rejection Breakup", "qty", breakup_rows[0]) if breakup_rows else 3
	)
	effective_precision = min(parent_precision, child_precision)
	return 0.5 * (10 ** (-effective_precision))


def _get_docfield_precision(doctype: str, fieldname: str, row) -> int:
	df = frappe.get_meta(doctype, cached=True).get_field(fieldname)
	if not df:
		return 3
	if df.fieldtype == "Float" and not df.precision:
		return max(int(get_system_float_precision()), 0)
	return max(int(get_field_precision(df, row) or 3), 0)


def _apply_rejection_entries(doc) -> None:
	"""Handle rejection quantity: deduct from FG row and add rejection row."""
	rejection_qty = float(doc.get("custom_pea_rejection_qty") or 0)
	existing_rejection_t_warehouse = _get_existing_rejection_target_warehouse(doc)

	_remove_existing_rejection_rows(doc)

	if rejection_qty <= 0:
		return

	fg_row = _find_finished_good_row(doc)
	if not fg_row:
		return

	_validate_rejection_qty_against_finished_good(rejection_qty, fg_row)
	rejection_warehouse = resolve_rejection_warehouse(doc, existing_rejection_t_warehouse)
	fg_row.qty -= rejection_qty
	_append_rejection_item_row(doc, fg_row, rejection_qty, rejection_warehouse)


def _validate_rejection_qty_against_finished_good(rejection_qty: float, fg_row: Any) -> None:
	if rejection_qty <= fg_row.qty:
		return
	frappe.throw(
		_("Rejection Quantity ({0}) cannot exceed Finished Good quantity ({1}).").format(
			rejection_qty, fg_row.qty
		)
	)


def _append_rejection_item_row(
	doc: Document, fg_row: Any, rejection_qty: float, rejection_warehouse: str
) -> None:
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
	rejection_row.valuation_rate = fg_row.valuation_rate or fg_row.basic_rate
	rejection_row.amount = (rejection_row.valuation_rate or 0) * rejection_qty
	rejection_row.additional_cost = (rejection_row.amount or 0) - (rejection_row.basic_amount or 0)
	rejection_row.expense_account = fg_row.expense_account
	if hasattr(fg_row, "cost_center") and fg_row.cost_center:
		rejection_row.cost_center = fg_row.cost_center
	if hasattr(fg_row, "project") and fg_row.project:
		rejection_row.project = fg_row.project
	rejection_row.custom_pea_is_rejection_item = 1
	rejection_row.is_scrap_item = 0
	rejection_row.is_finished_item = 1
	rejection_row.bom_no = ""


def _validate_rejection_target_warehouses(doc: Document) -> None:
	"""Ensure rejection rows always target a warehouse marked as rejected."""
	if not _has_rejected_warehouse_flag():
		return

	for row in doc.get("items") or []:
		if not row.get("custom_pea_is_rejection_item"):
			continue
		if not row.get("t_warehouse"):
			frappe.throw(_("Rejection row must have a Target Warehouse."))
		if not _is_rejected_warehouse(row.t_warehouse):
			frappe.throw(
				_("Rejection row Target Warehouse must be marked as Rejected Warehouse: {0}").format(
					row.t_warehouse
				)
			)


def _remove_existing_rejection_rows(doc) -> None:
	"""Remove rows marked as rejection items and restore their qty to the FG row."""
	items_to_keep = []
	total_rejection_qty = 0
	fg_row = None

	for row in doc.get("items", []):
		if row.get("custom_pea_is_rejection_item"):
			total_rejection_qty += row.qty
		else:
			items_to_keep.append(row)
			if row.get("is_finished_item"):
				fg_row = row

	if not total_rejection_qty:
		return

	if fg_row:
		fg_row.qty += total_rejection_qty

	doc.items = items_to_keep
	for idx, row in enumerate(doc.items, start=1):
		row.idx = idx


def _find_finished_good_row(doc):
	"""Find and return the finished good row from Stock Entry items."""
	for row in doc.get("items", []):
		if row.get("is_finished_item"):
			return row
	return None


def _get_existing_rejection_target_warehouse(doc) -> str | None:
	candidates = [
		row
		for row in doc.get("items", [])
		if row.get("custom_pea_is_rejection_item") and row.get("t_warehouse")
	]
	if not candidates:
		return None
	# Legacy docs can contain multiple rejection rows. Prefer an already-valid rejected warehouse;
	# among matches keep latest idx. If none are valid, fall back to latest row overall.
	if _has_rejected_warehouse_flag():
		valid_candidates = [row for row in candidates if _is_rejected_warehouse(row.get("t_warehouse"))]
		if valid_candidates:
			latest_valid = max(valid_candidates, key=lambda row: int(row.get("idx") or 0))
			return latest_valid.get("t_warehouse")
		if doc.is_new():
			# For first-save docs, ignore invalid provisional row warehouses and use Shift/Settings defaults.
			return None
	latest = max(candidates, key=lambda row: int(row.get("idx") or 0))
	return latest.get("t_warehouse")


def _has_rejected_warehouse_flag() -> bool:
	return frappe.get_meta("Warehouse", cached=True).has_field("is_rejected_warehouse")


def _is_rejected_warehouse(warehouse: str | None) -> bool:
	if not warehouse:
		return False
	return bool(frappe.db.get_value("Warehouse", warehouse, "is_rejected_warehouse"))


def _set_entry_metrics(doc) -> None:
	"""Compute read-only entry metrics used by operators and supervisors."""
	meta = frappe.get_meta("Stock Entry", cached=True)
	_set_die_tool_health_metrics(doc, meta)
	ok_qty = _get_ok_units_for_metrics(doc)
	_set_if_field(doc, meta, "custom_pea_ok_qty", flt(ok_qty))
	actual_start = _as_datetime(doc.get("custom_pea_actual_start_date"))
	actual_end = _as_datetime(doc.get("custom_pea_actual_end_date"))

	if not actual_start or not actual_end:
		_set_if_field(doc, meta, "custom_pea_actual_duration_mins", None)
		_set_if_field(doc, meta, "custom_pea_production_time_mins", None)
		_set_if_field(doc, meta, "custom_pea_actual_spm", None)
		_set_if_field(doc, meta, "custom_pea_cycle_time_sec", None)
		_set_if_field(doc, meta, "custom_pea_operator_efficiency_pct", None)
		_set_if_field(doc, meta, "custom_pea_metrics_note", "")
		return

	duration_mins = (actual_end - actual_start).total_seconds() / 60
	if duration_mins <= 0:
		_set_if_field(doc, meta, "custom_pea_actual_duration_mins", None)
		_set_if_field(doc, meta, "custom_pea_production_time_mins", None)
		_set_if_field(doc, meta, "custom_pea_actual_spm", None)
		_set_if_field(doc, meta, "custom_pea_cycle_time_sec", None)
		_set_if_field(doc, meta, "custom_pea_operator_efficiency_pct", None)
		_set_if_field(doc, meta, "custom_pea_metrics_note", "")
		return

	deducted_loss_mins = _get_deducted_loss_minutes_for_entry(doc, actual_start, actual_end)
	production_time_mins = max(duration_mins - deducted_loss_mins, 0)
	total_strokes = max(flt(doc.get("custom_pea_total_strokes")), 0)
	actual_spm = (
		(total_strokes / production_time_mins) if production_time_mins > 0 and total_strokes > 0 else 0
	)
	cycle_time_sec = (
		(production_time_mins * 60) / total_strokes if production_time_mins > 0 and total_strokes > 0 else 0
	)
	standard_spm = flt(doc.get("custom_pea_standard_spm") or 0)
	operator_efficiency = ((actual_spm / standard_spm) * 100) if standard_spm > 0 else 0

	_set_if_field(doc, meta, "custom_pea_actual_duration_mins", flt(duration_mins))
	_set_if_field(doc, meta, "custom_pea_production_time_mins", flt(production_time_mins))
	_set_if_field(doc, meta, "custom_pea_actual_spm", flt(actual_spm))
	_set_if_field(doc, meta, "custom_pea_cycle_time_sec", flt(cycle_time_sec))
	_set_if_field(doc, meta, "custom_pea_operator_efficiency_pct", flt(operator_efficiency))
	_set_if_field(
		doc, meta, "custom_pea_metrics_note", _build_metrics_note(duration_mins, deducted_loss_mins)
	)


def _build_metrics_note(duration_mins: float, deducted_loss_mins: float) -> str:
	if flt(duration_mins) <= 0:
		return ""
	if flt(deducted_loss_mins) < flt(duration_mins):
		return ""
	return _(
		"Production metrics are zero because deducted loss time covers the full actual window. Review planned losses and unplanned losses for this entry."
	)


def _get_deducted_loss_minutes_for_entry(
	doc,
	actual_start: datetime.datetime,
	actual_end: datetime.datetime,
) -> float:
	"""Return total deduplicated loss minutes that overlap the actual entry window."""
	overlap_intervals = _get_unplanned_loss_overlaps(doc, actual_start, actual_end)
	overlap_intervals.extend(_get_planned_loss_overlaps(doc, actual_start, actual_end))

	if not overlap_intervals:
		return 0.0

	merged_intervals = merge_intervals(overlap_intervals)
	total_mins = sum(get_interval_minutes(start_dt, end_dt) for start_dt, end_dt in merged_intervals)
	return flt(total_mins)


def _get_unplanned_loss_overlaps(
	doc: Document,
	actual_start: datetime.datetime,
	actual_end: datetime.datetime,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
	overlap_intervals = []
	for row in doc.get("custom_pea_unplanned_losses") or []:
		interval = resolve_time_interval_in_window(
			row.get("start_time"),
			row.get("end_time"),
			actual_start,
			actual_end,
		)
		if not interval:
			continue
		overlap = get_interval_overlap(interval[0], interval[1], actual_start, actual_end)
		if overlap:
			overlap_intervals.append(overlap)
	return overlap_intervals


def _get_planned_loss_overlaps(
	doc: Document,
	actual_start: datetime.datetime,
	actual_end: datetime.datetime,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
	planned_rows, shift_start, shift_end = _get_shift_planned_losses_for_metrics(doc)
	if not planned_rows or not shift_start or not shift_end:
		return []

	overlap_intervals = []
	for row in planned_rows:
		interval = resolve_time_interval_in_window(
			row.get("start_time"),
			row.get("end_time"),
			shift_start,
			shift_end,
		)
		if not interval:
			continue
		overlap = get_interval_overlap(interval[0], interval[1], actual_start, actual_end)
		if overlap:
			overlap_intervals.append(overlap)
	return overlap_intervals


def _get_shift_planned_losses_for_metrics(
	doc: Document,
) -> tuple[list[dict], datetime.datetime | None, datetime.datetime | None]:
	shift_name = doc.get("custom_pea_shift")
	if not shift_name:
		return [], None, None
	shift = frappe.db.get_value(
		"Shift",
		shift_name,
		["shift_date", "planned_start_time", "shift_end_date", "planned_end_time"],
		as_dict=True,
	)
	if not shift:
		return [], None, None
	shift_date = shift.get("shift_date")
	planned_start_time = shift.get("planned_start_time")
	if not shift_date or not planned_start_time:
		return [], None, None
	shift_start = combine_date_time(shift_date, planned_start_time)
	shift_end = get_shift_planned_end_datetime(
		shift_date=shift_date,
		planned_start_time=planned_start_time,
		planned_end_time=shift.get("planned_end_time"),
		shift_end_date=shift.get("shift_end_date"),
		shift_duration=None,
	)
	if not shift_end or shift_end <= shift_start:
		return [], None, None

	planned_rows = frappe.get_all(
		"Loss Entry",
		filters={"parenttype": "Shift", "parent": shift_name},
		fields=["downtime_reason", "start_time", "end_time"],
		order_by="idx asc",
	)
	return planned_rows, shift_start, shift_end


def _get_ok_units_for_metrics(doc) -> float:
	if is_joint_lh_rh_production(doc):
		gross_qty = flt(doc.get("custom_pea_lh_gross_qty")) + flt(doc.get("custom_pea_rh_gross_qty"))
		rejection_qty = flt(doc.get("custom_pea_lh_rejection_qty")) + flt(
			doc.get("custom_pea_rh_rejection_qty")
		)
		return max(gross_qty - rejection_qty, 0)
	fg_completed_qty = flt(doc.get("fg_completed_qty") or 0)
	rejection_qty_field = flt(doc.get("custom_pea_rejection_qty") or 0)
	return max(fg_completed_qty - rejection_qty_field, 0)


def _set_if_field(doc, meta, fieldname: str, value) -> None:
	if meta.has_field(fieldname):
		doc.set(fieldname, value)


def _set_die_tool_health_metrics(doc, meta) -> None:
	item_code = _get_fg_item_code_for_metrics(doc)
	if not item_code or not is_die_tool_enabled(item_code):
		_set_if_field(doc, meta, "custom_pea_die_tool_utilization_pct", 0)
		_set_if_field(doc, meta, "custom_pea_die_tool_maintenance_due", 0)
		return

	counter = frappe.db.get_value(
		"Die Tool Counter",
		item_code,
		["current_stroke_count", "stroke_capacity", "warning_threshold_pct"],
		as_dict=True,
	)

	current_strokes = float((counter or {}).get("current_stroke_count") or 0)
	stroke_capacity = float((counter or {}).get("stroke_capacity") or 0)
	warning_threshold = float((counter or {}).get("warning_threshold_pct") or 90)
	utilization_pct, maintenance_due = get_counter_health(
		current_strokes=current_strokes,
		stroke_capacity=stroke_capacity,
		warning_threshold_pct=warning_threshold,
	)

	_set_if_field(doc, meta, "custom_pea_die_tool_utilization_pct", utilization_pct)
	_set_if_field(doc, meta, "custom_pea_die_tool_maintenance_due", maintenance_due)


def _get_fg_item_code_for_metrics(doc) -> str | None:
	if is_joint_lh_rh_production(doc):
		return doc.get("custom_pea_die_tool_item")
	if doc.get("fg_item"):
		return doc.get("fg_item")
	for row in doc.get("items", []):
		if row.get("is_finished_item"):
			return row.get("item_code")
	return None
