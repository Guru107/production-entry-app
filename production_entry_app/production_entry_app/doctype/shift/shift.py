from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.query_builder.functions import CustomFunction, Sum
from frappe.utils import add_to_date, cint, flt, get_datetime

from production_entry_app.production_entry_app.utils.loss_time import (
	build_interval_overlap_criterion,
	build_interval_overlap_filters,
	get_loss_duration_minutes,
)
from production_entry_app.production_entry_app.utils.shift_time import combine_date_time
from production_entry_app.production_entry_app.utils.system_precision import (
	get_system_float_precision,
)

METRICS_CACHE_TTL_SEC: int = 30
WARNING_THRESHOLD_PCT_DEFAULT: float = 90.0
SHIFT_SUMMARY_TARGET_COVERAGE_PCT_MIN: float = 60.0
SHIFT_SUMMARY_COMPLETENESS_MIN_RECORDED_RATIO: float = 0.5
SHIFT_SUMMARY_WORKSTATION_MIN_PRODUCTION_MINS: float = 15.0
VALID_SHIFT_DURATIONS: frozenset[int] = frozenset({8, 10, 12, 14, 16})
RUNNING_SHIFT_USER_EDITABLE_FIELDS: frozenset[str] = frozenset(
	{
		"shift_duration",
		"raw_material_warehouse",
		"work_in_progress_warehouse",
		"rejection_warehouse",
		"scrap_warehouse",
	}
)
RUNNING_SHIFT_SERVER_COMPUTED_FIELDS: frozenset[str] = frozenset(
	{
		"planned_start_time_input",
		"planned_start_time",
		"planned_end_time",
		"shift_end_date",
		"shift_title",
	}
)
RUNNING_SHIFT_MUTABLE_FIELDS: frozenset[str] = (
	RUNNING_SHIFT_USER_EDITABLE_FIELDS | RUNNING_SHIFT_SERVER_COMPUTED_FIELDS
)
_SHIFT_START_LOSSES: list[tuple[str, int, int]] = [
	("Shift Start Up", 0, 10),
]
# JH Activity is scheduled at a fixed absolute time (10:00-10:10) if the shift window overlaps.
_JH_ACTIVITY_REASON: str = "JH Activity"
_JH_ACTIVITY_FIXED_START_TIME: datetime.time = datetime.time(10, 0, 0)
_JH_ACTIVITY_DURATION_MINS: int = 10
_FIXED_TIME_BREAKS: dict[int, list[tuple[str, str, int]]] = {
	8: [("Tea Break", "09:00", 10)],
	10: [("Tea Break", "09:00", 10), ("Lunch Break", "12:00", 30), ("Tea Break", "17:00", 10)],
	12: [("Tea Break", "09:00", 10), ("Lunch Break", "12:00", 30), ("Tea Break", "17:00", 20)],
	14: [
		("Tea Break", "09:00", 10),
		("Lunch Break", "12:00", 30),
		("Tea Break", "17:00", 20),
		("Tea Break", "20:00", 10),
	],
	16: [
		("Tea Break", "09:00", 10),
		("Lunch Break", "12:00", 30),
		("Tea Break", "17:00", 20),
		("Tea Break", "20:00", 10),
		("Dinner", "22:00", 30),
	],
}


def _get_notification_recipients_for_shift(shift_doc: Shift) -> list[str]:
	"""Return list of user emails to notify for shift events (supervisor + Manufacturing Managers)."""
	emails: list[str] = []
	supervisor = shift_doc.supervisor
	if supervisor:
		email = frappe.db.get_value("User", supervisor, "email")
		if email:
			emails.append(email)
	managers = frappe.get_all(
		"Has Role",
		filters={"role": "Manufacturing Manager", "parenttype": "User"},
		pluck="parent",
	)
	manager_users = [user for user in managers if user and user != supervisor]
	if manager_users:
		manager_emails = frappe.get_all(
			"User",
			filters={"name": ("in", manager_users), "enabled": 1},
			pluck="email",
		)
		for email in manager_emails:
			if email and email not in emails:
				emails.append(email)
	return emails


def _send_shift_notification(
	shift_doc: Shift,
	*,
	event: str,
	subject: str,
	email_content: str | None = None,
) -> None:
	"""Create notification log entries for shift start/end events."""
	recipients = _get_notification_recipients_for_shift(shift_doc)
	if not recipients:
		return
	from frappe.desk.doctype.notification_log.notification_log import (
		enqueue_create_notification,
	)

	notification_doc = {
		"type": "Alert",
		"document_type": "Shift",
		"document_name": shift_doc.name,
		"subject": subject,
		"from_user": frappe.session.user,
		"email_content": email_content,
	}
	enqueue_create_notification(recipients, notification_doc)


VALID_STATUSES: tuple[str, ...] = ("Draft", "Running", "Completed", "Cancelled")


def _resolve_shift_company(
	current_company: str | None,
	default_company: str | None,
	default_exists: bool,
	company_count: int,
	sole_company: str | None,
) -> str | None:
	if current_company:
		return current_company
	if default_company and default_exists:
		return default_company
	if company_count == 1 and sole_company:
		return sole_company
	return None


def _resolve_shift_branch(current_branch: str | None, default_branch: str | None) -> str | None:
	if current_branch:
		return current_branch
	if default_branch and frappe.db.exists("Branch", default_branch):
		return default_branch
	return (
		frappe.db.get_value("Branch", {}, "name", order_by="creation asc")
		if frappe.db.count("Branch") == 1
		else None
	)


def _get_next_shift_sequence(shift_date: str) -> int:
	prefix = f"SHIFT-{shift_date}."
	existing_names = frappe.get_all(
		"Shift",
		filters={"shift_date": shift_date},
		pluck="name",
		limit_page_length=0,
	)
	max_sequence = 0
	for name in existing_names:
		if not isinstance(name, str) or not name.startswith(prefix):
			continue
		try:
			max_sequence = max(max_sequence, int(name.rsplit(".", 1)[-1]))
		except ValueError:
			continue
	return max_sequence + 1


@frappe.whitelist()
def get_planned_losses_for_duration(
	shift_duration: str, planned_start_time: str, shift_date: str
) -> list[dict]:
	"""Return planned losses rows for given duration, start time, and date.

	Used by client script to populate the grid when shift_duration (or related fields) changes.
	"""
	if not shift_duration or not planned_start_time or not shift_date:
		return []

	if not frappe.has_permission("Shift", "create"):
		frappe.throw(_("You do not have permission to create Shift."), frappe.PermissionError)

	doc = frappe.new_doc("Shift")
	doc.shift_duration = shift_duration
	doc.planned_start_time = planned_start_time
	doc.shift_date = shift_date
	doc._populate_planned_losses()

	return [
		{"downtime_reason": r.downtime_reason, "start_time": r.start_time, "end_time": r.end_time}
		for r in doc.planned_losses
	]


