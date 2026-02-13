from __future__ import annotations

import datetime
import unittest

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase


def _ensure_downtime_reasons() -> None:
	"""Ensure Tea Break and Lunch Break Downtime Reasons exist (for planned losses tests)."""
	for name in ("Tea Break", "Lunch Break"):
		if not frappe.db.exists("Downtime Reason", name):
			frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert()


class TestShift(FrappeTestCase):
	def setUp(self) -> None:
		super().setUp()
		_ensure_downtime_reasons()
		# End any stale Running shifts so start_shift() is not blocked
		for sn in frappe.get_all("Shift", filters={"status": "Running"}, pluck="name"):
			frappe.db.set_value("Shift", sn, "status", "Completed", update_modified=False)

	def test_defaults_are_populated_on_insert(self) -> None:
		self._delete_shift_if_exists(self._expected_name(frappe.utils.today(), "1"))
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
			}
		).insert()

		self.assertEqual(doc.shift_date, frappe.utils.today())
		self.assertTrue(doc.planned_start_time)
		self.assertTrue(doc.planned_end_time)
		self.assertEqual(doc.supervisor, frappe.session.user)

	def test_planned_end_time_is_calculated(self) -> None:
		self._delete_shift_if_exists(self._expected_name("2026-02-06", "2"))
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-06",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(doc.planned_end_time, "16:00:00")
		self.assertEqual(doc.shift_end_date, "2026-02-06")

	def test_midnight_crossing_sets_shift_end_date(self) -> None:
		self._delete_shift_if_exists(self._expected_name("2026-02-07", "1"))
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "10",
				"shift_date": "2026-02-07",
				"planned_start_time": "22:00:00",
			}
		).insert()

		self.assertEqual(doc.planned_end_time, "08:00:00")
		self.assertEqual(doc.shift_end_date, "2026-02-08")

	def test_name_format(self) -> None:
		# Use date unlikely to collide with test_defaults (which uses frappe.utils.today())
		expected_name = self._expected_name("2026-04-01", "2")
		self._delete_shift_if_exists(expected_name)
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-04-01",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(doc.name, expected_name)

	def test_status_transitions_via_actions(self) -> None:
		name = self._expected_name("2026-02-09", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-09",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(doc.status, "Draft")

		doc.start_shift()
		doc.reload()
		self.assertEqual(doc.status, "Running")

		doc.end_shift()
		doc.reload()
		self.assertEqual(doc.status, "Completed")

	def test_status_transition_draft_to_cancelled(self) -> None:
		name = self._expected_name("2026-02-15", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-15",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(doc.status, "Draft")

		doc.cancel_shift()
		doc.reload()
		self.assertEqual(doc.status, "Cancelled")

	def test_cancel_shift_not_allowed_from_running(self) -> None:
		name = self._expected_name("2026-02-16", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-16",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.start_shift()

		with self.assertRaises(ValidationError):
			doc.cancel_shift()

	def test_planned_losses_locked_in_running_state(self) -> None:
		name = self._expected_name("2026-02-17", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-17",
				"planned_start_time": "08:00:00",
			}
		).insert()
		self.assertEqual(len(doc.planned_losses), 2)

		doc.start_shift()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so _validate_field_locking sees persisted status via get_value
		doc = frappe.get_doc("Shift", name)

		# Modifying planned_losses should be rejected
		doc.planned_losses = []
		with self.assertRaises(ValidationError):
			doc.save()

		# End shift so it does not leak into subsequent tests (e.g. conflict check)
		frappe.get_doc("Shift", name).end_shift()

	def test_document_locked_in_completed_state(self) -> None:
		name = self._expected_name("2026-02-18", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-18",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.start_shift()
		doc.end_shift()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so _validate_field_locking sees persisted status via get_value
		doc = frappe.get_doc("Shift", name)

		doc.shift_duration = "10"
		with self.assertRaises(ValidationError):
			doc.save()

	def test_document_locked_in_cancelled_state(self) -> None:
		name = self._expected_name("2026-02-19", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-19",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.cancel_shift()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so _validate_field_locking sees persisted status via get_value
		doc = frappe.get_doc("Shift", name)

		doc.supervisor = "Administrator"
		with self.assertRaises(ValidationError):
			doc.save()

	def test_planned_losses_auto_populate_8_hour_shift(self) -> None:
		name = self._expected_name("2026-02-11", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-11",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(len(doc.planned_losses), 2)

		tea, lunch = doc.planned_losses[0], doc.planned_losses[1]
		self.assertEqual(tea.downtime_reason, "Tea Break")
		self.assertEqual(tea.start_time, "10:00:00")
		self.assertEqual(tea.end_time, "10:15:00")

		self.assertEqual(lunch.downtime_reason, "Lunch Break")
		self.assertEqual(lunch.start_time, "12:00:00")
		self.assertEqual(lunch.end_time, "12:30:00")

	def test_planned_losses_auto_populate_10_hour_shift(self) -> None:
		name = self._expected_name("2026-02-12", "2")
		self._delete_shift_if_exists(name)
		# Clean up any stale Shift-1 on same date to prevent overlap
		self._delete_shift_if_exists(self._expected_name("2026-02-12", "1"))

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "10",
				"shift_date": "2026-02-12",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(len(doc.planned_losses), 3)

		tea1, lunch, tea2 = doc.planned_losses[0], doc.planned_losses[1], doc.planned_losses[2]
		self.assertEqual(tea1.downtime_reason, "Tea Break")
		self.assertEqual(tea1.start_time, "10:00:00")
		self.assertEqual(tea1.end_time, "10:15:00")

		self.assertEqual(lunch.downtime_reason, "Lunch Break")
		self.assertEqual(lunch.start_time, "12:00:00")
		self.assertEqual(lunch.end_time, "12:30:00")

		self.assertEqual(tea2.downtime_reason, "Tea Break")
		self.assertEqual(tea2.start_time, "14:00:00")
		self.assertEqual(tea2.end_time, "14:15:00")

	def test_planned_losses_auto_populate_12_hour_shift(self) -> None:
		name = self._expected_name("2026-02-13", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "12",
				"shift_date": "2026-02-13",
				"planned_start_time": "06:00:00",
			}
		).insert()

		self.assertEqual(len(doc.planned_losses), 3)

		tea1, lunch, tea2 = doc.planned_losses[0], doc.planned_losses[1], doc.planned_losses[2]
		self.assertEqual(tea1.start_time, "08:00:00")
		self.assertEqual(tea1.end_time, "08:15:00")
		self.assertEqual(lunch.start_time, "10:00:00")
		self.assertEqual(lunch.end_time, "10:30:00")
		self.assertEqual(tea2.start_time, "12:00:00")
		self.assertEqual(tea2.end_time, "12:15:00")

	def test_planned_losses_repopulate_when_shift_duration_changes(self) -> None:
		name = self._expected_name("2026-02-14", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-14",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(len(doc.planned_losses), 2)

		doc.shift_duration = "10"
		doc.save()

		self.assertEqual(len(doc.planned_losses), 3)
		self.assertEqual(doc.planned_losses[2].downtime_reason, "Tea Break")
		self.assertEqual(doc.planned_losses[2].start_time, "14:00:00")

	def test_status_cannot_be_changed_directly(self) -> None:
		name = self._expected_name("2026-02-10", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-10",
				"planned_start_time": "08:00:00",
			}
		).insert()

		doc.status = "Running"
		with self.assertRaises(ValidationError):
			doc.save()

	def test_overlap_validation_prevents_overlapping_shifts(self) -> None:
		"""Two shifts on same date with overlapping times must be rejected."""
		name1 = self._expected_name("2026-02-20", "1")
		name2 = self._expected_name("2026-02-20", "2")
		self._delete_shift_if_exists(name1)
		self._delete_shift_if_exists(name2)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-20",
				"planned_start_time": "08:00:00",
			}
		).insert()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so _validate_no_overlapping_shifts sees first shift when inserting second

		# Shift 2: 10:00-18:00 overlaps Shift 1: 08:00-16:00
		with self.assertRaises(ValidationError) as cm:
			frappe.get_doc(
				{
					"doctype": "Shift",
					"shift_label": "2",
					"shift_duration": "8",
					"shift_date": "2026-02-20",
					"planned_start_time": "10:00:00",
				}
			).insert()
		self.assertIn("overlap", str(cm.exception).lower())

	def test_non_overlapping_shifts_allowed(self) -> None:
		"""Shifts that do not overlap on the same date are allowed."""
		name1 = self._expected_name("2026-02-21", "1")
		name2 = self._expected_name("2026-02-21", "2")
		self._delete_shift_if_exists(name1)
		self._delete_shift_if_exists(name2)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-21",
				"planned_start_time": "08:00:00",
			}
		).insert()

		# Shift 2: 16:00-24:00 (midnight) - ends 00:00 next day, does not overlap 08:00-16:00
		doc2 = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-21",
				"planned_start_time": "16:00:00",
			}
		).insert()
		self.assertEqual(doc2.name, name2)

	def test_unique_shift_label_per_date_validation(self) -> None:
		"""Only one Shift 1 and one Shift 2 per date."""
		name = self._expected_name("2026-02-22", "1")
		self._delete_shift_if_exists(name)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-22",
				"planned_start_time": "08:00:00",
			}
		).insert()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so _validate_unique_shift_label_per_date sees first shift when inserting second

		# Second Shift 1 on same date must fail
		with self.assertRaises(ValidationError) as cm:
			frappe.get_doc(
				{
					"doctype": "Shift",
					"shift_label": "1",
					"shift_duration": "8",
					"shift_date": "2026-02-22",
					"planned_start_time": "18:00:00",
				}
			).insert()
		self.assertIn("shift", str(cm.exception).lower())
		self.assertIn("1", str(cm.exception))

	def test_same_shift_label_different_dates_allowed(self) -> None:
		"""Shift 1 on different dates is allowed."""
		name1 = self._expected_name("2026-02-23", "1")
		name2 = self._expected_name("2026-02-24", "1")
		self._delete_shift_if_exists(name1)
		self._delete_shift_if_exists(name2)

		doc1 = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-23",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc2 = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-24",
				"planned_start_time": "08:00:00",
			}
		).insert()
		self.assertEqual(doc1.name, name1)
		self.assertEqual(doc2.name, name2)

	def test_get_linked_downtime_entries_returns_overlapping_downtimes(self) -> None:
		"""get_linked_downtime_entries returns Downtime Entries whose time overlaps with the Shift."""
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			get_linked_downtime_entries,
		)

		workstation = frappe.get_all("Workstation", limit=1, pluck="name")
		employee = frappe.get_all("Employee", limit=1, pluck="name")
		if not workstation or not employee:
			raise unittest.SkipTest(
				"Workstation and Employee required for Downtime Entry; skipping linked downtimes test"
			)
		workstation, employee = workstation[0], employee[0]

		name = self._expected_name("2026-03-10", "1")
		self._delete_shift_if_exists(name)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-10",
				"planned_start_time": "08:00:00",
			}
		).insert()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so get_linked_downtime_entries sees shift

		# Downtime 10:00-11:00 overlaps with shift 08:00-16:00
		dt_overlap = frappe.get_doc(
			{
				"doctype": "Downtime Entry",
				"workstation": workstation,
				"operator": employee,
				"from_time": "2026-03-10 10:00:00",
				"to_time": "2026-03-10 11:00:00",
				"stop_reason": "Other",
			}
		).insert()
		# Downtime 18:00-19:00 does NOT overlap with shift 08:00-16:00
		dt_no_overlap = frappe.get_doc(
			{
				"doctype": "Downtime Entry",
				"workstation": workstation,
				"operator": employee,
				"from_time": "2026-03-10 18:00:00",
				"to_time": "2026-03-10 19:00:00",
				"stop_reason": "Other",
			}
		).insert()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

		result = get_linked_downtime_entries(name)
		names = [r["name"] for r in result]
		self.assertIn(dt_overlap.name, names)
		self.assertNotIn(dt_no_overlap.name, names)

		# Cleanup
		frappe.delete_doc("Downtime Entry", dt_overlap.name, force=True)
		frappe.delete_doc("Downtime Entry", dt_no_overlap.name, force=True)
		frappe.delete_doc("Shift", name, force=True)

	def test_update_shift_can_change_own_times_without_false_overlap(self) -> None:
		"""Updating a shift (e.g. duration) should not falsely overlap with itself."""
		name = self._expected_name("2026-02-25", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-25",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.shift_duration = "10"
		doc.save()
		doc.reload()
		self.assertEqual(doc.shift_duration, "10")

	def test_notification_created_on_shift_start(self) -> None:
		"""Notification Log is created when shift transitions to Running."""
		name = self._expected_name("2026-02-26", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-26",
				"planned_start_time": "08:00:00",
			}
		).insert()
		before_count = frappe.db.count("Notification Log", {"document_type": "Shift", "document_name": name})
		doc.start_shift()
		after_count = frappe.db.count("Notification Log", {"document_type": "Shift", "document_name": name})
		self.assertGreater(after_count, before_count)

	def test_notification_created_on_shift_end(self) -> None:
		"""Notification Log is created when shift transitions to Completed."""
		name = self._expected_name("2026-02-27", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-27",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.start_shift()
		before_count = frappe.db.count("Notification Log", {"document_type": "Shift", "document_name": name})
		doc.end_shift()
		after_count = frappe.db.count("Notification Log", {"document_type": "Shift", "document_name": name})
		self.assertGreater(after_count, before_count)

	def test_running_shift_conflict_detected(self) -> None:
		"""check_running_shift_conflict returns conflict when another shift is Running."""
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			check_running_shift_conflict,
		)

		name1 = self._expected_name("2026-02-28", "1")
		name2 = self._expected_name("2026-02-28", "2")
		self._delete_shift_if_exists(name1)
		self._delete_shift_if_exists(name2)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-28",
				"planned_start_time": "08:00:00",
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-28",
				"planned_start_time": "16:00:00",
			}
		).insert()

		# Start Shift 1
		doc1 = frappe.get_doc("Shift", name1)
		doc1.start_shift()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so check sees Running shift

		# Shift 2 (Draft) checking for conflict should find Shift 1 Running
		result = check_running_shift_conflict(name2)
		self.assertTrue(result.get("has_conflict"))
		self.assertIn(name1, [s["name"] for s in result.get("conflicting_shifts", [])])

		# End Shift 1 so it does not leak into subsequent tests
		frappe.get_doc("Shift", name1).end_shift()

	def test_start_shift_blocked_when_another_running(self) -> None:
		"""start_shift raises error when another shift is already Running."""
		name1 = self._expected_name("2026-02-28", "1")
		name2 = self._expected_name("2026-02-28", "2")
		self._delete_shift_if_exists(name1)
		self._delete_shift_if_exists(name2)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-28",
				"planned_start_time": "08:00:00",
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-28",
				"planned_start_time": "16:00:00",
			}
		).insert()

		# Start Shift 1
		doc1 = frappe.get_doc("Shift", name1)
		doc1.start_shift()

		# Trying to start Shift 2 should be blocked
		doc2 = frappe.get_doc("Shift", name2)
		with self.assertRaises(frappe.ValidationError):
			doc2.start_shift()

		# End Shift 1 so it does not leak
		frappe.get_doc("Shift", name1).end_shift()

	def test_no_running_shift_conflict_when_none_running(self) -> None:
		"""check_running_shift_conflict returns no conflict when no other shift is Running."""
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			check_running_shift_conflict,
		)

		# End any Running shifts from previous tests to ensure clean state
		for shift_name in frappe.get_all("Shift", filters={"status": "Running"}, pluck="name"):
			frappe.db.set_value("Shift", shift_name, "status", "Completed", update_modified=False)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so check_running_shift_conflict sees no Running shifts

		name = self._expected_name("2026-03-01", "1")
		self._delete_shift_if_exists(name)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-01",
				"planned_start_time": "08:00:00",
			}
		).insert()

		result = check_running_shift_conflict(name)
		self.assertFalse(result.get("has_conflict"))
		self.assertEqual(result.get("conflicting_shifts"), [])

	def test_branch_field_can_be_set(self) -> None:
		name = self._expected_name("2026-03-11", "1")
		self._delete_shift_if_exists(name)

		if not frappe.db.exists("Branch", "Test Branch"):
			frappe.get_doc({"doctype": "Branch", "branch": "Test Branch"}).insert(ignore_permissions=True)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-11",
				"planned_start_time": "08:00:00",
				"branch": "Test Branch",
			}
		).insert()
		self.assertEqual(doc.branch, "Test Branch")

	def test_branch_field_is_optional(self) -> None:
		name = self._expected_name("2026-03-12", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-12",
				"planned_start_time": "08:00:00",
			}
		).insert()
		self.assertFalse(doc.branch)

	def _expected_name(self, shift_date: str, shift_label: str) -> str:
		return f"SHIFT-{shift_date}.Shift-{shift_label}"

	def _delete_shift_if_exists(self, name: str) -> None:
		if frappe.db.exists("Shift", name):
			frappe.delete_doc("Shift", name, force=True, ignore_permissions=True)


