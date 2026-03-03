from __future__ import annotations

from frappe.utils import flt, get_time

SETUP_TIME_REASON: str = "Setup Time"


def get_loss_duration_minutes(start_value, end_value) -> float:
	if not start_value or not end_value:
		return 0.0
	start = get_time(start_value)
	end = get_time(end_value)
	start_mins = (start.hour * 60) + start.minute + (start.second / 60)
	end_mins = (end.hour * 60) + end.minute + (end.second / 60)
	duration_mins = end_mins - start_mins
	if duration_mins < 0:
		duration_mins += 24 * 60
	return flt(duration_mins if duration_mins > 0 else 0, 3)