@frappe.whitelist()
def get_linked_downtime_entries(shift_name: str | None = None) -> list[dict]:
	"""Return Downtime Entries whose time range overlaps with the given Shift.

	Downtime Entries are fetched by time overlap, not by shift link.
	A downtime spanning multiple shifts appears in each overlapping shift.
	"""
	if not shift_name:
		return []
	shift_exists = bool(frappe.db.exists("Shift", shift_name))
	if not shift_exists and shift_name.startswith("new-"):
		return []
	if not frappe.has_permission("Shift", "read", shift_name):
		raise frappe.PermissionError
	if not shift_exists:
		return []

	shift = frappe.db.get_value(
		"Shift",
		shift_name,
		["shift_date", "planned_start_time", "shift_end_date", "planned_end_time"],
		as_dict=True,
	)
	if not shift or not all([shift.get("shift_date"), shift.get("planned_start_time")]):
		return []

	start_dt = combine_date_time(shift["shift_date"], shift["planned_start_time"])
	end_dt = combine_date_time(
		shift.get("shift_end_date") or shift["shift_date"],
		shift.get("planned_end_time") or "23:59:59",
	)

	entries = frappe.get_list(
		"Downtime Entry",
		filters=build_interval_overlap_filters("from_time", "to_time", start_dt, end_dt),
		fields=["name", "workstation", "operator", "from_time", "to_time", "downtime", "stop_reason"],
		order_by="from_time asc",
		limit_page_length=0,
	)
	return entries


@frappe.whitelist()
def check_running_shift_conflict(shift_name: str) -> dict:
	"""Return whether another shift in the same department and branch is currently Running.

	Used by client to show a warning dialog before starting a shift.
	Returns: {"has_conflict": bool, "conflicting_shifts": [{"name": str, "shift_label": str, ...}]}
	"""
	if not shift_name:
		return {"has_conflict": False, "conflicting_shifts": []}
	if not frappe.has_permission("Shift", "read", shift_name):
		raise frappe.PermissionError

	current_shift = frappe.db.get_value(
		"Shift",
		shift_name,
		["department", "branch"],
		as_dict=True,
	)
	if not current_shift or not current_shift.get("department") or not current_shift.get("branch"):
		return {"has_conflict": False, "conflicting_shifts": []}

	running = frappe.get_list(
		"Shift",
		filters=[
			["status", "=", "Running"],
			["name", "!=", shift_name],
			["department", "=", current_shift["department"]],
			["branch", "=", current_shift["branch"]],
		],
		fields=["name", "shift_label", "shift_date", "supervisor"],
		limit_page_length=0,
	)
	return {
		"has_conflict": len(running) > 0,
		"conflicting_shifts": running,
	}


def _empty_shift_summary() -> dict:
	return {
		"float_precision": get_system_float_precision(),
		"snapshot": {
			"entry_count": 0,
			"late_entry_count": 0,
			"total_qty": 0,
			"ok_qty": 0,
			"rejection_qty": 0,
			"rejection_pct": 0,
			"recorded_production_mins": 0,
			"overall_throughput_spm": 0,
			"overall_ok_spm": 0,
			"overall_shift_efficiency_pct": None,
			"target_coverage_pct": 0,
		},
		"losses": {
			"planned_shift_mins": 0,
			"planned_loss_mins": 0,
			"planned_usable_mins": 0,
			"unplanned_loss_mins": 0,
			"unplanned_loss_breakdown": [],
		},
		"exceptions": {
			"workstations": [],
			"item_boms": [],
			"unplanned_loss_reasons": [],
		},
		"logged_downtime": {
			"recorded": False,
			"entry_count": 0,
			"total_mins": 0,
			"top_reasons": [],
		},
		"positive_signal": None,
		"completeness": {"show_banner": False, "messages": []},
	}


def _get_shift_summary_cache_key(shift_name: str) -> str:
	return f"pea:shift_summary:{shift_name}:admin"


def _get_shift_metrics_cache_key(shift_name: str) -> str:
	return _get_shift_summary_cache_key(shift_name)


def _get_cached_shift_summary(shift_name: str) -> dict | None:
	if frappe.session.user != "Administrator":
		return None
	return frappe.cache().get_value(_get_shift_summary_cache_key(shift_name))


def _set_cached_shift_summary(shift_name: str, summary: dict) -> None:
	if frappe.session.user != "Administrator":
		return
	frappe.cache().set_value(
		_get_shift_summary_cache_key(shift_name), summary, expires_in_sec=METRICS_CACHE_TTL_SEC
	)


def _with_shift_summary_float_precision(summary: dict) -> dict:
	result = dict(summary)
	result.setdefault("float_precision", get_system_float_precision())
	return result


def invalidate_shift_summary_cache(shift_name: str | None) -> None:
	if not shift_name:
		return
	frappe.cache().delete_keys(f"pea:shift_summary:{shift_name}:")


def invalidate_shift_summary_for_shift(doc, method: str | None = None) -> None:
	invalidate_shift_summary_cache(getattr(doc, "name", None))


def cleanup_orphan_stock_entry_loss_links(doc, method: str | None = None) -> None:
	"""Delete orphan Loss Entry rows before Shift trash validation runs."""
	del method
	from production_entry_app.production_entry_app.api import _cleanup_orphan_stock_entry_loss_links

	_cleanup_orphan_stock_entry_loss_links(getattr(doc, "name", None))


def invalidate_shift_summary_for_downtime_entry(doc, method: str | None = None) -> None:
	shift_names = {getattr(doc, "custom_pea_shift", None) or getattr(doc, "shift", None)}
	get_before_save = getattr(doc, "get_doc_before_save", None)
	if callable(get_before_save):
		before_doc = get_before_save()
		if before_doc:
			shift_names.add(
				getattr(before_doc, "custom_pea_shift", None) or getattr(before_doc, "shift", None)
			)
	for shift_name in shift_names:
		invalidate_shift_summary_cache(shift_name)


def _get_shift_window(shift_name: str) -> tuple[dict, datetime.datetime, datetime.datetime] | None:
	shift = frappe.db.get_value(
		"Shift",
		shift_name,
		[
			"name",
			"status",
			"shift_duration",
			"shift_date",
			"planned_start_time",
			"shift_end_date",
			"planned_end_time",
		],
		as_dict=True,
	)
	if not shift or not shift.get("shift_date") or not shift.get("planned_start_time"):
		return None
	start_dt = combine_date_time(shift["shift_date"], shift["planned_start_time"])
	end_dt = combine_date_time(
		shift.get("shift_end_date") or shift["shift_date"],
		shift.get("planned_end_time") or "23:59:59",
	)
	return shift, start_dt, end_dt


def _get_entry_production_minutes(entry: dict) -> float:
	production_time_mins = entry.get("custom_pea_production_time_mins")
	if production_time_mins is not None:
		return flt(production_time_mins)
	return flt(entry.get("custom_pea_actual_duration_mins") or 0)


def _get_logged_downtime_minutes(row: dict) -> float:
	if flt(row.get("downtime") or 0) > 0:
		return flt(row.get("downtime") or 0)
	start_dt = get_datetime(row.get("from_time")) if row.get("from_time") else None
	end_dt = get_datetime(row.get("to_time")) if row.get("to_time") else None
	if not start_dt or not end_dt or end_dt <= start_dt:
		return 0
	return flt((end_dt - start_dt).total_seconds() / 60)


