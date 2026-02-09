from __future__ import annotations

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase


class TestDowntimeReason(FrappeTestCase):
	def test_mandatory_fields(self) -> None:
		doc = frappe.get_doc({"doctype": "Downtime Reason"})
		with self.assertRaises((ValidationError, frappe.MandatoryError)):
			doc.insert()

	def test_autoname_uses_downtime_reason_name(self) -> None:
		name = "Test Autoname Reason"
		if frappe.db.exists("Downtime Reason", name):
			frappe.delete_doc("Downtime Reason", name, force=True)

		doc = frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert()
		self.assertEqual(doc.name, name)

		frappe.delete_doc("Downtime Reason", name, force=True)

	def test_duplicate_name_rejected(self) -> None:
		name = "Duplicate Reason Test"
		if frappe.db.exists("Downtime Reason", name):
			frappe.delete_doc("Downtime Reason", name, force=True)

		frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so duplicate check sees first record

		with self.assertRaises(Exception):
			frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert()

		frappe.delete_doc("Downtime Reason", name, force=True)
