from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.utils import get_time


@frappe.whitelist()
def get_shift_details_for_stock_entry(shift_name: str) -> dict:
	"""Return shift details to auto-populate Stock Entry fields.

	Called from the Stock Entry client script when custom_shift is set.
	"""
	if not shift_name:
		return {}

	shift = frappe.get_doc("Shift", shift_name)

	planned_start = None
	if shift.shift_date and shift.planned_start_time:
		planned_start = datetime.datetime.combine(
			frappe.utils.getdate(shift.shift_date),
			get_time(shift.planned_start_time),
		)

	planned_end = None
	end_date = shift.shift_end_date or shift.shift_date
	end_time = shift.planned_end_time
	if end_date and end_time:
		planned_end = datetime.datetime.combine(
			frappe.utils.getdate(end_date),
			get_time(end_time),
		)

	return {
		"branch": shift.branch,
		"custom_planned_start_date": str(planned_start) if planned_start else None,
		"custom_planned_end_date": str(planned_end) if planned_end else None,
		"from_warehouse": shift.work_in_progress_warehouse,
		"to_warehouse": shift.work_in_progress_warehouse,
	}