def _top_reason_rows(reason_totals: dict[str, float], key_name: str = "reason") -> list[dict]:
	return [
		{key_name: reason, "mins": flt(total_mins)}
		for reason, total_mins in sorted(
			reason_totals.items(),
			key=lambda row: (-flt(row[1]), row[0]),
		)[:3]
	]


def _get_entry_summary_quantities(entry: dict) -> tuple[float, float, float, float]:
	if entry.get("custom_pea_is_joint_lh_rh"):
		total_qty = flt(entry.get("custom_pea_lh_gross_qty")) + flt(entry.get("custom_pea_rh_gross_qty"))
		rejection_qty = flt(entry.get("custom_pea_lh_rejection_qty")) + flt(
			entry.get("custom_pea_rh_rejection_qty")
		)
		return (
			total_qty,
			max(total_qty - rejection_qty, 0),
			rejection_qty,
			flt(entry.get("custom_pea_total_strokes")),
		)
	total_qty = flt(entry.get("fg_completed_qty") or 0)
	rejection_qty = flt(entry.get("custom_pea_rejection_qty") or 0)
	return total_qty, max(total_qty - rejection_qty, 0), rejection_qty, total_qty


def _build_workstation_summary_rows(entries: list[dict]) -> tuple[list[dict], dict | None]:
	aggregates: dict[str, dict] = {}
	for entry in entries:
		workstation = entry.get("custom_pea_workstation") or "Unassigned"
		aggregate = aggregates.setdefault(
			workstation,
			{
				"workstation": workstation,
				"total_qty": 0.0,
				"total_strokes": 0.0,
				"ok_qty": 0.0,
				"rejection_qty": 0.0,
				"production_mins": 0.0,
				"target_mins": 0.0,
				"standard_weighted_sum": 0.0,
			},
		)
		total_qty, ok_qty, rejection_qty, total_strokes = _get_entry_summary_quantities(entry)
		production_mins = _get_entry_production_minutes(entry)
		standard_spm = flt(entry.get("custom_pea_standard_spm") or 0)
		aggregate["total_qty"] += total_qty
		aggregate["total_strokes"] += total_strokes
		aggregate["ok_qty"] += ok_qty
		aggregate["rejection_qty"] += rejection_qty
		aggregate["production_mins"] += production_mins
		if standard_spm > 0 and production_mins > 0:
			aggregate["target_mins"] += production_mins
			aggregate["standard_weighted_sum"] += standard_spm * production_mins

	rows: list[dict] = []
	for aggregate in aggregates.values():
		production_mins = flt(aggregate["production_mins"])
		target_mins = flt(aggregate["target_mins"])
		throughput_spm = (flt(aggregate["total_strokes"]) / production_mins) if production_mins > 0 else 0
		target_coverage_pct = (target_mins / production_mins) * 100 if production_mins > 0 else 0
		weighted_target_spm = flt(aggregate["standard_weighted_sum"]) / target_mins if target_mins > 0 else 0
		efficiency_pct = None
		if (
			production_mins >= SHIFT_SUMMARY_WORKSTATION_MIN_PRODUCTION_MINS
			and target_coverage_pct >= SHIFT_SUMMARY_TARGET_COVERAGE_PCT_MIN
			and weighted_target_spm > 0
		):
			efficiency_pct = flt((throughput_spm / weighted_target_spm) * 100)
		rows.append(
			{
				"workstation": aggregate["workstation"],
				"total_qty": flt(aggregate["total_qty"]),
				"ok_qty": flt(aggregate["ok_qty"]),
				"rejection_qty": flt(aggregate["rejection_qty"]),
				"production_mins": production_mins,
				"throughput_spm": flt(throughput_spm),
				"efficiency_pct": efficiency_pct,
				"target_coverage_pct": flt(target_coverage_pct),
			}
		)

	def _sort_worst(row: dict) -> tuple[float, float, str]:
		efficiency_pct = row.get("efficiency_pct")
		if efficiency_pct is not None:
			return (0, flt(efficiency_pct), str(row["workstation"]))
		return (1, flt(row["throughput_spm"]), str(row["workstation"]))

	def _sort_best(row: dict) -> tuple[float, float, str]:
		efficiency_pct = row.get("efficiency_pct")
		if efficiency_pct is not None:
			return (0, -flt(efficiency_pct), str(row["workstation"]))
		return (1, -flt(row["throughput_spm"]), str(row["workstation"]))

	worst_rows = sorted(rows, key=_sort_worst)[:3]
	best_row = sorted(rows, key=_sort_best)[0] if rows else None
	return worst_rows, best_row


def _build_item_bom_rows(entries: list[dict]) -> list[dict]:
	aggregates: dict[str, dict] = {}
	for entry in entries:
		item_code = entry.get("item_code") or entry.get("fg_item") or _("Unknown Item")
		bom_no = entry.get("bom_no") or ""
		label = f"{item_code} / {bom_no}" if bom_no else f"{item_code} / {_('No BOM')}"
		aggregate = aggregates.setdefault(
			label,
			{
				"label": label,
				"item_code": item_code,
				"bom_no": bom_no,
				"total_qty": 0.0,
				"ok_qty": 0.0,
				"rejection_qty": 0.0,
			},
		)
		total_qty, ok_qty, rejection_qty, _total_strokes = _get_entry_summary_quantities(entry)
		aggregate["total_qty"] += total_qty
		aggregate["ok_qty"] += ok_qty
		aggregate["rejection_qty"] += rejection_qty
	rows: list[dict] = []
	for aggregate in aggregates.values():
		total_qty = flt(aggregate["total_qty"])
		rows.append(
			{
				"label": aggregate["label"],
				"item_code": aggregate["item_code"],
				"bom_no": aggregate["bom_no"] or None,
				"total_qty": total_qty,
				"ok_qty": flt(aggregate["ok_qty"]),
				"rejection_qty": flt(aggregate["rejection_qty"]),
				"rejection_pct": flt((aggregate["rejection_qty"] / total_qty) * 100) if total_qty > 0 else 0,
			}
		)
	return sorted(
		rows,
		key=lambda row: (
			-flt(row["rejection_qty"]),
			-flt(row["rejection_pct"]),
			flt(row["ok_qty"]),
			row["label"],
		),
	)[:3]


def _build_completeness_state(
	*,
	shift_status: str | None,
	entry_count: int,
	recorded_production_mins: float,
	planned_usable_mins: float,
) -> dict:
	messages: list[str] = []
	if shift_status == "Running":
		messages.append(_("Running shift summaries are provisional."))
	if entry_count == 0:
		messages.append(_("No production entries are recorded for this shift yet."))
	if (
		shift_status == "Completed"
		and planned_usable_mins > 0
		and (recorded_production_mins / planned_usable_mins) < SHIFT_SUMMARY_COMPLETENESS_MIN_RECORDED_RATIO
	):
		messages.append(_("Recorded production time looks low relative to planned usable time."))
	return {"show_banner": len(messages) > 0, "messages": messages}


def _normalize_planned_loss_time(value: Any) -> str | None:
	if hasattr(value, "strftime"):
		return value.strftime("%H:%M:%S")
	return str(value) if value is not None else None


def _format_shift_title_date(value: Any) -> str:
	if hasattr(value, "isoformat"):
		return value.isoformat()
	return str(value)


