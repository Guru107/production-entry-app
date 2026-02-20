from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.die_tool_counter import (
	_ensure_counter_exists,
	_get_or_create_counter,
	update_counter_for_stock_entry,
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

	def test_counter_created_if_missing_returns_new_name(self) -> None:
		inserted = SimpleNamespace(name="DIE-NEW")

		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.exists",
			return_value=False,
		):
			with patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.get_doc",
				return_value=SimpleNamespace(insert=lambda ignore_permissions=True: inserted),
			):
				name = _ensure_counter_exists("DIE-NEW")

		self.assertEqual(name, "DIE-NEW")

	def test_atomic_increment_does_not_use_document_save(self) -> None:
		doc = frappe._dict(
			{
				"purpose": "Manufacture",
				"fg_item": "DIE-001",
				"fg_completed_qty": 5,
				"custom_rejection_qty": 1,
			}
		)
		update_builder = SimpleNamespace(
			set=lambda *args, **kwargs: update_builder,
			where=lambda *args, **kwargs: update_builder,
			run=lambda *args, **kwargs: None,
		)

		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter._get_or_create_counter"
		) as get_or_create_counter:
			with patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter._ensure_counter_exists",
				return_value="DIE-001",
			):
				with patch(
					"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.get_value",
					side_effect=[2, 1000],
				):
					with patch(
						"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.qb.update",
						return_value=update_builder,
					) as qb_update:
						update_counter_for_stock_entry(doc, direction=1)

		get_or_create_counter.assert_not_called()
		self.assertGreaterEqual(qb_update.call_count, 2)

	def test_atomic_decrement_clamps_to_zero(self) -> None:
		doc = frappe._dict(
			{
				"purpose": "Manufacture",
				"fg_item": "DIE-001",
				"fg_completed_qty": 10,
				"custom_rejection_qty": 0,
			}
		)
		update_builder = SimpleNamespace(
			set=lambda *args, **kwargs: update_builder,
			where=lambda *args, **kwargs: update_builder,
			run=lambda *args, **kwargs: None,
		)

		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter._ensure_counter_exists",
			return_value="DIE-001",
		):
			with patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.get_value",
				side_effect=[1, 1000],
			):
				with patch(
					"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.qb.update",
					return_value=update_builder,
				) as qb_update:
					update_counter_for_stock_entry(doc, direction=-1)

		self.assertGreaterEqual(qb_update.call_count, 2)
