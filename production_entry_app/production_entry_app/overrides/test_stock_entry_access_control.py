from __future__ import annotations

from unittest.mock import patch

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.overrides.stock_entry import ProductionEntryAppStockEntry
from production_entry_app.production_entry_app.overrides.test_stock_entry_hooks import (
	_ensure_rejection_breakup_custom_field,
	_ensure_rejection_breakup_doctype,
	_ensure_rejection_reason_doctype,
	_ensure_rejection_reasons,
	_get_or_create_item,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	bootstrap_manufacturing_test_context,
	cleanup_running_shifts,
)


class TestStockEntryAccessControl(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()
		context = bootstrap_manufacturing_test_context("SE Access Control")
		cls.company = context["company"]
		cls.wip_warehouse = context["wip_warehouse"]
		cls.rm_warehouse = context["rm_warehouse"]
		cls.rejection_warehouse = context["rejection_warehouse"]
		cls.fg_warehouse = context["fg_warehouse"]
		cls.fg_item = _get_or_create_item("_Test FG Item For Shift")
		cls.rm_item = _get_or_create_item("_Test RM Item For Shift")

	def setUp(self) -> None:
		cleanup_running_shifts()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - keep shift cleanup visible

	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_denied_validate_hook_skips_app_logic(self) -> None:
		from production_entry_app.production_entry_app.overrides import stock_entry_hooks as hooks

		doc = frappe._dict(
			{
				"doctype": "Stock Entry",
				"custom_shift": "SHIFT-ACCESS-CONTROL",
				"custom_rejection_qty": 5,
			}
		)

		with (
			patch.object(hooks.access_control, "can_use_production_entry_app", return_value=False),
			patch.object(hooks, "_validate_linked_shift_is_running") as validate_shift,
			patch.object(hooks, "_apply_shift_defaults") as apply_shift_defaults,
			patch.object(hooks, "_sync_unplanned_loss_shift_links") as sync_loss_links,
			patch.object(hooks, "_validate_actual_times") as validate_actual_times,
			patch.object(hooks, "_validate_workstation_overlap") as validate_workstation_overlap,
			patch.object(hooks, "_validate_operator_overlap") as validate_operator_overlap,
			patch.object(hooks, "_validate_workstation_downtime_overlap") as validate_downtime_overlap,
			patch.object(hooks, "_validate_rejection_breakup") as validate_rejection_breakup,
			patch.object(hooks, "_apply_rejection_entries") as apply_rejection_entries,
			patch.object(hooks, "_validate_rejection_target_warehouses") as validate_target_warehouses,
			patch.object(hooks, "_set_entry_metrics") as set_entry_metrics,
		):
			hooks.validate_stock_entry(doc, "validate")

		for mock in (
			validate_shift,
			apply_shift_defaults,
			sync_loss_links,
			validate_actual_times,
			validate_workstation_overlap,
			validate_operator_overlap,
			validate_downtime_overlap,
			validate_rejection_breakup,
			apply_rejection_entries,
			validate_target_warehouses,
			set_entry_metrics,
		):
			mock.assert_not_called()

	def test_denied_submit_cancel_skip_app_side_effects(self) -> None:
		from production_entry_app.production_entry_app.overrides import stock_entry_hooks as hooks

		doc = frappe._dict({"doctype": "Stock Entry", "custom_shift": "SHIFT-ACCESS-CONTROL"})

		with (
			patch.object(hooks.access_control, "can_use_production_entry_app", return_value=False),
			patch.object(hooks, "update_counter_for_stock_entry") as update_counter,
			patch.object(hooks, "frappe") as frappe_mod,
		):
			hooks.on_submit_stock_entry(doc, "on_submit")
			hooks.on_cancel_stock_entry(doc, "on_cancel")

		update_counter.assert_not_called()
		frappe_mod.cache.assert_not_called()

	def test_denied_finished_item_row_uses_native_behavior(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry.access_control.can_use_production_entry_app",
			return_value=False,
		):
			se = frappe.get_doc(
				{
					"doctype": "Stock Entry",
					"purpose": "Manufacture",
					"stock_entry_type": "Manufacture",
					"company": self.company,
				}
			)
			se.append(
				"items",
				{
					"item_code": self.fg_item,
					"qty": 5,
					"is_finished_item": 1,
					"t_warehouse": self.fg_warehouse,
				},
			)
			se.append(
				"items",
				{
					"item_code": self.fg_item,
					"qty": 5,
					"is_finished_item": 1,
					"custom_is_rejection_item": 1,
					"t_warehouse": self.rejection_warehouse,
				},
			)

			override_row = se.get_finished_item_row()
			base_row = StockEntry.get_finished_item_row(se)

		self.assertIsInstance(se, ProductionEntryAppStockEntry)
		self.assertIs(override_row, base_row)
		self.assertTrue(override_row.custom_is_rejection_item)
		self.assertEqual(override_row.t_warehouse, self.rejection_warehouse)
