from __future__ import annotations

import frappe
from frappe.exceptions import MandatoryError, ValidationError
from frappe.tests.utils import FrappeTestCase


class TestLossType(FrappeTestCase):
	def test_mandatory_fields(self) -> None:
		# `loss_type_name` is required for autoname; Frappe raises ValidationError during naming.
		with self.assertRaises(ValidationError):
			frappe.get_doc({"doctype": "Loss Type"}).insert()

		with self.assertRaises(MandatoryError):
			frappe.get_doc({"doctype": "Loss Type", "loss_type_name": self._unique_loss_type_name()}).insert()

	def test_default_duration_must_be_positive(self) -> None:
		with self.assertRaises(ValidationError):
			frappe.get_doc(
				{
					"doctype": "Loss Type",
					"loss_type_name": self._unique_loss_type_name(),
					"default_duration": -1,
				}
			).insert()

		with self.assertRaises(ValidationError):
			frappe.get_doc(
				{
					"doctype": "Loss Type",
					"loss_type_name": self._unique_loss_type_name(),
					"default_duration": 0,
				}
			).insert()

	def test_autoname_uses_loss_type_name(self) -> None:
		loss_type_name = self._unique_loss_type_name()
		doc = frappe.get_doc(
			{"doctype": "Loss Type", "loss_type_name": loss_type_name, "default_duration": 15}
		).insert()

		self.assertEqual(doc.name, loss_type_name)

	def _unique_loss_type_name(self) -> str:
		return f"Test Loss Type {frappe.generate_hash(length=8)}"
