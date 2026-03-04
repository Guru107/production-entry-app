from __future__ import annotations

import datetime

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


def resolve_time_interval_in_window(
	start_value: str | datetime.time | None,
	end_value: str | datetime.time | None,
	window_start: datetime.datetime,
	window_end: datetime.datetime,
) -> tuple[datetime.datetime, datetime.datetime] | None:
	"""Resolve a time-only interval onto the date that overlaps the given window."""
	if not start_value or not end_value:
		return None
	if not isinstance(window_start, datetime.datetime) or not isinstance(window_end, datetime.datetime):
		return None
	if window_end <= window_start:
		return None

	start_time = get_time(start_value)
	end_time = get_time(end_value)
	candidate_dates = []
	for offset in (-1, 0, 1):
		candidate_dates.append(window_start.date() + datetime.timedelta(days=offset))
		candidate_dates.append(window_end.date() + datetime.timedelta(days=offset))

	seen_dates: set[datetime.date] = set()
	best_interval: tuple[datetime.datetime, datetime.datetime] | None = None
	best_overlap_mins = 0.0
	for date_value in candidate_dates:
		if date_value in seen_dates:
			continue
		seen_dates.add(date_value)
		start_dt = datetime.datetime.combine(date_value, start_time)
		end_dt = datetime.datetime.combine(date_value, end_time)
		if end_dt < start_dt:
			end_dt += datetime.timedelta(days=1)
		overlap = get_interval_overlap(start_dt, end_dt, window_start, window_end)
		if not overlap:
			continue
		overlap_mins = get_interval_minutes(*overlap)
		if overlap_mins <= 0:
			continue
		if overlap_mins > best_overlap_mins:
			best_interval = (start_dt, end_dt)
			best_overlap_mins = overlap_mins

	return best_interval


def get_interval_overlap(
	start_1: datetime.datetime,
	end_1: datetime.datetime,
	start_2: datetime.datetime,
	end_2: datetime.datetime,
) -> tuple[datetime.datetime, datetime.datetime] | None:
	overlap_start = max(start_1, start_2)
	overlap_end = min(end_1, end_2)
	if overlap_end <= overlap_start:
		return None
	return overlap_start, overlap_end


def merge_intervals(
	intervals: list[tuple[datetime.datetime, datetime.datetime]],
) -> list[tuple[datetime.datetime, datetime.datetime]]:
	if not intervals:
		return []
	sorted_intervals = sorted(intervals, key=lambda row: row[0])
	merged: list[tuple[datetime.datetime, datetime.datetime]] = [sorted_intervals[0]]
	for start_dt, end_dt in sorted_intervals[1:]:
		last_start, last_end = merged[-1]
		if start_dt <= last_end:
			merged[-1] = (last_start, max(last_end, end_dt))
			continue
		merged.append((start_dt, end_dt))
	return merged


def get_interval_minutes(start_dt: datetime.datetime, end_dt: datetime.datetime) -> float:
	return flt(max((end_dt - start_dt).total_seconds() / 60, 0), 3)
