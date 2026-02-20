from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.query_builder.functions import Avg, Count, CustomFunction, Sum
from frappe.utils import add_to_date, flt

from production_entry_app.production_entry_app.utils.shift_time import combine_date_time

METRICS_CACHE_TTL_SEC: int = 30


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


@frappe.whitelist()
def get_planned_losses_for_duration(
	shift_duration: str, planned_start_time: str, shift_date: str
) -> list[dict]:
	"""Return planned losses rows for given duration, start time, and date.

	Used by client script to populate the grid when shift_duration (or related fields) changes.
	"""
	if not shift_duration or not planned_start_time or not shift_date:
		return []

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
def get_linked_downtime_entries(shift_name: str) -> list[dict]:
	"""Return Downtime Entries whose time range overlaps with the given Shift.

	Downtime Entries are fetched by time overlap, not by shift link.
	A downtime spanning multiple shifts appears in each overlapping shift.
	"""
	if not shift_name:
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

	entries = frappe.get_all(
		"Downtime Entry",
		filters=[
			["from_time", "<", end_dt],
			["to_time", ">", start_dt],
		],
		fields=["name", "workstation", "operator", "from_time", "to_time", "downtime", "stop_reason"],
		order_by="from_time asc",
	)
	return entries


@frappe.whitelist()
def check_running_shift_conflict(shift_name: str) -> dict:
	"""Return whether another shift is currently Running, excluding the given shift.

	Used by client to show a warning dialog before starting a shift.
	Returns: {"has_conflict": bool, "conflicting_shifts": [{"name": str, "shift_label": str, ...}]}
	"""
	if not shift_name:
		return {"has_conflict": False, "conflicting_shifts": []}

	running = frappe.get_all(
		"Shift",
		filters=[
			["status", "=", "Running"],
			["name", "!=", shift_name],
		],
		fields=["name", "shift_label", "shift_date", "supervisor"],
	)
	return {
		"has_conflict": len(running) > 0,
		"conflicting_shifts": running,
	}


def _empty_shift_metrics() -> dict:
	return {
		"entry_count": 0,
		"total_good_qty": 0,
		"total_rejection_qty": 0,
		"total_ok_qty": 0,
		"total_duration_mins": 0,
		"avg_actual_spm": 0,
		"avg_efficiency_pct": 0,
	}


def _get_shift_metrics_cache_key(shift_name: str) -> str:
	return f"pea:shift_metrics:{shift_name}"


def _get_cached_shift_metrics(shift_name: str) -> dict | None:
	return frappe.cache().get_value(_get_shift_metrics_cache_key(shift_name))


def _set_cached_shift_metrics(shift_name: str, metrics: dict) -> None:
	frappe.cache().set_value(
		_get_shift_metrics_cache_key(shift_name), metrics, expires_in_sec=METRICS_CACHE_TTL_SEC
	)


@frappe.whitelist()
def get_shift_metrics(shift_name: str) -> dict:
	"""Return aggregate production metrics for submitted Stock Entries linked to a shift."""
	if not shift_name:
		return _empty_shift_metrics()
	if not frappe.has_permission("Shift", "read", shift_name):
		raise frappe.PermissionError
	cached_metrics = _get_cached_shift_metrics(shift_name)
	if cached_metrics is not None:
		return cached_metrics

	stock_entry = DocType("Stock Entry")
	row = (
		frappe.qb.from_(stock_entry)
		.select(
			Count(stock_entry.name).as_("entry_count"),
			Sum(stock_entry.fg_completed_qty).as_("total_good_qty"),
			Sum(stock_entry.custom_rejection_qty).as_("total_rejection_qty"),
			Sum(stock_entry.custom_actual_duration_mins).as_("total_duration_mins"),
			Avg(stock_entry.custom_operator_efficiency_pct).as_("avg_efficiency_pct"),
		)
		.where(
			(stock_entry.docstatus == 1)
			& (stock_entry.purpose == "Manufacture")
			& (stock_entry.custom_shift == shift_name)
		)
	).run(as_dict=True)

	if not row:
		empty_metrics = _empty_shift_metrics()
		_set_cached_shift_metrics(shift_name, empty_metrics)
		return empty_metrics

	metrics = row[0] or {}
	entry_count = int(metrics.get("entry_count") or 0)
	if entry_count == 0:
		empty_metrics = _empty_shift_metrics()
		_set_cached_shift_metrics(shift_name, empty_metrics)
		return empty_metrics

	total_good_qty = flt(metrics.get("total_good_qty") or 0, 3)
	total_rejection_qty = flt(metrics.get("total_rejection_qty") or 0, 3)
	total_ok_qty = flt(total_good_qty - total_rejection_qty, 3)
	total_duration_mins = flt(metrics.get("total_duration_mins") or 0, 3)
	avg_actual_spm = flt((total_ok_qty / total_duration_mins), 3) if total_duration_mins > 0 else 0
	avg_efficiency_pct = flt(metrics.get("avg_efficiency_pct") or 0, 2)

	result = {
		"entry_count": entry_count,
		"total_good_qty": total_good_qty,
		"total_rejection_qty": total_rejection_qty,
		"total_ok_qty": total_ok_qty,
		"total_duration_mins": total_duration_mins,
		"avg_actual_spm": avg_actual_spm,
		"avg_efficiency_pct": avg_efficiency_pct,
	}
	_set_cached_shift_metrics(shift_name, result)
	return result


