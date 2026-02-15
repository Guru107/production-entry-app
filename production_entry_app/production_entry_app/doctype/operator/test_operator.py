from __future__ import annotations

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase


class TestOperator(FrappeTestCase):
	def test_mandatory_fields(self) -> None:
		doc = frappe.get_doc({"doctype": "Operator"})
		with self.assertRaises((ValidationError, frappe.MandatoryError)):
			doc.insert()

	def test_autoname_uses_operator_name(self) -> None:
		name = "Test Autoname Operator"
		if frappe.db.exists("Operator", name):
			frappe.delete_doc("Operator", name, force=True)

		doc = frappe.get_doc({"doctype": "Operator", "operator_name": name}).insert()
		self.assertEqual(doc.name, name)

		frappe.delete_doc("Operator", name, force=True)

	def test_is_active_defaults_to_true(self) -> None:
		name = "Active Default Operator"
		if frappe.db.exists("Operator", name):
			frappe.delete_doc("Operator", name, force=True)

		doc = frappe.get_doc({"doctype": "Operator", "operator_name": name}).insert()
		self.assertEqual(doc.is_active, 1)

		frappe.delete_doc("Operator", name, force=True)

	def test_duplicate_name_rejected(self) -> None:
		name = "Duplicate Operator Test"
		if frappe.db.exists("Operator", name):
			frappe.delete_doc("Operator", name, force=True)

		frappe.get_doc({"doctype": "Operator", "operator_name": name}).insert()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so duplicate check sees first record

		with self.assertRaises(Exception):
			frappe.get_doc({"doctype": "Operator", "operator_name": name}).insert()

		frappe.delete_doc("Operator", name, force=True)
