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

	def test_planned_losses_auto_populate_8_hour_shift(self) -> None:
		_ensure_loss_types()
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
		_ensure_loss_types()
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
		_ensure_loss_types()
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
		_ensure_loss_types()
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

	def _expected_name(self, shift_date: str, shift_label: str) -> str:
		return f"SHIFT-{shift_date}.Shift-{shift_label}"

	def _delete_shift_if_exists(self, name: str) -> None:
		if frappe.db.exists("Shift", name):
			frappe.delete_doc("Shift", name, force=True, ignore_permissions=True)