def _format_shift_title_time(value: Any) -> str:
	if isinstance(value, datetime.timedelta):
		total_seconds = int(value.total_seconds()) % 86400
		hours, remainder = divmod(total_seconds, 3600)
		minutes = remainder // 60
		return f"{hours:02d}:{minutes:02d}"
	if hasattr(value, "strftime"):
		return value.strftime("%H:%M")

	parts = str(value).strip().split(":")
	if len(parts) >= 2:
		return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"
	return str(value).strip()


def _build_shift_title(
	shift_date: Any,
	planned_start_time: Any,
	shift_end_date: Any,
	planned_end_time: Any,
) -> str:
	if not shift_date:
		return ""

	start_date = _format_shift_title_date(shift_date)
	if not planned_start_time or not planned_end_time:
		return start_date

	end_date = _format_shift_title_date(shift_end_date or shift_date)
	start_time = _format_shift_title_time(planned_start_time)
	end_time = _format_shift_title_time(planned_end_time)
	if end_date != start_date:
		return f"{start_date} {start_time} - {end_date} {end_time}"
	return f"{start_date} {start_time}-{end_time}"


def _planned_loss_signature(row: Any) -> tuple[str | None, str | None, str | None]:
	return (
		getattr(row, "downtime_reason", None),
		_normalize_planned_loss_time(getattr(row, "start_time", None)),
		_normalize_planned_loss_time(getattr(row, "end_time", None)),
	)


def _get_active_downtime_reason_checker() -> Callable[[str], bool]:
	reason_active_cache: dict[str, bool] = {}
	has_is_active_field = bool(frappe.get_meta("Downtime Reason", cached=True).has_field("is_active"))

	def is_active_reason(reason: str) -> bool:
		if reason in reason_active_cache:
			return reason_active_cache[reason]
		if not frappe.db.exists("Downtime Reason", reason):
			reason_active_cache[reason] = False
			return False
		if not has_is_active_field:
			reason_active_cache[reason] = True
			return True
		reason_active_cache[reason] = bool(frappe.db.get_value("Downtime Reason", reason, "is_active"))
		return reason_active_cache[reason]

	return is_active_reason


def _planned_loss_entry_with_start(
	reason: str,
	start_dt: datetime.datetime,
	end_dt: datetime.datetime,
) -> tuple[datetime.datetime, dict[str, str]]:
	return (
		start_dt,
		{
			"downtime_reason": reason,
			"start_time": start_dt.time().strftime("%H:%M:%S"),
			"end_time": end_dt.time().strftime("%H:%M:%S"),
		},
	)


def _get_jh_activity_entries(
	base: datetime.datetime,
	shift_end: datetime.datetime,
	is_active_reason: Callable[[str], bool],
) -> list[tuple[datetime.datetime, dict[str, str]]]:
	if not is_active_reason(_JH_ACTIVITY_REASON):
		return []
	start_dt = _find_fixed_time_in_window(base, shift_end, _JH_ACTIVITY_FIXED_START_TIME)
	if start_dt is None:
		return []
	end_dt = add_to_date(start_dt, minutes=_JH_ACTIVITY_DURATION_MINS)
	return [_planned_loss_entry_with_start(_JH_ACTIVITY_REASON, start_dt, min(end_dt, shift_end))]


def _get_fixed_time_break_entries(
	base: datetime.datetime,
	shift_end: datetime.datetime,
	duration_hours: int,
	is_active_reason: Callable[[str], bool],
) -> list[tuple[datetime.datetime, dict[str, str]]]:
	entries = []
	for reason, fixed_time, duration_mins in _FIXED_TIME_BREAKS.get(duration_hours, []):
		if not is_active_reason(reason):
			continue
		fixed_time_value = datetime.datetime.strptime(fixed_time, "%H:%M").time()
		start_dt = _find_fixed_time_in_window(base, shift_end, fixed_time_value)
		if start_dt:
			end_dt = min(add_to_date(start_dt, minutes=duration_mins), shift_end)
			if end_dt > start_dt:
				entries.append(_planned_loss_entry_with_start(reason, start_dt, end_dt))
	return entries


def _find_fixed_time_in_window(
	base: datetime.datetime,
	shift_end: datetime.datetime,
	fixed_time_value: datetime.time,
) -> datetime.datetime | None:
	candidates = [
		datetime.datetime.combine(base.date(), fixed_time_value),
		datetime.datetime.combine(base.date() + datetime.timedelta(days=1), fixed_time_value),
	]
	return next((candidate for candidate in candidates if base <= candidate < shift_end), None)


