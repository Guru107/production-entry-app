from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.overrides.downtime_entry_hooks import (
	validate_downtime_entry,
)
from production_entry_app.production_entry_app.utils.downtime_reason_seed import ensure_downtime_reason


def _ensure_downtime_reason_custom_field() -> None:
	if frappe.db.exists("Custom Field", "Downtime Entry-custom_pea_downtime_reason"):
		return
	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"name": "Downtime Entry-custom_pea_downtime_reason",
			"dt": "Downtime Entry",
			"fieldname": "custom_pea_downtime_reason",
			"fieldtype": "Link",
			"label": "Downtime Reason",
			"options": "Downtime Reason",
			"insert_after": "stop_reason",
			"reqd": 1,
			"module": "Production Entry App",
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Downtime Entry")


class TestDowntimeEntryHooks(FrappeTestCase):
	def setUp(self) -> None:
		_ensure_downtime_reason_custom_field()
		ensure_downtime_reason("00", "Other")
		ensure_downtime_reason("05", "Maintenance")

	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_from_time_must_be_before_to_time(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Downtime Entry",
				"workstation": "Hook Workstation",
				"operator": "HR-EMP-00001",
				"from_time": "2026-10-01 10:30:00",
				"to_time": "2026-10-01 10:00:00",
				"custom_pea_downtime_reason": "00",
				"stop_reason": "Other",
			}
		)

		with self.assertRaisesRegex(frappe.ValidationError, "From Time must be before To Time"):
			validate_downtime_entry(doc)

	def test_equal_from_and_to_time_is_rejected(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Downtime Entry",
				"workstation": "Hook Workstation",
				"operator": "HR-EMP-00001",
				"from_time": "2026-10-01 10:00:00",
				"to_time": "2026-10-01 10:00:00",
				"custom_pea_downtime_reason": "00",
				"stop_reason": "Other",
			}
		)

		with self.assertRaisesRegex(frappe.ValidationError, "From Time must be before To Time"):
			validate_downtime_entry(doc)

	def test_downtime_reason_link_is_required(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Downtime Entry",
				"workstation": "Hook Workstation",
				"operator": "HR-EMP-00001",
				"from_time": "2026-10-01 10:00:00",
				"to_time": "2026-10-01 10:30:00",
				"stop_reason": "Other",
			}
		)

		with self.assertRaisesRegex(frappe.ValidationError, "Downtime Reason is required"):
			validate_downtime_entry(doc)

	def test_valid_downtime_entry_passes_validation(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Downtime Entry",
				"workstation": "Hook Workstation",
				"operator": "HR-EMP-00001",
				"from_time": "2026-10-01 10:00:00",
				"to_time": "2026-10-01 10:30:00",
				"custom_pea_downtime_reason": "05",
				"stop_reason": "Other",
			}
		)

		validate_downtime_entry(doc)

	def test_reason_labels_use_downtime_reason_descriptions(self) -> None:
		from production_entry_app.production_entry_app.overrides.downtime_entry_hooks import (
			get_downtime_reason_labels,
		)

		labels = get_downtime_reason_labels(["00", "05", None, ""])
		self.assertEqual(labels["00"], "Other")
		self.assertEqual(labels["05"], "Maintenance")
