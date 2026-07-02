from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.overrides.stock_entry import ProductionEntryAppStockEntry
from production_entry_app.production_entry_app.overrides.test_stock_entry_hooks import (
	_append_rejection_breakup_rows,
	_ensure_rejection_breakup_custom_field,
	_ensure_rejection_breakup_doctype,
	_ensure_rejection_reason_doctype,
	_ensure_rejection_reasons,
)
from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
	bootstrap_manufacture_masters,
	make_direct_manufacture_entry,
	make_running_shift,
)


class TestStockEntryOverride(FrappeTestCase):
	"""Regression coverage for rejection-row FG selection and valuation posting."""

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()

	def setUp(self) -> None:
		frappe.db.rollback()
		self.masters = bootstrap_manufacture_masters()

	def tearDown(self) -> None:
		frappe.db.rollback()

	def _append_default_rejection_rows(self, se: object) -> None:
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 6, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 4, "remark": "Surface crack"},
			],
		)

	def _make_manufacture_entry_with_rejection_breakup(self, shift_name: str, fg_qty: float) -> object:
		se = make_direct_manufacture_entry(
			self.masters,
			shift=shift_name,
			fg_qty=fg_qty,
			rejection_qty=0,
		)
		while se.custom_pea_rejection_breakup:
			se.custom_pea_rejection_breakup.pop()
		self._append_default_rejection_rows(se)
		se.custom_pea_rejection_qty = 10
		se.save(ignore_permissions=True)
		return se

	def test_stock_entry_uses_app_override_for_finished_item_selection(self) -> None:
		shift = make_running_shift(self.masters)
		se = self._make_manufacture_entry_with_rejection_breakup(shift.name, fg_qty=100)

		self.assertIsInstance(se, ProductionEntryAppStockEntry)
		finished_row = se.get_finished_item_row()
		self.assertIsNotNone(finished_row)
		assert finished_row is not None
		self.assertTrue(finished_row.is_finished_item)
		self.assertFalse(finished_row.custom_pea_is_rejection_item)
		self.assertEqual(finished_row.t_warehouse, self.masters["fg_warehouse"])

	def test_rejection_row_posts_non_zero_valuation_on_submit(self) -> None:
		shift = make_running_shift(self.masters)
		se = self._make_manufacture_entry_with_rejection_breakup(shift.name, fg_qty=100)

		fg_rows = [row for row in se.items if row.is_finished_item and not row.custom_pea_is_rejection_item]
		rejection_rows = [row for row in se.items if row.custom_pea_is_rejection_item]
		self.assertEqual(len(fg_rows), 1)
		self.assertEqual(len(rejection_rows), 1)
		self.assertAlmostEqual(rejection_rows[0].basic_rate, fg_rows[0].basic_rate, places=6)

		se.submit()

		fg_rows = [row for row in se.items if row.is_finished_item and not row.custom_pea_is_rejection_item]
		rejection_rows = [row for row in se.items if row.custom_pea_is_rejection_item]
		self.assertEqual(len(fg_rows), 1)
		self.assertEqual(len(rejection_rows), 1)

		sle_rows = frappe.get_all(
			"Stock Ledger Entry",
			filters={
				"voucher_no": se.name,
				"voucher_detail_no": rejection_rows[0].name,
				"warehouse": self.masters["rejection_warehouse"],
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
				"warehouse": self.masters["fg_warehouse"],
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

	def test_manufacture_with_rejection_posts_expected_sles(self) -> None:
		shift = make_running_shift(self.masters)
		se = make_direct_manufacture_entry(self.masters, shift=shift.name, fg_qty=100, rejection_qty=10)
		se.submit()

		sles = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": se.name},
			fields=["warehouse", "actual_qty"],
		)
		by_wh = {row["warehouse"]: row["actual_qty"] for row in sles}
		assert by_wh[self.masters["fg_warehouse"]] == 90
		assert by_wh[self.masters["rejection_warehouse"]] == 10

	def test_manufacture_with_rejection_cancels_cleanly(self) -> None:
		shift = make_running_shift(self.masters)
		se = make_direct_manufacture_entry(self.masters, shift=shift.name, fg_qty=100, rejection_qty=10)
		se.submit()
		submitted_sles = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": se.name, "is_cancelled": 0},
			fields=["name", "warehouse", "actual_qty"],
		)
		assert submitted_sles
		se.cancel()

		active_after_cancel = frappe.get_all(
			"Stock Ledger Entry", filters={"voucher_no": se.name, "is_cancelled": 0}, pluck="name"
		)
		cancelled_after_cancel = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": se.name, "is_cancelled": 1},
			fields=["warehouse", "actual_qty"],
		)
		assert not active_after_cancel
		assert len(cancelled_after_cancel) >= len(submitted_sles)
		submitted_warehouses = {row["warehouse"] for row in submitted_sles}
		cancelled_warehouses = {row["warehouse"] for row in cancelled_after_cancel}
		for warehouse in submitted_warehouses:
			assert warehouse in cancelled_warehouses
