from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.joint_production import JOINT_PRODUCTION_STOCK_ENTRY_TYPE
from production_entry_app.production_entry_app.utils.die_tool_counter import (
	_ensure_counter_exists,
	_get_or_create_counter,
	get_counter_health,
	get_counter_snapshot,
	is_die_tool_enabled,
	resolve_die_tool_item_code,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	ensure_production_owned_joint_metadata,
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

	def test_get_counter_snapshot_returns_existing_row(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.exists",
			side_effect=[True, True],
		):
			with patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.get_value",
				return_value=frappe._dict(
					name="DIE-001",
					current_stroke_count=100,
					stroke_capacity=1000,
					warning_threshold_pct=90,
				),
			) as get_value:
				row = get_counter_snapshot("DIE-001")

		self.assertEqual(row.get("name"), "DIE-001")
		self.assertEqual(get_value.call_count, 1)

	def test_get_counter_snapshot_retries_and_returns_none_when_missing(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.exists",
			side_effect=[True, True],
		):
			with patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.get_value",
				return_value=None,
			):
				row = get_counter_snapshot("DIE-001")

		self.assertIsNone(row)

	def test_get_counter_snapshot_does_not_create_missing_counter(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.exists",
				return_value=True,
			),
			patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter.frappe.db.get_value",
				return_value=None,
			),
			patch(
				"production_entry_app.production_entry_app.utils.die_tool_counter._ensure_counter_exists"
			) as ensure_counter,
		):
			row = get_counter_snapshot("DIE-001", retries=0)

		self.assertIsNone(row)
		ensure_counter.assert_not_called()

	def test_get_counter_health_uses_exact_utilization_for_threshold_check(self) -> None:
		utilization_pct, is_maintenance_due = get_counter_health(
			current_strokes=1,
			stroke_capacity=3,
			warning_threshold_pct=33.3333,
		)

		self.assertAlmostEqual(utilization_pct, 33.3333333333, places=6)
		self.assertEqual(is_maintenance_due, 1)


class TestResolveDieToolItemCode(FrappeTestCase):
	def setUp(self) -> None:
		ensure_production_owned_joint_metadata()

	def test_joint_production_prefers_stock_entry_die_tool_item(self) -> None:
		doc = frappe._dict(
			purpose="Repack",
			stock_entry_type=JOINT_PRODUCTION_STOCK_ENTRY_TYPE,
			custom_pea_die_tool_item="DIE-JOINT",
			custom_pea_joint_production_lines=[{"bom_no": "BOM-1"}],
		)
		self.assertEqual(resolve_die_tool_item_code(doc), "DIE-JOINT")

	def test_manufacture_prefers_stock_entry_die_tool_item_over_fg(self) -> None:
		doc = frappe._dict(
			purpose="Manufacture",
			fg_item="FG-1",
			custom_pea_die_tool_item="DIE-MFG",
		)
		self.assertEqual(resolve_die_tool_item_code(doc), "DIE-MFG")

	def test_manufacture_falls_back_to_finished_item(self) -> None:
		doc = frappe._dict(purpose="Manufacture", fg_item="FG-1")
		self.assertEqual(resolve_die_tool_item_code(doc), "FG-1")