def _ensure_user_with_role(email: str, role: str) -> None:
	"""Create or update user to have the given role."""
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = email.split("@", 1)[0]
		user.user_type = "System User"
	user.add_roles(role)
	user.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed for permission tests to see user roles


class TestShiftPermissions(FrappeTestCase):
	"""Verify role-based access control for Shift and Downtime Reason."""

	def setUp(self) -> None:
		super().setUp()
		_ensure_downtime_reasons()
		# Ensure Manufacturing User and Manufacturing Manager roles exist (ERPNext)
		if not frappe.db.exists("Role", "Manufacturing User"):
			frappe.get_doc({"doctype": "Role", "role_name": "Manufacturing User"}).insert(
				ignore_permissions=True
			)
		if not frappe.db.exists("Role", "Manufacturing Manager"):
			frappe.get_doc({"doctype": "Role", "role_name": "Manufacturing Manager"}).insert(
				ignore_permissions=True
			)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")

	def test_manufacturing_user_can_crud_shift(self) -> None:
		_ensure_user_with_role("test_shift_mfg_user@example.com", "Manufacturing User")
		frappe.set_user("test_shift_mfg_user@example.com")

		name = self._expected_name("2026-03-02", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-02",
				"planned_start_time": "08:00:00",
			}
		).insert()
		self.assertTrue(frappe.db.exists("Shift", doc.name))

		loaded = frappe.get_doc("Shift", doc.name)
		self.assertEqual(loaded.shift_label, "1")

		loaded.shift_duration = "10"
		loaded.save()

		frappe.delete_doc("Shift", doc.name)
		self.assertFalse(frappe.db.exists("Shift", doc.name))

	def test_manufacturing_manager_can_crud_shift(self) -> None:
		_ensure_user_with_role("test_shift_mfg_manager@example.com", "Manufacturing Manager")
		frappe.set_user("test_shift_mfg_manager@example.com")

		name = self._expected_name("2026-03-03", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-03-03",
				"planned_start_time": "08:00:00",
			}
		).insert()
		self.assertTrue(frappe.db.exists("Shift", doc.name))

		loaded = frappe.get_doc("Shift", doc.name)
		loaded.delete()
		self.assertFalse(frappe.db.exists("Shift", doc.name))

	def test_manufacturing_user_can_crud_downtime_reason(self) -> None:
		_ensure_user_with_role("test_shift_mfg_user@example.com", "Manufacturing User")
		frappe.set_user("test_shift_mfg_user@example.com")

		reason_name = f"Test Downtime Reason {frappe.generate_hash(length=6)}"
		if frappe.db.exists("Downtime Reason", reason_name):
			frappe.delete_doc("Downtime Reason", reason_name)

		doc = frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": reason_name}).insert()
		self.assertTrue(frappe.db.exists("Downtime Reason", doc.name))

		loaded = frappe.get_doc("Downtime Reason", doc.name)
		loaded.delete()
		self.assertFalse(frappe.db.exists("Downtime Reason", doc.name))

	def test_user_without_manufacturing_role_cannot_access_shift(self) -> None:
		"""User with only Blogger role must not have Shift permission."""
		_ensure_user_with_role("test_shift_blogger@example.com", "Blogger")
		user = frappe.get_doc("User", "test_shift_blogger@example.com")
		# Ensure user has only Blogger (remove Manufacturing roles if added elsewhere)
		roles = frappe.get_roles(user.name)
		for role in ("Manufacturing User", "Manufacturing Manager"):
			if role in roles:
				user.remove_roles(role)
				user.save(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		frappe.set_user("test_shift_blogger@example.com")

		self.assertFalse(
			frappe.has_permission("Shift", "read"),
			"User with only Blogger role must not have Shift read permission.",
		)

	def _expected_name(self, shift_date: str, shift_label: str) -> str:
		return f"SHIFT-{shift_date}.Shift-{shift_label}"

	def _delete_shift_if_exists(self, name: str) -> None:
		if frappe.db.exists("Shift", name):
			frappe.delete_doc("Shift", name, force=True, ignore_permissions=True)