@frappe.whitelist()
def get_shift_summary(shift_name: str | None = None) -> dict:
	"""Return structured summary data for the Shift summary tab."""
	if not shift_name:
		return _empty_shift_summary()
	shift_exists = bool(frappe.db.exists("Shift", shift_name))
	if not shift_exists and shift_name.startswith("new-"):
		return _empty_shift_summary()
	if not frappe.has_permission("Shift", "read", shift_name):
		raise frappe.PermissionError
	if not shift_exists:
		return _empty_shift_summary()
	for doctype in ("Stock Entry", "BOM", "Downtime Entry"):
		if not frappe.has_permission(doctype, "read"):
			raise frappe.PermissionError
	cached_summary = _get_cached_shift_summary(shift_name)
	if cached_summary is not None:
		return _with_shift_summary_float_precision(cached_summary)

	window = _get_shift_window(shift_name)
	if not window:
		empty_summary = _empty_shift_summary()
		_set_cached_shift_summary(shift_name, empty_summary)
		return empty_summary
	shift, start_dt, end_dt = window

	entry_rows = frappe.get_list(
		"Stock Entry",
		filters={
			"docstatus": 1,
			"purpose": ["in", ["Manufacture", "Repack"]],
			"custom_pea_shift": shift_name,
		},
		or_filters={"purpose": "Manufacture", "custom_pea_is_joint_lh_rh": 1},
		fields=[
			"name",
			"purpose",
			"fg_completed_qty",
			"custom_pea_rejection_qty",
			"custom_pea_is_joint_lh_rh",
			"custom_pea_total_strokes",
			"custom_pea_lh_gross_qty",
			"custom_pea_lh_rejection_qty",
			"custom_pea_rh_gross_qty",
			"custom_pea_rh_rejection_qty",
			"custom_pea_lh_bom",
			"custom_pea_rh_bom",
			"custom_pea_is_late_entry",
			"custom_pea_actual_duration_mins",
			"custom_pea_production_time_mins",
			"custom_pea_standard_spm",
			"custom_pea_workstation",
			"bom_no",
		],
		order_by="name asc",
		limit_page_length=0,
	)
	entry_rows = [
		row
		for row in entry_rows
		if row.get("purpose") in (None, "Manufacture") or row.get("custom_pea_is_joint_lh_rh")
	]
	entry_names = [row.get("name") for row in entry_rows if row.get("name")]
	item_by_entry = (
		{
			row.get("parent"): row.get("item_code")
			for row in frappe.get_all(
				"Stock Entry Detail",
				filters={"parent": ["in", entry_names], "is_finished_item": 1},
				fields=["parent", "item_code"],
				order_by="idx asc",
			)
		}
		if entry_names
		else {}
	)
	bom_names = sorted(
		{
			bom_no
			for row in entry_rows
			for bom_no in (row.get("bom_no"), row.get("custom_pea_lh_bom"), row.get("custom_pea_rh_bom"))
			if bom_no
		}
	)
	item_by_bom = (
		{
			row.get("name"): row.get("item")
			for row in frappe.get_list(
				"BOM",
				filters={"name": ["in", bom_names]},
				fields=["name", "item"],
				limit_page_length=0,
			)
		}
		if bom_names
		else {}
	)
	for row in entry_rows:
		if row.get("custom_pea_is_joint_lh_rh"):
			lh_bom = row.get("custom_pea_lh_bom") or ""
			rh_bom = row.get("custom_pea_rh_bom") or ""
			row["bom_no"] = " + ".join(value for value in (lh_bom, rh_bom) if value)
			row["item_code"] = " + ".join(
				value for value in (item_by_bom.get(lh_bom), item_by_bom.get(rh_bom)) if value
			)
			continue
		row["item_code"] = item_by_entry.get(row.get("name")) or item_by_bom.get(row.get("bom_no")) or ""
	loss_rows = (
		frappe.get_all(
			"Loss Entry",
			filters={"parenttype": "Stock Entry", "parent": ["in", entry_names]},
			fields=["parent", "downtime_reason", "start_time", "end_time"],
		)
		if entry_names
		else []
	)
	logged_downtime_rows = frappe.get_list(
		"Downtime Entry",
		filters=[
			["custom_pea_shift", "=", shift_name],
			*build_interval_overlap_filters("from_time", "to_time", start_dt, end_dt),
		],
		fields=["name", "downtime", "from_time", "to_time", "stop_reason"],
		order_by="from_time asc",
		limit_page_length=0,
	)
	planned_loss_rows = frappe.get_all(
		"Loss Entry",
		filters={"parenttype": "Shift", "parent": shift_name},
		fields=["downtime_reason", "start_time", "end_time"],
	)

	entry_count = len(entry_rows)
	late_entry_count = sum(1 for row in entry_rows if row.get("custom_pea_is_late_entry"))
	total_qty = 0.0
	total_strokes = 0.0
	rejection_qty = 0.0
	recorded_production_mins = 0.0
	target_covered_mins = 0.0
	weighted_target_sum = 0.0
	for row in entry_rows:
		entry_total, _entry_ok, entry_rejection, entry_strokes = _get_entry_summary_quantities(row)
		total_qty += entry_total
		total_strokes += entry_strokes
		rejection_qty += entry_rejection
		production_mins = _get_entry_production_minutes(row)
		recorded_production_mins += production_mins
		standard_spm = flt(row.get("custom_pea_standard_spm") or 0)
		if standard_spm > 0 and production_mins > 0:
			target_covered_mins += production_mins
			weighted_target_sum += standard_spm * production_mins

	ok_qty = max(total_qty - rejection_qty, 0)
	rejection_pct = flt((rejection_qty / total_qty) * 100) if total_qty > 0 else 0
	overall_throughput_spm = (total_strokes / recorded_production_mins) if recorded_production_mins > 0 else 0
	overall_ok_spm = (ok_qty / recorded_production_mins) if recorded_production_mins > 0 else 0
	target_coverage_pct = (
		(target_covered_mins / recorded_production_mins) * 100 if recorded_production_mins > 0 else 0
	)
	weighted_target_spm = (weighted_target_sum / target_covered_mins) if target_covered_mins > 0 else 0
	overall_shift_efficiency_pct = (
		flt((overall_throughput_spm / weighted_target_spm) * 100)
		if weighted_target_spm > 0 and target_coverage_pct >= SHIFT_SUMMARY_TARGET_COVERAGE_PCT_MIN
		else None
	)

	unplanned_loss_reason_totals: dict[str, float] = {}
	unplanned_loss_mins = 0.0
	for row in loss_rows:
		reason = row.get("downtime_reason") or _("Unknown")
		duration_mins = get_loss_duration_minutes(row.get("start_time"), row.get("end_time"))
		if duration_mins <= 0:
			continue
		unplanned_loss_mins += duration_mins
		unplanned_loss_reason_totals[reason] = (
			flt(unplanned_loss_reason_totals.get(reason) or 0) + duration_mins
		)

	logged_downtime_reason_totals: dict[str, float] = {}
	logged_downtime_total_mins = 0.0
	for row in logged_downtime_rows:
		reason = row.get("stop_reason") or _("Unknown")
		duration_mins = _get_logged_downtime_minutes(row)
		if duration_mins <= 0:
			continue
		logged_downtime_total_mins += duration_mins
		logged_downtime_reason_totals[reason] = (
			flt(logged_downtime_reason_totals.get(reason) or 0) + duration_mins
		)

	planned_loss_mins = 0.0
	for row in planned_loss_rows:
		planned_loss_mins += get_loss_duration_minutes(row.get("start_time"), row.get("end_time"))
	planned_shift_mins = flt(shift.get("shift_duration") or 0) * 60
	planned_usable_mins = max(planned_shift_mins - planned_loss_mins, 0)

	workstation_rows, best_workstation = _build_workstation_summary_rows(entry_rows)
	summary = {
		"float_precision": get_system_float_precision(),
		"snapshot": {
			"entry_count": entry_count,
			"late_entry_count": late_entry_count,
			"total_qty": flt(total_qty),
			"ok_qty": flt(ok_qty),
			"rejection_qty": flt(rejection_qty),
			"rejection_pct": rejection_pct,
			"recorded_production_mins": flt(recorded_production_mins),
			"overall_throughput_spm": flt(overall_throughput_spm),
			"overall_ok_spm": flt(overall_ok_spm),
			"overall_shift_efficiency_pct": overall_shift_efficiency_pct,
			"target_coverage_pct": flt(target_coverage_pct),
		},
		"losses": {
			"planned_shift_mins": flt(planned_shift_mins),
			"planned_loss_mins": flt(planned_loss_mins),
			"planned_usable_mins": flt(planned_usable_mins),
			"unplanned_loss_mins": flt(unplanned_loss_mins),
			"unplanned_loss_breakdown": _top_reason_rows(unplanned_loss_reason_totals),
		},
		"exceptions": {
			"workstations": workstation_rows,
			"item_boms": _build_item_bom_rows(entry_rows),
			"unplanned_loss_reasons": _top_reason_rows(unplanned_loss_reason_totals),
		},
		"logged_downtime": {
			"recorded": len(logged_downtime_rows) > 0,
			"entry_count": len(logged_downtime_rows),
			"total_mins": flt(logged_downtime_total_mins),
			"top_reasons": _top_reason_rows(logged_downtime_reason_totals),
		},
		"positive_signal": best_workstation,
		"completeness": _build_completeness_state(
			shift_status=shift.get("status"),
			entry_count=entry_count,
			recorded_production_mins=flt(recorded_production_mins),
			planned_usable_mins=flt(planned_usable_mins),
		),
	}
	_set_cached_shift_summary(shift_name, summary)
	return summary


