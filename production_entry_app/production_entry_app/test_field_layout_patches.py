from __future__ import annotations

import json
from types import ModuleType
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.patches import (
	relocate_joint_fetch_and_rejection,
	relocate_joint_fetch_items,
	remove_legacy_rework_reports,
	rename_rejection_breakup_item_code,
	reorder_manufacture_press_fields,
	reorder_manufacture_press_fields_v2,
	sync_manufacture_press_field_layout,
)

PRESS_FIELDS = ("custom_pea_total_strokes", "custom_pea_die_tool_item", "custom_pea_unplanned_losses_section")
FIELD_ORDER_FILTERS = {"doc_type": "Stock Entry", "property": "field_order", "doctype_or_field": "DocType"}


def _freeze_field_order(field_order: list[str]) -> None:
	"""Replace any Stock Entry field_order Property Setter; the test rollback restores it."""
	frappe.db.delete("Property Setter", FIELD_ORDER_FILTERS)
	frappe.get_doc(
		{
			"doctype": "Property Setter",
			**FIELD_ORDER_FILTERS,
			"property_type": "Data",
			"value": json.dumps(field_order),
		}
	).insert(ignore_permissions=True)


def _frozen_field_order() -> list[str]:
	return json.loads(frappe.db.get_value("Property Setter", FIELD_ORDER_FILTERS, "value"))


class TestFieldOrderPatches(FrappeTestCase):
	def _assert_result_and_idempotent(self, patch_module: ModuleType, expected: list[str]) -> None:
		patch_module.execute()
		self.assertEqual(_frozen_field_order(), expected)
		patch_module.execute()
		self.assertEqual(_frozen_field_order(), expected)

	def test_relocate_joint_fetch_items_moves_fetch_and_drops_resources_section(self) -> None:
		_freeze_field_order(
			[
				"a",
				"custom_pea_joint_production_lines",
				"custom_pea_joint_resources_section",
				"custom_pea_joint_resources_col_break",
				"b",
				"custom_pea_joint_fetch_items",
				"c",
			]
		)
		self._assert_result_and_idempotent(
			relocate_joint_fetch_items,
			["a", "custom_pea_joint_production_lines", "custom_pea_joint_fetch_items", "b", "c"],
		)

	def test_relocate_joint_fetch_and_rejection_moves_blocks_after_anchor(self) -> None:
		_freeze_field_order(
			[
				"custom_pea_workstation_operator_section",
				"custom_pea_workstation",
				"custom_pea_operator",
				"custom_pea_rejection_section",
				"custom_pea_rejection_breakup",
				"custom_pea_joint_fetch_items",
				"custom_pea_rh_rejection_qty",
				"z",
			]
		)
		self._assert_result_and_idempotent(
			relocate_joint_fetch_and_rejection,
			[
				"custom_pea_rh_rejection_qty",
				"custom_pea_joint_fetch_items",
				"custom_pea_rejection_section",
				"custom_pea_rejection_breakup",
				"custom_pea_workstation_operator_section",
				"custom_pea_workstation",
				"custom_pea_operator",
				"z",
			],
		)

	def test_sync_manufacture_press_field_layout_moves_press_fields_after_operator(self) -> None:
		_freeze_field_order([*PRESS_FIELDS, "custom_pea_operator", "other"])
		self._assert_result_and_idempotent(
			sync_manufacture_press_field_layout,
			["custom_pea_operator", *PRESS_FIELDS, "other"],
		)


class TestCustomFieldLayoutPatches(FrappeTestCase):
	def _snapshot(self) -> list[tuple]:
		# idx is deliberately excluded: reorder_manufacture_press_fields_v2 is a shipped patch whose
		# idx drifts on re-run; insert_after is what drives field order.
		return frappe.get_all(
			"Custom Field",
			filters={"dt": "Stock Entry", "module": "Production Entry App"},
			fields=["name", "insert_after"],
			order_by="name",
			as_list=True,
		)

	def test_reorder_patches_place_press_fields_after_operator_and_are_idempotent(self) -> None:
		for patch_module in (reorder_manufacture_press_fields, reorder_manufacture_press_fields_v2):
			patch_module.execute()
			first = self._snapshot()
			patch_module.execute()
			self.assertEqual(self._snapshot(), first, patch_module.__name__)
			self.assertEqual(
				frappe.db.get_value("Custom Field", "Stock Entry-custom_pea_total_strokes", "insert_after"),
				"custom_pea_operator",
				patch_module.__name__,
			)


class TestCleanupPatches(FrappeTestCase):
	def _make_report(self, name: str, is_standard: str, module: str) -> None:
		frappe.db.delete("Report", {"name": name})
		frappe.get_doc(
			{
				"doctype": "Report",
				"report_name": name,
				"ref_doctype": "Stock Entry",
				"report_type": "Query Report",
				"is_standard": "No",
			}
		).insert(ignore_permissions=True)
		# Set after insert so the developer_mode export hook never writes module files.
		frappe.db.set_value("Report", name, {"is_standard": is_standard, "module": module})

	def test_remove_legacy_rework_reports_deletes_only_the_apps_standard_reports(self) -> None:
		self._make_report("Rework Register", "Yes", "Production Entry App")
		self._make_report("Daily Rework Report", "No", "Production Entry App")

		# Production is not in developer_mode; the patch runner sets in_patch, which Report.on_trash honours.
		with (
			patch.dict(frappe.local.conf, {"developer_mode": 0}),
			patch.dict(frappe.flags, {"in_patch": True}),
		):
			for _ in range(2):
				remove_legacy_rework_reports.execute()

		self.assertFalse(frappe.db.exists("Report", "Rework Register"))
		self.assertTrue(frappe.db.exists("Report", "Daily Rework Report"))

	def test_rename_rejection_breakup_item_code_is_noop_when_already_renamed(self) -> None:
		for _ in range(2):
			rename_rejection_breakup_item_code.execute()

		meta = frappe.get_meta("Rejection Breakup", cached=False)
		self.assertIsNotNone(meta.get_field("custom_pea_rb_item_code"))
		self.assertIsNone(meta.get_field("item_code"))
