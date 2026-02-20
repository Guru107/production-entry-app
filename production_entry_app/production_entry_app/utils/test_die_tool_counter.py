from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.die_tool_counter import (
	_ensure_counter_exists,
	_get_or_create_counter,
)


class TestDieToolCounterUtils(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_get_or_create_counter_returns_existing_by_name(self) -> None:
		expected = object()
		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.exists",
			return_value=True,
		):
			with patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.get_doc",
				return_value=expected,
			) as get_doc:
				result = _get_or_create_counter("DIE-001")

		self.assertIs(result, expected)
		get_doc.assert_called_once_with("Die Tool Counter", "DIE-001")

	def test_ensure_counter_exists_returns_inserted_name(self) -> None:
		inserted = frappe._dict(name="DIE-001")
		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.exists",
			return_value=False,
		):
			with patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.get_doc"
			) as get_doc:
				get_doc.return_value.insert.return_value = inserted
				result = _ensure_counter_exists("DIE-001")

		self.assertEqual(result, "DIE-001")

	def test_get_or_create_counter_handles_duplicate_insert_race(self) -> None:
		existing_doc = object()

		class _Doc:
			def insert(self, ignore_permissions=True):
				raise frappe.DuplicateEntryError("Die Tool Counter", "DIE-001")

		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.exists",
			side_effect=[False, True],
		):
			with patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.get_doc",
				side_effect=[_Doc(), existing_doc],
			):
				result = _get_or_create_counter("DIE-001")

		self.assertIs(result, existing_doc)

	def test_get_or_create_counter_falls_back_to_die_tool_item_lookup(self) -> None:
		existing_doc = object()

		class _Doc:
			def insert(self, ignore_permissions=True):
				raise frappe.DuplicateEntryError("Die Tool Counter", "DIE-001")

		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.exists",
			side_effect=[False, False],
		):
			with patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.get_value",
				return_value="DIE-001",
			):
				with patch(
					"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.get_doc",
					side_effect=[_Doc(), existing_doc],
				):
					result = _get_or_create_counter("DIE-001")

		self.assertIs(result, existing_doc)
