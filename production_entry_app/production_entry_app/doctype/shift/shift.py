from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, get_time

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
		{"loss_type": r.loss_type, "start_time": r.start_time, "end_time": r.end_time}
		for r in doc.planned_losses
	]


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
		"""
		self._transition_status(to_status="Running", allowed_from=("Draft",))

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
				getattr(row, "loss_type", None) != getattr(p, "loss_type", None)
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

		others = frappe.get_all(
			"Shift",
			filters=[
				["status", "!=", "Cancelled"],
				["name", "!=", self.name or ""],
			],
			fields=["name", "shift_date", "planned_start_time", "shift_end_date", "planned_end_time"],
		)

		for row in others:
			other_start = self._combine_date_time(row["shift_date"], row["planned_start_time"])
			other_end = self._combine_date_time(row["shift_end_date"], row["planned_end_time"])
			if my_start < other_end and my_end > other_start:
				link = frappe.utils.get_link_to_form("Shift", row["name"])
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
