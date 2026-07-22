from __future__ import annotations

import frappe
from frappe.exceptions import DuplicateEntryError, ValidationError
from frappe.tests.utils import FrappeTestCase


class TestOperator(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def _delete_if_exists(self, name: str) -> None:
		if frappe.db.exists("Operator", name):
			frappe.delete_doc("Operator", name, force=True)

	def test_mandatory_fields(self) -> None:
		doc = frappe.get_doc({"doctype": "Operator"})
		with self.assertRaises((ValidationError, frappe.MandatoryError)):
			doc.insert()

	def test_autoname_uses_operator_name(self) -> None:
		name = "Test Autoname Operator"
		self._delete_if_exists(name)

		doc = frappe.get_doc({"doctype": "Operator", "operator_name": name}).insert()
		self.assertEqual(doc.name, name)
		self._delete_if_exists(name)

	def test_is_active_defaults_to_true(self) -> None:
		name = "Active Default Operator"
		self._delete_if_exists(name)

		doc = frappe.get_doc({"doctype": "Operator", "operator_name": name}).insert()
		self.assertEqual(doc.is_active, 1)
		self._delete_if_exists(name)

	def test_bulk_import_is_enabled(self) -> None:
		self.assertEqual(frappe.get_meta("Operator").allow_import, 1)

	def test_duplicate_name_rejected(self) -> None:
		name = "Duplicate Operator Test"
		self._delete_if_exists(name)

		frappe.get_doc({"doctype": "Operator", "operator_name": name}).insert()

		with self.assertRaises((DuplicateEntryError, frappe.UniqueValidationError)):
			frappe.get_doc({"doctype": "Operator", "operator_name": name}).insert()
		self._delete_if_exists(name)
