from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import api


class TestReworkStockEntryType(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_configured_rework_material_transfer_type_is_resolved(self) -> None:
		expected = f"Rework Material Transfer {frappe.generate_hash(length=6)}"
		with patch.object(api.frappe, "get_list", return_value=[expected]):
			self.assertEqual(api.get_rework_stock_entry_type(), expected)

	def test_rework_stock_entry_type_requires_material_transfer_purpose(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": f"Invalid Rework {frappe.generate_hash(length=6)}",
				"purpose": "Repack",
				"custom_pea_rework_entry": 1,
			}
		)

		with self.assertRaisesRegex(frappe.ValidationError, "must use Material Transfer purpose"):
			doc.insert(ignore_permissions=True)

	def test_multiple_rework_stock_entry_types_are_rejected(self) -> None:
		with (
			patch.object(api.frappe, "get_list", return_value=["Rework A", "Rework B"]),
			self.assertRaisesRegex(frappe.ValidationError, "Only one.*Rework"),
		):
			api.get_rework_stock_entry_type()

	def test_missing_rework_stock_entry_type_has_clear_error(self) -> None:
		with (
			patch.object(api.frappe, "get_list", return_value=[]),
			self.assertRaisesRegex(frappe.ValidationError, "Configure a Material Transfer.*Rework"),
		):
			api.get_rework_stock_entry_type()

	def test_passive_rework_stock_entry_type_discovery_allows_missing_configuration(self) -> None:
		with patch.object(api.frappe, "get_list", return_value=[]):
			self.assertEqual(api.get_rework_stock_entry_type(required="0"), "")

	def test_passive_rework_stock_entry_type_discovery_allows_ambiguous_configuration(self) -> None:
		with patch.object(api.frappe, "get_list", return_value=["Rework A", "Rework B"]):
			self.assertEqual(api.get_rework_stock_entry_type(required="0"), "")

	def test_selected_rework_stock_entry_type_is_identified_independently(self) -> None:
		with patch.object(
			api.frappe.db,
			"get_value",
			return_value=frappe._dict(purpose="Material Transfer", custom_pea_rework_entry=1),
		):
			self.assertEqual(
				api.get_rework_stock_entry_type(stock_entry_type="Rework A", required="0"),
				"Rework A",
			)

	def test_selected_non_rework_stock_entry_type_returns_blank(self) -> None:
		for selected_type in (
			frappe._dict(purpose="Material Transfer", custom_pea_rework_entry=0),
			frappe._dict(purpose="Repack", custom_pea_rework_entry=1),
			None,
		):
			with (
				self.subTest(selected_type=selected_type),
				patch.object(api.frappe.db, "get_value", return_value=selected_type),
			):
				self.assertEqual(
					api.get_rework_stock_entry_type(stock_entry_type="Selected Type", required="0"),
					"",
				)

	def test_blank_selected_stock_entry_type_returns_without_a_lookup(self) -> None:
		with patch.object(api.frappe.db, "get_value") as get_value:
			self.assertEqual(api.get_rework_stock_entry_type(stock_entry_type="", required="0"), "")
		get_value.assert_not_called()

	def test_selected_rework_stock_entry_type_requires_read_permission(self) -> None:
		def has_permission(doctype: str, ptype: str, doc: str | None = None) -> bool:
			return doctype == "Stock Entry" and ptype == "create" and doc is None

		with (
			patch.object(api.frappe, "has_permission", side_effect=has_permission),
			patch.object(api.frappe.db, "get_value") as get_value,
			self.assertRaises(frappe.PermissionError),
		):
			api.get_rework_stock_entry_type(stock_entry_type="Rework A", required=0)
		get_value.assert_not_called()

	def test_stock_entry_type_cannot_be_joint_and_rework(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": f"Joint Rework {frappe.generate_hash(length=6)}",
				"purpose": "Material Transfer",
				"custom_pea_joint_lh_rh_production": 1,
				"custom_pea_rework_entry": 1,
			}
		)

		with self.assertRaisesRegex(frappe.ValidationError, "cannot be both.*Joint LH/RH.*Rework"):
			doc.insert(ignore_permissions=True)

	def test_rework_stock_entry_type_resolution_requires_stock_entry_create_permission(self) -> None:
		with patch.object(api.frappe, "has_permission", return_value=False):
			for required in (1, 0):
				with self.subTest(required=required), self.assertRaises(frappe.PermissionError):
					api.get_rework_stock_entry_type(required=required)
			with self.assertRaises(frappe.PermissionError):
				api.get_rework_stock_entry_type(stock_entry_type="Rework A", required=0)
