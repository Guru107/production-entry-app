from __future__ import annotations

import frappe
from frappe.exceptions import DuplicateEntryError, ValidationError
from frappe.tests.utils import FrappeTestCase


class TestDowntimeReason(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def _delete_if_exists(self, name: str) -> None:
		if frappe.db.exists("Downtime Reason", name):
			frappe.delete_doc("Downtime Reason", name, force=True)

	def test_mandatory_fields(self) -> None:
		doc = frappe.get_doc({"doctype": "Downtime Reason"})
		with self.assertRaises((ValidationError, frappe.MandatoryError)):
			doc.insert()

	def test_autoname_uses_downtime_reason_name(self) -> None:
		name = "Test Autoname Reason"
		self._delete_if_exists(name)

		doc = frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert()
		self.assertEqual(doc.name, name)
		self._delete_if_exists(name)

	def test_duplicate_name_rejected(self) -> None:
		name = "Duplicate Reason Test"
		self._delete_if_exists(name)

		frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert()

		with self.assertRaises((DuplicateEntryError, frappe.UniqueValidationError)):
			frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert()
		self._delete_if_exists(name)
