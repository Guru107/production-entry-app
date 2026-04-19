from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.overrides.stock_entry import ProductionEntryAppStockEntry
from production_entry_app.production_entry_app.overrides.test_stock_entry_hooks import (
	_append_rejection_breakup_rows,
	_create_manufacture_stock_entry,
	_create_test_shift,
	_ensure_rejection_breakup_custom_field,
	_ensure_rejection_breakup_doctype,
	_ensure_rejection_reason_doctype,
	_ensure_rejection_reasons,
	_get_or_create_item,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	bootstrap_manufacturing_test_context,
	cleanup_running_shifts,
	ensure_production_entry_settings_shift_fields,
	ensure_stock,
)


def _set_shift_warehouse_defaults(rm_warehouse: str, wip_warehouse: str, rejection_warehouse: str) -> None:
	ensure_production_entry_settings_shift_fields()
	frappe.db.set_single_value("Production Entry Settings", "shift_raw_material_warehouse", rm_warehouse)
	frappe.db.set_single_value("Production Entry Settings", "shift_wip_warehouse", wip_warehouse)
	frappe.db.set_single_value("Production Entry Settings", "shift_rejection_warehouse", rejection_warehouse)


class TestStockEntryOverride(FrappeTestCase):
	"""Regression coverage for rejection-row FG selection and valuation posting."""

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()
		context = bootstrap_manufacturing_test_context("SE Override")
		cls.company = context["company"]
		cls.wip_warehouse = context["wip_warehouse"]
		cls.rm_warehouse = context["rm_warehouse"]
		cls.rejection_warehouse = context["rejection_warehouse"]
		cls.fg_warehouse = context["fg_warehouse"]
		cls.fg_item = _get_or_create_item("_Test FG Item For Shift")
		cls.rm_item = _get_or_create_item("_Test RM Item For Shift")
		_set_shift_warehouse_defaults(cls.rm_warehouse, cls.wip_warehouse, cls.rejection_warehouse)

	def setUp(self) -> None:
		cleanup_running_shifts()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - ensure running shift cleanup is visible
		_set_shift_warehouse_defaults(self.rm_warehouse, self.wip_warehouse, self.rejection_warehouse)
		ensure_stock(self.rm_item, self.rm_warehouse, self.company, target_qty=200)

	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_stock_entry_uses_app_override_for_finished_item_selection(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-24",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 6, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 4, "remark": "Surface crack"},
			],
		)

		self.assertIsInstance(se, ProductionEntryAppStockEntry)
		finished_row = se.get_finished_item_row()
		self.assertIsNotNone(finished_row)
		self.assertTrue(finished_row.is_finished_item)
		self.assertFalse(finished_row.custom_is_rejection_item)
		self.assertEqual(finished_row.t_warehouse, self.fg_warehouse)

	def test_rejection_row_posts_non_zero_valuation_on_submit(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-25",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 6, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 4, "remark": "Surface crack"},
			],
		)
		se.insert(ignore_permissions=True)

		fg_rows = [row for row in se.items if row.is_finished_item and not row.custom_is_rejection_item]
		rejection_rows = [row for row in se.items if row.custom_is_rejection_item]
		self.assertEqual(len(fg_rows), 1)
		self.assertEqual(len(rejection_rows), 1)
		self.assertAlmostEqual(rejection_rows[0].basic_rate, fg_rows[0].basic_rate, places=6)

		se.submit()

		fg_rows = [row for row in se.items if row.is_finished_item and not row.custom_is_rejection_item]
		rejection_rows = [row for row in se.items if row.custom_is_rejection_item]
		self.assertEqual(len(fg_rows), 1)
		self.assertEqual(len(rejection_rows), 1)

		sle_rows = frappe.get_all(
			"Stock Ledger Entry",
			filters={
				"voucher_no": se.name,
				"voucher_detail_no": rejection_rows[0].name,
				"warehouse": self.rejection_warehouse,
				"is_cancelled": 0,
			},
			fields=["valuation_rate", "stock_value_difference", "actual_qty"],
		)
		self.assertEqual(len(sle_rows), 1)
		self.assertGreater(float(sle_rows[0]["valuation_rate"] or 0), 0)
		self.assertGreater(float(sle_rows[0]["stock_value_difference"] or 0), 0)

		fg_sle_rows = frappe.get_all(
			"Stock Ledger Entry",
			filters={
				"voucher_no": se.name,
				"voucher_detail_no": fg_rows[0].name,
				"warehouse": self.fg_warehouse,
				"is_cancelled": 0,
			},
			fields=["valuation_rate", "stock_value_difference", "actual_qty"],
		)
		self.assertEqual(len(fg_sle_rows), 1)
		self.assertGreater(float(fg_sle_rows[0]["valuation_rate"] or 0), 0)

		rejection_sle = sle_rows[0]
		fg_sle = fg_sle_rows[0]
		currency_precision = int(frappe.db.get_single_value("System Settings", "currency_precision") or 2)
		currency_places = max(currency_precision, 0)
		self.assertAlmostEqual(
			float(rejection_sle["valuation_rate"] or 0),
			float(fg_sle["valuation_rate"] or 0),
			places=6,
		)
		self.assertAlmostEqual(
			float(rejection_sle["stock_value_difference"] or 0),
			float(rejection_sle["actual_qty"] or rejection_rows[0].qty)
			* float(fg_sle["valuation_rate"] or 0),
			places=currency_places,
		)
