from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
	_sync_item_branches_from_header,
	validate_stock_entry,
)


class _MetaWithFields:
	def __init__(self, fields: set[str]) -> None:
		self.fields = fields

	def has_field(self, fieldname: str) -> bool:
		return fieldname in self.fields


class TestReworkStockEntryFields(FrappeTestCase):
	def setUp(self) -> None:
		suffix = frappe.generate_hash(length=6)
		self.rework_stock_entry_type = f"Rework Material Transfer {suffix}"
		self.normal_stock_entry_type = f"Normal Material Transfer {suffix}"
		self.active_operator = f"Active Rework Operator {suffix}"
		self.inactive_operator = f"Inactive Rework Operator {suffix}"
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": self.rework_stock_entry_type,
				"purpose": "Material Transfer",
				"custom_pea_rework_entry": 1,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": self.normal_stock_entry_type,
				"purpose": "Material Transfer",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Operator", "operator_name": self.active_operator, "is_active": 1}).insert(
			ignore_permissions=True
		)
		frappe.get_doc(
			{"doctype": "Operator", "operator_name": self.inactive_operator, "is_active": 0}
		).insert(ignore_permissions=True)

	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_rework_actual_end_must_be_later_than_start(self) -> None:
		doc = self._make_rework_entry()
		doc.custom_pea_rework_actual_end = doc.custom_pea_rework_actual_start

		with self.assertRaisesRegex(frappe.ValidationError, "Rework Actual End must be after"):
			validate_stock_entry(doc)

	def test_rework_requires_at_least_one_operator(self) -> None:
		doc = self._make_rework_entry()

		with self.assertRaisesRegex(frappe.ValidationError, "at least one active Operator"):
			validate_stock_entry(doc)

	def test_rework_rejects_inactive_operators(self) -> None:
		doc = self._make_rework_entry()
		doc.append("custom_pea_rework_operators", {"operator": self.inactive_operator})

		with self.assertRaisesRegex(frappe.ValidationError, "Inactive Rework Operator.*is inactive"):
			validate_stock_entry(doc)

	def test_rework_requires_rework_type(self) -> None:
		doc = self._make_rework_entry()
		doc.custom_pea_rework_type = None
		doc.append("custom_pea_rework_operators", {"operator": self.active_operator})

		with self.assertRaisesRegex(frappe.ValidationError, "Rework Type is required"):
			validate_stock_entry(doc)

	def test_rework_requires_workstation(self) -> None:
		doc = self._make_rework_entry()
		doc.custom_pea_rework_workstation = None
		doc.append("custom_pea_rework_operators", {"operator": self.active_operator})

		with self.assertRaisesRegex(frappe.ValidationError, "Rework Workstation is required"):
			validate_stock_entry(doc)

	def test_non_rework_entries_reject_all_rework_owned_fields(self) -> None:
		values = {
			"custom_pea_rework_type": "Deburring",
			"custom_pea_rework_workstation": "Rework Workstation",
			"custom_pea_rework_actual_start": "2026-09-01 08:00:00",
			"custom_pea_rework_actual_end": "2026-09-01 09:00:00",
			"custom_pea_rework_cost": 50,
		}
		for fieldname, value in values.items():
			with self.subTest(fieldname=fieldname):
				doc = frappe.new_doc("Stock Entry")
				doc.purpose = "Material Transfer"
				doc.stock_entry_type = self.normal_stock_entry_type
				doc.set(fieldname, value)
				with self.assertRaisesRegex(frappe.ValidationError, "Rework fields can only be used"):
					validate_stock_entry(doc)

		doc = frappe.new_doc("Stock Entry")
		doc.purpose = "Material Transfer"
		doc.stock_entry_type = self.normal_stock_entry_type
		doc.append("custom_pea_rework_operators", {"operator": self.active_operator})
		with self.assertRaisesRegex(frappe.ValidationError, "Rework fields can only be used"):
			validate_stock_entry(doc)

	def test_active_operator_with_valid_rework_times_passes_validation(self) -> None:
		doc = self._make_rework_entry()
		doc.append("custom_pea_rework_operators", {"operator": self.active_operator})

		validate_stock_entry(doc)

	def test_item_branch_is_synced_from_stock_entry_branch(self) -> None:
		doc = self._make_rework_entry()
		doc.branch = "Nashik"
		doc.append("custom_pea_rework_operators", {"operator": self.active_operator})
		doc.append("items", {"item_code": "FG001SHR", "branch": "_Test Branch"})

		validate_stock_entry(doc)

		self.assertEqual(doc.get("items")[0].branch, "Nashik")

	def test_non_rework_item_branch_is_synced_from_stock_entry_branch(self) -> None:
		doc = frappe.new_doc("Stock Entry")
		doc.purpose = "Material Transfer"
		doc.stock_entry_type = self.normal_stock_entry_type
		doc.branch = "Nashik"
		doc.append("items", {"item_code": "FG001SHR", "branch": "_Test Branch"})

		validate_stock_entry(doc)

		self.assertEqual(doc.get("items")[0].branch, "Nashik")

	def test_item_branch_sync_handles_stale_stock_entry_detail_meta(self) -> None:
		doc = frappe._dict(
			{
				"branch": "Nashik",
				"items": [frappe._dict({"item_code": "FG001SHR", "branch": None})],
			}
		)

		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.get_meta",
			side_effect=[_MetaWithFields({"branch"}), _MetaWithFields(set())],
		):
			_sync_item_branches_from_header(doc)

		self.assertEqual(doc.get("items")[0].branch, "Nashik")

	def test_non_rework_entry_without_rework_fields_passes_validation(self) -> None:
		doc = frappe.new_doc("Stock Entry")
		doc.purpose = "Material Transfer"
		doc.stock_entry_type = self.normal_stock_entry_type

		validate_stock_entry(doc)

	def _make_rework_entry(self) -> Document:
		doc = frappe.new_doc("Stock Entry")
		doc.purpose = "Material Transfer"
		doc.stock_entry_type = self.rework_stock_entry_type
		doc.custom_pea_rework_type = "Deburring"
		doc.custom_pea_rework_workstation = "Rework Workstation"
		doc.custom_pea_rework_actual_start = "2026-09-01 08:00:00"
		doc.custom_pea_rework_actual_end = "2026-09-01 09:00:00"
		return doc
