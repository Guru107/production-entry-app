from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


class TestReworkType(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def _delete_if_exists(self, name: str) -> None:
		if frappe.db.exists("Rework Type", name):
			frappe.delete_doc("Rework Type", name, force=True)

	def test_creation_uses_rework_type_name_and_defaults_active(self) -> None:
		name = "Test Rework Type Creation"
		self._delete_if_exists(name)

		doc = frappe.get_doc({"doctype": "Rework Type", "rework_type_name": name}).insert()

		self.assertEqual(doc.name, name)
		self.assertEqual(doc.is_active, 1)

	def test_is_active_filter_returns_only_active_rework_types(self) -> None:
		active_name = "Test Active Rework Type"
		inactive_name = "Test Inactive Rework Type"
		self._delete_if_exists(active_name)
		self._delete_if_exists(inactive_name)
		frappe.get_doc({"doctype": "Rework Type", "rework_type_name": active_name}).insert()
		frappe.get_doc(
			{
				"doctype": "Rework Type",
				"rework_type_name": inactive_name,
				"is_active": 0,
			}
		).insert()

		active_names = frappe.get_all(
			"Rework Type",
			filters={"is_active": 1, "name": ("in", [active_name, inactive_name])},
			pluck="name",
		)

		self.assertEqual(active_names, [active_name])

	def test_default_workstation_rejects_missing_link(self) -> None:
		with self.assertRaises(frappe.LinkValidationError):
			frappe.get_doc(
				{
					"doctype": "Rework Type",
					"rework_type_name": "Test Invalid Workstation Rework Type",
					"default_workstation": "Missing Workstation",
				}
			).insert()
