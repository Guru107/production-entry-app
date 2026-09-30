from __future__ import annotations

import frappe
from frappe.exceptions import DuplicateEntryError
from frappe.tests.utils import FrappeTestCase


class TestDowntimeReason(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	@staticmethod
	def _delete_if_exists(code: str) -> None:
		if frappe.db.exists("Downtime Reason", code):
			frappe.delete_doc("Downtime Reason", code, force=True)

	def test_mandatory_fields(self) -> None:
		doc = frappe.get_doc({"doctype": "Downtime Reason"})
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_code_is_mandatory(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Downtime Reason", "description": "No Code Reason"}).insert()

	def test_description_is_mandatory(self) -> None:
		with self.assertRaises(frappe.MandatoryError):
			frappe.get_doc({"doctype": "Downtime Reason", "code": "95"}).insert()

	def test_code_must_be_two_digit_number(self) -> None:
		for bad_code in ("1", "123", "1a", "ab", "-1"):
			with self.subTest(code=bad_code):
				with self.assertRaises(frappe.ValidationError):
					frappe.get_doc(
						{"doctype": "Downtime Reason", "code": bad_code, "description": "Bad Format"}
					).insert()

	def test_autoname_uses_code(self) -> None:
		doc = frappe.get_doc(
			{"doctype": "Downtime Reason", "code": "95", "description": "Test Autoname Reason"}
		).insert()
		self.assertEqual(doc.name, "95")
		self._delete_if_exists("95")

	def test_duplicate_code_rejected(self) -> None:
		frappe.get_doc({"doctype": "Downtime Reason", "code": "95", "description": "First"}).insert()
		with self.assertRaises((DuplicateEntryError, frappe.UniqueValidationError)):
			frappe.get_doc({"doctype": "Downtime Reason", "code": "95", "description": "Second"}).insert()
		self._delete_if_exists("95")

	def test_description_editable_without_changing_identity(self) -> None:
		doc = frappe.get_doc({"doctype": "Downtime Reason", "code": "95", "description": "Alpha"}).insert()
		doc.description = "Beta"
		doc.save()
		doc.reload()
		self.assertEqual(doc.name, "95")
		self.assertEqual(doc.description, "Beta")
		self._delete_if_exists("95")

	def test_search_matches_code_and_description_and_displays_description(self) -> None:
		meta = frappe.get_meta("Downtime Reason", cached=False)
		self.assertEqual(meta.title_field, "description")
		self.assertTrue(meta.show_title_field_in_link)
		search_fields = {field.strip() for field in (meta.search_fields or "").split(",") if field.strip()}
		self.assertIn("code", search_fields)
		self.assertIn("description", search_fields)

	def test_is_active_defaults_on(self) -> None:
		doc = frappe.get_doc(
			{"doctype": "Downtime Reason", "code": "96", "description": "Active Check"}
		).insert()
		self.assertEqual(doc.is_active, 1)
		self._delete_if_exists("96")
