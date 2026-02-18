from __future__ import annotations

import datetime

import frappe
from frappe.utils import add_days, add_to_date, get_time


def combine_date_time(
	date_value: str | datetime.date | None, time_value: str | datetime.time | None
) -> datetime.datetime:
	"""Combine date + time values into a datetime."""
	return datetime.datetime.combine(frappe.utils.getdate(date_value), get_time(time_value))


def get_shift_planned_end_datetime(
	*,
	shift_date: str | datetime.date | None,
	planned_start_time: str | datetime.time | None,
	planned_end_time: str | datetime.time | None,
	shift_end_date: str | datetime.date | None,
	shift_duration: str | int | None = None,
) -> datetime.datetime | None:
	if not shift_date:
		return None

	if planned_end_time:
		end_date = shift_end_date or shift_date
		if not shift_end_date and planned_start_time:
			start_time = get_time(planned_start_time)
			end_time = get_time(planned_end_time)
			if end_time <= start_time:
				end_date = add_days(shift_date, 1)

		return datetime.datetime.combine(frappe.utils.getdate(end_date), get_time(planned_end_time))

	if not planned_start_time or not shift_duration:
		return None

	try:
		duration_hours = int(str(shift_duration).strip())
	except ValueError:
		return None

	start_dt = datetime.datetime.combine(frappe.utils.getdate(shift_date), get_time(planned_start_time))
	return add_to_date(start_dt, hours=duration_hours)
