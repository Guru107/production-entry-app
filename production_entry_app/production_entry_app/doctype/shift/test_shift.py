from __future__ import annotations

import datetime

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase


def _ensure_loss_types() -> None:
	"""Ensure Tea Break and Lunch Break Loss Types exist (for planned losses tests)."""
	for name in ("Tea Break", "Lunch Break"):
		if not frappe.db.exists("Loss Type", name):
			frappe.get_doc({"doctype": "Loss Type", "loss_type_name": name}).insert()


class TestShift(FrappeTestCase):
	def setUp(self) -> None:
		super().setUp()
		_ensure_loss_types()

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
		expected_name = self._expected_name("2026-02-05", "2")
		self._delete_shift_if_exists(expected_name)
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-05",
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
		self.assertEqual(tea.loss_type, "Tea Break")
		self.assertEqual(tea.start_time, "10:00:00")
		self.assertEqual(tea.end_time, "10:15:00")

		self.assertEqual(lunch.loss_type, "Lunch Break")
		self.assertEqual(lunch.start_time, "12:00:00")
		self.assertEqual(lunch.end_time, "12:30:00")

	def test_planned_losses_auto_populate_10_hour_shift(self) -> None:
		name = self._expected_name("2026-02-12", "2")
		self._delete_shift_if_exists(name)

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
		self.assertEqual(tea1.loss_type, "Tea Break")
		self.assertEqual(tea1.start_time, "10:00:00")
		self.assertEqual(tea1.end_time, "10:15:00")

		self.assertEqual(lunch.loss_type, "Lunch Break")
		self.assertEqual(lunch.start_time, "12:00:00")
		self.assertEqual(lunch.end_time, "12:30:00")

		self.assertEqual(tea2.loss_type, "Tea Break")
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
		self.assertEqual(doc.planned_losses[2].loss_type, "Tea Break")
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

	def test_no_running_shift_conflict_when_none_running(self) -> None:
		"""check_running_shift_conflict returns no conflict when no other shift is Running."""
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			check_running_shift_conflict,
		)

		# End any Running shifts from previous tests to ensure clean state
		for shift_name in frappe.get_all("Shift", filters={"status": "Running"}, pluck="name"):
			try:
				frappe.get_doc("Shift", shift_name).end_shift()
			except Exception:
				pass

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

	def _expected_name(self, shift_date: str, shift_label: str) -> str:
		return f"SHIFT-{shift_date}.Shift-{shift_label}"

	def _delete_shift_if_exists(self, name: str) -> None:
		if frappe.db.exists("Shift", name):
			frappe.delete_doc("Shift", name, force=True, ignore_permissions=True)