@frappe.whitelist()
def get_shift_aggregate_production_entries(shift_name: str | None = None) -> list[dict]:
	"""Return per-BOM aggregate production values for submitted manufacture entries in a shift."""
	if not shift_name:
		return []
	shift_exists = bool(frappe.db.exists("Shift", shift_name))
	if not shift_exists and shift_name.startswith("new-"):
		return []
	if not frappe.has_permission("Shift", "read", shift_name):
		raise frappe.PermissionError
	if not shift_exists:
		return []
	for doctype in ("Stock Entry", "BOM"):
		if not frappe.has_permission(doctype, "read"):
			raise frappe.PermissionError
	float_precision = get_system_float_precision()
	permitted_entries = frappe.get_list(
		"Stock Entry",
		filters={
			"docstatus": 1,
			"purpose": ["in", ["Manufacture", "Repack"]],
			"custom_pea_shift": shift_name,
		},
		or_filters={"purpose": "Manufacture", "custom_pea_is_joint_lh_rh": 1},
		fields=[
			"name",
			"purpose",
			"bom_no",
			"custom_pea_is_joint_lh_rh",
			"custom_pea_lh_bom",
			"custom_pea_rh_bom",
			"custom_pea_lh_gross_qty",
			"custom_pea_lh_rejection_qty",
			"custom_pea_rh_gross_qty",
			"custom_pea_rh_rejection_qty",
			"custom_pea_total_strokes",
			"custom_pea_actual_duration_mins",
			"custom_pea_production_time_mins",
		],
		limit_page_length=0,
	)
	permitted_entries = [
		row
		for row in permitted_entries
		if row.get("purpose") in (None, "Manufacture") or row.get("custom_pea_is_joint_lh_rh")
	]
	permitted_entry_names = [row.get("name") for row in permitted_entries if row.get("name")]
	if not permitted_entry_names:
		return []
	requested_bom_names = sorted(
		{
			bom_no
			for row in permitted_entries
			for bom_no in (row.get("bom_no"), row.get("custom_pea_lh_bom"), row.get("custom_pea_rh_bom"))
			if bom_no
		}
	)
	permitted_bom_names = frappe.get_list(
		"BOM",
		filters={"name": ["in", requested_bom_names]},
		pluck="name",
		limit_page_length=0,
	)
	if not permitted_bom_names:
		return []

	stock_entry = DocType("Stock Entry")
	bom = DocType("BOM")
	has_production_time_field = frappe.get_meta("Stock Entry", cached=True).has_field(
		"custom_pea_production_time_mins"
	)
	production_time_expr = (
		frappe.qb.terms.Case()
		.when(stock_entry.custom_pea_production_time_mins > 0, stock_entry.custom_pea_production_time_mins)
		.else_(stock_entry.custom_pea_actual_duration_mins)
	)
	select_fields = [
		stock_entry.bom_no.as_("bom_used"),
		bom.item.as_("item_code"),
		Sum(stock_entry.fg_completed_qty).as_("total_qty"),
		Sum(stock_entry.custom_pea_rejection_qty).as_("total_reject_qty"),
		Sum(stock_entry.custom_pea_actual_duration_mins).as_("total_duration_mins"),
	]
	if has_production_time_field:
		select_fields.insert(
			4,
			Sum(production_time_expr).as_("total_production_mins"),
		)
	rows = (
		frappe.qb.from_(stock_entry)
		.inner_join(bom)
		.on(bom.name == stock_entry.bom_no)
		.select(*select_fields)
		.where(
			(stock_entry.docstatus == 1)
			& (stock_entry.purpose == "Manufacture")
			& (stock_entry.custom_pea_shift == shift_name)
			& stock_entry.name.isin(permitted_entry_names)
			& stock_entry.bom_no.isin(permitted_bom_names)
			& stock_entry.bom_no.isnotnull()
			& (stock_entry.bom_no != "")
		)
		.groupby(stock_entry.bom_no, bom.item)
		.orderby(stock_entry.bom_no, order=frappe.qb.asc)
		.orderby(bom.item, order=frappe.qb.asc)
	).run(as_dict=True)

	result: list[dict] = []
	for row in rows:
		total_qty = flt(row.get("total_qty") or 0)
		total_reject_qty = flt(row.get("total_reject_qty") or 0)
		total_ok_qty = total_qty - total_reject_qty
		total_production_mins = row.get("total_production_mins")
		total_duration_mins = flt(
			total_production_mins
			if total_production_mins is not None
			else (row.get("total_duration_mins") or 0),
		)
		avg_spm = (total_ok_qty / total_duration_mins) if total_duration_mins > 0 else 0
		result.append(
			{
				"bom_used": row.get("bom_used"),
				"item_code": row.get("item_code"),
				"total_qty": total_qty,
				"total_ok_qty": total_ok_qty,
				"total_reject_qty": total_reject_qty,
				"avg_spm": avg_spm,
				"float_precision": float_precision,
			}
		)

	item_by_bom = {
		row.get("name"): row.get("item")
		for row in frappe.get_list(
			"BOM",
			filters={"name": ["in", permitted_bom_names]},
			fields=["name", "item"],
			limit_page_length=0,
		)
	}
	joint_aggregates: dict[tuple[str, str], dict[str, float]] = {}
	for entry in permitted_entries:
		if not entry.get("custom_pea_is_joint_lh_rh"):
			continue
		lh_bom = entry.get("custom_pea_lh_bom") or ""
		rh_bom = entry.get("custom_pea_rh_bom") or ""
		key = (lh_bom, rh_bom)
		aggregate = joint_aggregates.setdefault(
			key,
			{"total_qty": 0.0, "total_reject_qty": 0.0, "total_strokes": 0.0, "mins": 0.0},
		)
		aggregate["total_qty"] += flt(entry.get("custom_pea_lh_gross_qty")) + flt(
			entry.get("custom_pea_rh_gross_qty")
		)
		aggregate["total_reject_qty"] += flt(entry.get("custom_pea_lh_rejection_qty")) + flt(
			entry.get("custom_pea_rh_rejection_qty")
		)
		aggregate["total_strokes"] += flt(entry.get("custom_pea_total_strokes"))
		aggregate["mins"] += flt(
			entry.get("custom_pea_production_time_mins")
			if entry.get("custom_pea_production_time_mins") is not None
			else entry.get("custom_pea_actual_duration_mins")
		)
	for (lh_bom, rh_bom), aggregate in joint_aggregates.items():
		total_qty = flt(aggregate["total_qty"])
		total_reject_qty = flt(aggregate["total_reject_qty"])
		mins = flt(aggregate["mins"])
		result.append(
			{
				"bom_used": " + ".join(value for value in (lh_bom, rh_bom) if value),
				"item_code": " + ".join(
					value for value in (item_by_bom.get(lh_bom), item_by_bom.get(rh_bom)) if value
				),
				"total_qty": total_qty,
				"total_ok_qty": max(total_qty - total_reject_qty, 0),
				"total_reject_qty": total_reject_qty,
				"avg_spm": flt(aggregate["total_strokes"] / mins) if mins > 0 else 0,
				"float_precision": float_precision,
			}
		)

	return result


