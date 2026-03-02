from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.die_tool_counter import (
	_ensure_counter_exists,
	_get_or_create_counter,
	is_die_tool_enabled,
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
		doc = MagicMock()
		doc.name = "DIE-001"
		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.exists",
			return_value=False,
		):
			with patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.get_doc"
			) as get_doc:
				get_doc.return_value = doc
				result = _ensure_counter_exists("DIE-001")

		self.assertEqual(result, "DIE-001")
		get_doc.return_value.insert.assert_called_once_with(ignore_permissions=True, ignore_if_duplicate=True)

	def test_get_or_create_counter_handles_duplicate_insert_race(self) -> None:
		existing_doc = object()

		class _Doc:
			name = "DIE-001"

			def insert(self, ignore_permissions=True, ignore_if_duplicate=False):
				return self

		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.exists",
			side_effect=[False, True, True],
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
			name = "DIE-001"

			def insert(self, ignore_permissions=True, ignore_if_duplicate=False):
				return self

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

	def test_is_die_tool_enabled_defaults_to_true_when_custom_field_absent(self) -> None:
		meta = frappe._dict(has_field=lambda fieldname: False)
		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.get_meta",
			return_value=meta,
		):
			self.assertTrue(is_die_tool_enabled("ITEM-001"))

	def test_is_die_tool_enabled_returns_false_when_item_opted_out(self) -> None:
		meta = frappe._dict(has_field=lambda fieldname: True)
		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.get_meta",
			return_value=meta,
		):
			with patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.get_value",
				return_value=0,
			):
				self.assertFalse(is_die_tool_enabled("ITEM-001"))
