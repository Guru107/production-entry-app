from __future__ import annotations

from unittest.mock import call, patch

import frappe
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

	def test_validate_returns_early_without_required_role(self) -> None:
		from production_entry_app.production_entry_app.overrides import stock_entry_hooks as hooks

		doc = frappe._dict(
			{
				"doctype": "Stock Entry",
				"custom_shift": "SHIFT-ACCESS-CONTROL",
				"custom_rejection_qty": 5,
			}
		)

		with (
			patch.object(
				hooks.access_control,
				"_get_access_configuration",
				return_value=hooks.access_control.AccessConfiguration(enabled=True, required_role="PEA User"),
			),
			patch.object(hooks.access_control.frappe, "get_roles", return_value=["Manufacturing User"]),
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

	def test_denied_submit_cancel_still_triggers_app_side_effects(self) -> None:
		from production_entry_app.production_entry_app.overrides import stock_entry_hooks as hooks

		doc = frappe._dict({"doctype": "Stock Entry", "custom_shift": "SHIFT-ACCESS-CONTROL"})

		with (
			patch.object(
				hooks.access_control,
				"_get_access_configuration",
				return_value=hooks.access_control.AccessConfiguration(enabled=True, required_role="PEA User"),
			),
			patch.object(hooks.access_control.frappe, "get_roles", return_value=["Manufacturing User"]),
			patch.object(hooks, "update_counter_for_stock_entry") as update_counter,
			patch.object(hooks, "frappe") as frappe_mod,
		):
			self.assertFalse(hooks.access_control.can_use_production_entry_app())
			hooks.on_submit_stock_entry(doc, "on_submit")
			hooks.on_cancel_stock_entry(doc, "on_cancel")

		update_counter.assert_has_calls([call(doc, direction=1), call(doc, direction=-1)])
		self.assertEqual(update_counter.call_count, 2)
		frappe_mod.cache.return_value.delete_value.assert_has_calls(
			[call("pea:shift_summary:SHIFT-ACCESS-CONTROL"), call("pea:shift_summary:SHIFT-ACCESS-CONTROL")]
		)
		self.assertEqual(frappe_mod.cache.return_value.delete_value.call_count, 2)

	def test_denied_finished_item_row_uses_native_behavior(self) -> None:
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

		self.assertIsInstance(se, ProductionEntryAppStockEntry)
		finished_row = se.get_finished_item_row()
		self.assertIsNotNone(finished_row)
		self.assertFalse(finished_row.custom_is_rejection_item)
		self.assertEqual(finished_row.item_code, self.fg_item)
		self.assertEqual(finished_row.t_warehouse, self.fg_warehouse)
