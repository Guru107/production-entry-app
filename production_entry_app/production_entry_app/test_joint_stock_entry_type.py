from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

import frappe

from production_entry_app.production_entry_app import api
from production_entry_app.production_entry_app.joint_production import JOINT_LH_RH_STOCK_ENTRY_TYPE


class TestJointStockEntryTypeResolver(TestCase):
	def test_configured_joint_repack_type_is_resolved(self) -> None:
		with patch.object(api.frappe, "get_list", return_value=[JOINT_LH_RH_STOCK_ENTRY_TYPE]):
			self.assertEqual(api.get_joint_stock_entry_type(), JOINT_LH_RH_STOCK_ENTRY_TYPE)

	def test_multiple_joint_stock_entry_types_are_rejected(self) -> None:
		with (
			patch.object(api.frappe, "get_list", return_value=[JOINT_LH_RH_STOCK_ENTRY_TYPE, "Other Joint"]),
			self.assertRaisesRegex(frappe.ValidationError, "Only one Stock Entry Type"),
		):
			api.get_joint_stock_entry_type()

	def test_missing_joint_stock_entry_type_has_clear_error_when_required(self) -> None:
		with (
			patch.object(api.frappe, "get_list", return_value=[]),
			self.assertRaisesRegex(frappe.ValidationError, "Configure a Repack Stock Entry Type"),
		):
			api.get_joint_stock_entry_type()

	def test_passive_joint_stock_entry_type_discovery_allows_missing_configuration(self) -> None:
		with patch.object(api.frappe, "get_list", return_value=[]):
			self.assertEqual(api.get_joint_stock_entry_type(required="0"), "")

	def test_joint_stock_entry_type_requires_stock_entry_create_permission(self) -> None:
		with (
			patch.object(api.frappe, "has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			api.get_joint_stock_entry_type(required="0")
