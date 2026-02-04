from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, get_time

VALID_STATUSES: tuple[str, ...] = ("Draft", "Running", "Completed", "Cancelled")


class Shift(Document):
	def before_insert(self) -> None:
		self._set_defaults()
		self._set_warehouse_defaults_from_manufacturing_settings()

	def validate(self) -> None:
		self._validate_status()
		self._calculate_planned_end_time_and_dates()
		self._populate_planned_losses_if_needed()

	@staticmethod
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
			{"loss_type": r.loss_type, "start_time": r.start_time, "end_time": r.end_time}
			for r in doc.planned_losses
		]

	@frappe.whitelist()
	def start_shift(self) -> None:
		"""Transition Draft -> Running.

		Status is system-managed; use this action instead of editing the Status field.
		"""
		self._transition_status(to_status="Running", allowed_from=("Draft",))

	@frappe.whitelist()
	def end_shift(self) -> None:
		"""Transition Running -> Completed.

		Status is system-managed; use this action instead of editing the Status field.
		"""
		self._transition_status(to_status="Completed", allowed_from=("Running",))

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
		shift_date = frappe.utils.getdate(date_value)
		shift_time = get_time(time_value)
		return datetime.datetime.combine(shift_date, shift_time)

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
				"loss_type": "Tea Break",
				"start_time": add_to_date(base, hours=2).time().strftime("%H:%M:%S"),
				"end_time": add_to_date(base, hours=2, minutes=15).time().strftime("%H:%M:%S"),
			}
		)
		entries.append(
			{
				"loss_type": "Lunch Break",
				"start_time": add_to_date(base, hours=4).time().strftime("%H:%M:%S"),
				"end_time": add_to_date(base, hours=4, minutes=30).time().strftime("%H:%M:%S"),
			}
		)
		if duration_hours in (10, 12):
			entries.append(
				{
					"loss_type": "Tea Break",
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