def _sanitize_department_for_name(department_name: str) -> str:
	"""Sanitize department name for use in Shift autoname (alphanumeric, hyphen, and underscore only)."""
	if not department_name:
		frappe.throw(_("Department is required."))
	allowed: list[str] = []
	for char in str(department_name).strip():
		if char.isalnum() or char in "-_":
			allowed.append(char)
		else:
			allowed.append("-")
	result = "".join(allowed).strip("-")
	if not result:
		frappe.throw(_("Department name could not be sanitized for naming."))
	return result


def _resolve_department_name_for_shift_naming(department: str) -> str:
	"""Resolve the human-facing Department label to use in Shift names."""
	if not department:
		frappe.throw(_("Department is required."))
	department_name = frappe.db.get_value("Department", department, "department_name")
	if department_name and str(department_name).strip():
		return str(department_name).strip()
	return department


class Shift(Document):
	def autoname(self) -> None:
		"""Format: SHIFT-{shift_date}.{shift_label}.{sequence:04d}."""
		if not self.shift_date or not self.shift_label:
			return
		sequence = _get_next_shift_sequence(self.shift_date)
		self.name = f"SHIFT-{self.shift_date}.{self.shift_label}.{sequence:04d}"

	def before_insert(self) -> None:
		self._set_defaults()
		self._set_warehouse_defaults_from_production_entry_settings()

	def validate(self) -> None:
		self._ensure_company()
		self._ensure_branch()
		self._validate_status()
		self._validate_field_locking()
		self._calculate_planned_end_time_and_dates()
		self._set_shift_title()
		self._populate_planned_losses_if_needed()
		self._validate_no_overlapping_shifts()
		self._validate_unique_shift_label_per_date()

	@frappe.whitelist()
	def start_shift(self) -> None:
		self._validate_no_other_running_shift()
		self._transition_status(to_status="Running", allowed_from=("Draft",))

	def _validate_no_other_running_shift(self) -> None:
		"""Prevent starting a shift when another shift in the same department and branch is already Running."""
		if not self.department or not self.branch:
			return

		running = frappe.get_all(
			"Shift",
			filters=[
				["status", "=", "Running"],
				["name", "!=", self.name or ""],
				["department", "=", self.department],
				["branch", "=", self.branch],
			],
			fields=["name", "shift_label", "shift_date"],
			limit=1,
		)
		if running:
			s = running[0]
			frappe.throw(
				_("Cannot start shift. {0} ({1}) is already Running.").format(
					frappe.utils.get_link_to_form("Shift", s["name"]),
					s.get("shift_label") or s["name"],
				)
			)

	@frappe.whitelist()
	def end_shift(self) -> None:
		self._transition_status(to_status="Completed", allowed_from=("Running",))

	@frappe.whitelist()
	def cancel_shift(self) -> None:
		self._transition_status(to_status="Cancelled", allowed_from=("Draft", "Completed"))

	def _set_defaults(self) -> None:
		if not self.naming_series:
			# Present for standard naming-series compatibility (even if autoname is `format:`).
			self.naming_series = "SHIFT-"

		if not self.shift_date:
			self.shift_date = frappe.utils.today()

		if not self.planned_start_time:
			self.planned_start_time = frappe.utils.nowtime()

		if not self.supervisor:
			self.supervisor = frappe.session.user

		if not self.status:
			self.status = "Draft"

	def _ensure_company(self) -> None:
		if getattr(self, "company", None):
			return

		default_company = frappe.db.get_single_value("Global Defaults", "default_company")
		company_count = frappe.db.count("Company")
		sole_company = None
		if company_count == 1:
			sole_company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")

		self.company = _resolve_shift_company(
			current_company=None,
			default_company=default_company,
			default_exists=bool(default_company and frappe.db.exists("Company", default_company)),
			company_count=company_count,
			sole_company=sole_company,
		)
		if self.company:
			return

		frappe.throw(_("Company is required to create a Shift."))

	def _ensure_branch(self) -> None:
		if getattr(self, "branch", None):
			return

		default_branch = None
		for key in ("branch", "Branch"):
			default_branch = frappe.defaults.get_user_default(key)
			if default_branch:
				break

		self.branch = _resolve_shift_branch(
			current_branch=None,
			default_branch=default_branch,
		)
		if self.branch:
			return

		frappe.throw(_("Branch is required to create a Shift."))

	def _validate_status(self) -> None:
		if not self.status:
			self.status = "Draft"

		if self.status not in VALID_STATUSES:
			frappe.throw(_("Invalid status value."))

		# Prevent direct edits to status from form/API.
		if self.is_new():
			return

		if self.has_value_changed("status") and not self.flags.get("allow_status_change"):
			frappe.throw(_("Status is system-managed. Use Start Shift / End Shift actions."))

	def _validate_field_locking(self) -> None:
		"""Enforce locking: planned_losses and most fields in Running; entire doc in Completed/Cancelled.

		shift_duration changes are allowed in Running state and trigger recalculation of
		planned_end_time, shift_end_date, and planned_losses.
		"""
		if self.is_new():
			return

		if self.flags.get("allow_status_change"):
			return

		current_status = self._get_current_status_for_locking()
		if not current_status:
			return

		if current_status == "Running":
			self._validate_running_shift_edits()

		if current_status in ("Completed", "Cancelled"):
			frappe.throw(
				_("Shift in {0} state cannot be modified.").format(
					frappe.bold(frappe.utils.escape_html(str(current_status)))
				)
			)

	def _get_current_status_for_locking(self) -> str | None:
		before = self.get_doc_before_save()
		return before.status if before else frappe.db.get_value("Shift", self.name, "status")

	def _validate_running_shift_edits(self) -> None:
		if self._planned_losses_changed():
			frappe.throw(_("Planned Losses cannot be edited when shift is Running."))
		if self._get_locked_scalar_field_changes():
			frappe.throw(_("Only shift duration and warehouse fields can be edited when shift is Running."))

	def _get_locked_scalar_field_changes(self) -> set[str]:
		# Only check scalar fields via has_value_changed; child tables (e.g. planned_losses)
		# may report false positives after reload due to object identity vs content equality.
		return {
			f.fieldname
			for f in self.meta.get("fields", [])
			if f.fieldtype != "Table"
			and self.has_value_changed(f.fieldname)
			and f.fieldname not in RUNNING_SHIFT_MUTABLE_FIELDS
		}

	def _planned_losses_changed(self) -> bool:
		"""Return True if planned_losses table content has changed."""
		before = self.get_doc_before_save()
		if not before:
			return bool(self.planned_losses)
		prev = before.get("planned_losses") or []
		curr = self.get("planned_losses") or []
		if len(prev) != len(curr):
			return True
		return any(
			_planned_loss_signature(row) != _planned_loss_signature(prev[i]) for i, row in enumerate(curr)
		)

	def _validate_no_overlapping_shifts(self) -> None:
		"""Prevent overlapping shift time periods (exclude Cancelled)."""
		if not all(
			[
				self.shift_date,
				self.planned_start_time,
				self.shift_end_date,
				self.planned_end_time,
				self.department,
				self.branch,
			]
		):
			return

		my_start = self._combine_date_time(self.shift_date, self.planned_start_time)
		my_end = self._combine_date_time(self.shift_end_date, self.planned_end_time)
		shift = DocType("Shift")
		timestamp = CustomFunction("TIMESTAMP", ["date_col", "time_col"])

		query = (
			frappe.qb.from_(shift)
			.select(shift.name)
			.where(shift.status != "Cancelled")
			.where(shift.department == self.department)
			.where(shift.branch == self.branch)
			.where(shift.shift_date >= add_to_date(self.shift_date, days=-1, as_string=True))
			.where(shift.shift_date <= add_to_date(self.shift_date, days=1, as_string=True))
			.where(
				build_interval_overlap_criterion(
					timestamp(shift.shift_date, shift.planned_start_time),
					timestamp(shift.shift_end_date, shift.planned_end_time),
					my_start,
					my_end,
				)
			)
		)
		if self.name:
			query = query.where(shift.name != self.name)

		conflict = query.limit(1).run(as_dict=True)
		if conflict:
			link = frappe.utils.get_link_to_form("Shift", conflict[0]["name"])
			frappe.throw(_("Shift time overlaps with {0}.").format(link))

	def _validate_unique_shift_label_per_date(self) -> None:
		"""Enforce unique shift_label per shift_date within the same department and branch."""
		if not self.shift_date or not self.shift_label or not self.department or not self.branch:
			return

		filters = [
			["shift_date", "=", self.shift_date],
			["shift_label", "=", self.shift_label],
			["department", "=", self.department],
			["branch", "=", self.branch],
			["status", "!=", "Cancelled"],
		]
		if not self.is_new():
			filters.append(["name", "!=", self.name])

		existing = frappe.get_all("Shift", filters=filters, limit=1)
		if existing:
			frappe.throw(
				_("Shift {0} already exists for date {1}.").format(
					frappe.bold(frappe.utils.escape_html(str(self.shift_label))),
					frappe.bold(frappe.utils.escape_html(str(self.shift_date))),
				)
			)

	def _transition_status(self, *, to_status: str, allowed_from: tuple[str, ...]) -> None:
		if self.is_new():
			frappe.throw(_("Please save the Shift before changing status."))

		if self.status not in allowed_from:
			frappe.throw(
				_("Invalid status transition from {0} to {1}.").format(
					frappe.bold(frappe.utils.escape_html(str(self.status))),
					frappe.bold(frappe.utils.escape_html(str(to_status))),
				)
			)

		self.flags.allow_status_change = True
		self.status = to_status
		self.save()
		self.add_comment(
			"Info",
			_("Status changed to {0} by {1}").format(
				frappe.bold(frappe.utils.escape_html(str(to_status))),
				frappe.bold(frappe.utils.escape_html(str(frappe.session.user))),
			),
		)

		if to_status == "Running":
			_send_shift_notification(
				self,
				event="start",
				subject=_("Shift {0} has been started.").format(
					frappe.bold(frappe.utils.escape_html(str(self.name)))
				),
			)
		elif to_status == "Completed":
			_send_shift_notification(
				self,
				event="end",
				subject=_("Shift {0} has been completed.").format(
					frappe.bold(frappe.utils.escape_html(str(self.name)))
				),
			)

	def _calculate_planned_end_time_and_dates(self) -> None:
		if not self.planned_start_time or not self.shift_duration or not self.shift_date:
			return

		duration_hours = self._parse_duration_hours(self.shift_duration)
		start_dt = self._combine_date_time(self.shift_date, self.planned_start_time)
		end_dt = add_to_date(start_dt, hours=duration_hours)

		# store as Time + Date fields
		self.planned_end_time = end_dt.time().strftime("%H:%M:%S")
		self.shift_end_date = end_dt.date().isoformat()

	def _set_shift_title(self) -> None:
		self.shift_title = _build_shift_title(
			self.shift_date,
			self.planned_start_time,
			self.shift_end_date,
			self.planned_end_time,
		)

	def _parse_duration_hours(self, shift_duration: str) -> int:
		try:
			duration = int(str(shift_duration).strip())
		except ValueError:
			frappe.throw(
				_("Invalid Shift Duration: {0}. Valid options are: {1}.").format(
					shift_duration, ", ".join(str(value) for value in sorted(VALID_SHIFT_DURATIONS))
				)
			)

		if duration not in VALID_SHIFT_DURATIONS:
			frappe.throw(
				_("Shift Duration must be one of: {0}.").format(
					", ".join(str(value) for value in sorted(VALID_SHIFT_DURATIONS))
				)
			)

		return duration

	def _combine_date_time(self, date_value: str, time_value: str) -> datetime.datetime:
		return combine_date_time(date_value, time_value)

	def _populate_planned_losses_if_needed(self) -> None:
		"""Auto-populate planned_losses when shift_duration, planned_start_time, or shift_date changes.

		Also repopulates when a Running shift's duration is changed (allowed by _validate_field_locking).
		"""
		if not self.shift_duration or not self.planned_start_time or not self.shift_date:
			return

		should_populate = (
			self.is_new()
			or self.has_value_changed("shift_duration")
			or self.has_value_changed("planned_start_time")
			or self.has_value_changed("shift_date")
		)
		if not should_populate:
			return

		self._populate_planned_losses()

	def _populate_planned_losses(self) -> None:
		"""Populate planned_losses based on shift duration and planned_start_time."""
		base = self._combine_date_time(self.shift_date, self.planned_start_time)
		duration_hours = self._parse_duration_hours(self.shift_duration)
		shift_end = add_to_date(base, hours=duration_hours)
		is_active_reason = _get_active_downtime_reason_checker()
		entries_with_start: list[tuple[datetime.datetime, dict]] = []

		for reason, offset_mins, duration_mins in _SHIFT_START_LOSSES:
			if not is_active_reason(reason):
				continue
			start_dt = add_to_date(base, minutes=offset_mins)
			end_dt = add_to_date(start_dt, minutes=duration_mins)
			entries_with_start.append(_planned_loss_entry_with_start(reason, start_dt, end_dt))

		entries_with_start.extend(_get_jh_activity_entries(base, shift_end, is_active_reason))
		entries_with_start.extend(
			_get_fixed_time_break_entries(base, shift_end, duration_hours, is_active_reason)
		)

		entries = [row for _, row in sorted(entries_with_start, key=lambda pair: pair[0])]

		self.planned_losses = []
		for row in entries:
			self.append("planned_losses", row)

	def _set_warehouse_defaults_from_production_entry_settings(self) -> None:
		"""Best-effort: populate missing warehouse defaults from Production Entry Settings."""

		settings_doctype = "Production Entry Settings"

		field_map = {
			"raw_material_warehouse": "shift_raw_material_warehouse",
			"work_in_progress_warehouse": "shift_wip_warehouse",
			"rejection_warehouse": "shift_rejection_warehouse",
			"scrap_warehouse": "shift_scrap_warehouse",
		}

		settings_meta = frappe.get_meta(settings_doctype, cached=True)

		for target_field, settings_field in field_map.items():
			if getattr(self, target_field, None):
				continue

			if not settings_meta.has_field(settings_field):
				continue

			value = frappe.db.get_single_value(settings_doctype, settings_field)
			if value:
				setattr(self, target_field, value)
