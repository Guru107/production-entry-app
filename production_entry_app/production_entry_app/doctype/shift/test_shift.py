from __future__ import annotations

import datetime

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase


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