class Shift(Document):
	def before_insert(self) -> None:
		self._set_defaults()
		self._set_warehouse_defaults_from_manufacturing_settings()

	def validate(self) -> None:
		self._validate_status()
		self._validate_field_locking()
		self._calculate_planned_end_time_and_dates()
		self._populate_planned_losses_if_needed()
		self._validate_no_overlapping_shifts()
		self._validate_unique_shift_label_per_date()

	@frappe.whitelist()
	def start_shift(self) -> None:
		"""Transition Draft -> Running.

		Status is system-managed; use this action instead of editing the Status field.
		Blocked if another shift is already Running.
		"""
		self._validate_no_other_running_shift()
		self._transition_status(to_status="Running", allowed_from=("Draft",))

	def _validate_no_other_running_shift(self) -> None:
		"""Prevent starting a shift when another shift is already Running."""
		running = frappe.get_all(
			"Shift",
			filters=[["status", "=", "Running"], ["name", "!=", self.name or ""]],
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
		"""Transition Running -> Completed.

		Status is system-managed; use this action instead of editing the Status field.
		"""
		self._transition_status(to_status="Completed", allowed_from=("Running",))

	@frappe.whitelist()
	def cancel_shift(self) -> None:
		"""Transition Draft -> Cancelled.

		Status is system-managed; use this action instead of editing the Status field.
		"""
		self._transition_status(to_status="Cancelled", allowed_from=("Draft",))

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
		"""Enforce locking: planned_losses in Running; entire doc in Completed/Cancelled."""
		if self.is_new():
			return

		if self.flags.get("allow_status_change"):
			return

		# Use DB status - reliable in all contexts (get_doc_before_save may be unset)
		db_status = frappe.db.get_value("Shift", self.name, "status")
		if not db_status:
			return

		if db_status == "Running":
			if self._planned_losses_changed():
				frappe.throw(_("Planned Losses cannot be edited when shift is Running."))

		if db_status in ("Completed", "Cancelled"):
			frappe.throw(_("Shift in {0} state cannot be modified.").format(frappe.bold(db_status)))

	def _planned_losses_changed(self) -> bool:
		"""Return True if planned_losses table content has changed."""
		before = self.get_doc_before_save()
		if not before:
			return bool(self.planned_losses)
		prev = before.get("planned_losses") or []
		curr = self.get("planned_losses") or []
		if len(prev) != len(curr):
			return True
		for i, row in enumerate(curr):
			if i >= len(prev):
				return True
			p = prev[i]
			if (
				getattr(row, "downtime_reason", None) != getattr(p, "downtime_reason", None)
				or getattr(row, "start_time", None) != getattr(p, "start_time", None)
				or getattr(row, "end_time", None) != getattr(p, "end_time", None)
			):
				return True
		return False

	def _validate_no_overlapping_shifts(self) -> None:
		"""Prevent overlapping shift time periods (exclude Cancelled)."""
		if not all([self.shift_date, self.planned_start_time, self.shift_end_date, self.planned_end_time]):
			return

		my_start = self._combine_date_time(self.shift_date, self.planned_start_time)
		my_end = self._combine_date_time(self.shift_end_date, self.planned_end_time)
		shift = DocType("Shift")
		timestamp = CustomFunction("TIMESTAMP", ["date_col", "time_col"])

		query = (
			frappe.qb.from_(shift)
			.select(shift.name)
			.where(shift.status != "Cancelled")
			.where(shift.shift_date >= add_to_date(self.shift_date, days=-1, as_string=True))
			.where(shift.shift_date <= add_to_date(self.shift_date, days=1, as_string=True))
			.where(timestamp(shift.shift_date, shift.planned_start_time) < my_end)
			.where(timestamp(shift.shift_end_date, shift.planned_end_time) > my_start)
		)
		if self.name:
			query = query.where(shift.name != self.name)

		conflict = query.limit(1).run(as_dict=True)
		if conflict:
			link = frappe.utils.get_link_to_form("Shift", conflict[0]["name"])
			frappe.throw(_("Shift time overlaps with {0}.").format(link))

	def _validate_unique_shift_label_per_date(self) -> None:
		"""Enforce unique shift_label per shift_date (exclude Cancelled)."""
		if not self.shift_date or not self.shift_label:
			return

		filters = [
			["shift_date", "=", self.shift_date],
			["shift_label", "=", self.shift_label],
			["status", "!=", "Cancelled"],
		]
		if not self.is_new():
			filters.append(["name", "!=", self.name])

		existing = frappe.get_all("Shift", filters=filters, limit=1)
		if existing:
			frappe.throw(
				_("Shift {0} already exists for date {1}.").format(
					frappe.bold(self.shift_label),
					frappe.bold(str(self.shift_date)),
				)
			)

	def _transition_status(self, *, to_status: str, allowed_from: tuple[str, ...]) -> None:
		if self.is_new():
			frappe.throw(_("Please save the Shift before changing status."))

		if self.status not in allowed_from:
			frappe.throw(
				_("Invalid status transition from {0} to {1}.").format(
					frappe.bold(self.status), frappe.bold(to_status)
				)
			)

		self.flags.allow_status_change = True
		self.status = to_status
		self.save()

		if to_status == "Running":
			_send_shift_notification(
				self,
				event="start",
				subject=_("Shift {0} has been started.").format(frappe.bold(self.name)),
			)
		elif to_status == "Completed":
			_send_shift_notification(
				self,
				event="end",
				subject=_("Shift {0} has been completed.").format(frappe.bold(self.name)),
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

	def _parse_duration_hours(self, shift_duration: str) -> int:
		try:
			duration = int(str(shift_duration).strip())
		except ValueError as e:
			frappe.throw(_("Invalid Shift Duration."), exc=e)

		if duration not in (8, 10, 12):
			frappe.throw(_("Shift Duration must be one of 8, 10, or 12 hours."))

		return duration

	def _combine_date_time(self, date_value: str, time_value: str) -> datetime.datetime:
		return combine_date_time(date_value, time_value)

	def _populate_planned_losses_if_needed(self) -> None:
		"""Auto-populate planned_losses when shift_duration, planned_start_time, or shift_date changes."""
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

		entries: list[dict] = []
		# 8h: Tea +2h (15min), Lunch +4h (30min)
		# 10h/12h: Tea +2h, Lunch +4h, Tea +6h
		entries.append(
			{
				"downtime_reason": "Tea Break",
				"start_time": add_to_date(base, hours=2).time().strftime("%H:%M:%S"),
				"end_time": add_to_date(base, hours=2, minutes=15).time().strftime("%H:%M:%S"),
			}
		)
		entries.append(
			{
				"downtime_reason": "Lunch Break",
				"start_time": add_to_date(base, hours=4).time().strftime("%H:%M:%S"),
				"end_time": add_to_date(base, hours=4, minutes=30).time().strftime("%H:%M:%S"),
			}
		)
		if duration_hours in (10, 12):
			entries.append(
				{
					"downtime_reason": "Tea Break",
					"start_time": add_to_date(base, hours=6).time().strftime("%H:%M:%S"),
					"end_time": add_to_date(base, hours=6, minutes=15).time().strftime("%H:%M:%S"),
				}
			)

		self.planned_losses = []
		for row in entries:
			self.append("planned_losses", row)

	def _set_warehouse_defaults_from_manufacturing_settings(self) -> None:
		"""Best-effort: fields are added later via fixtures (task 7.0).

		If fields don't exist yet, this should be a no-op.
		"""

		settings_doctype = "Manufacturing Settings"
		settings_name = settings_doctype

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

			value = frappe.db.get_value(settings_doctype, settings_name, settings_field)
			if value:
				setattr(self, target_field, value)
