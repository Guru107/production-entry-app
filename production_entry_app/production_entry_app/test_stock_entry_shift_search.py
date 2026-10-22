from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.api import stock_entry_shift_query


class TestStockEntryShiftSearch(FrappeTestCase):
	def test_stock_entry_shift_query_orders_by_shift_date_desc(self) -> None:
		query = MagicMock()
		for name in ("select", "where", "orderby", "limit", "offset"):
			setattr(query, name, MagicMock(return_value=query))
		query.run.return_value = [
			frappe._dict(name="SHIFT-NEW", shift_date="2026-12-31", status="Running"),
			frappe._dict(name="SHIFT-OLD", shift_date="2026-01-01", status="Completed"),
		]
		with (
			patch(
				"production_entry_app.production_entry_app.api.frappe.has_permission",
				return_value=True,
			),
			patch(
				"production_entry_app.production_entry_app.api.frappe.qb.from_",
				return_value=query,
			),
		):
			rows = stock_entry_shift_query("Shift", "", "name", 0, 10, None)

		self.assertEqual(rows[0][0], "SHIFT-NEW")
		order_calls = [call.args for call in query.orderby.call_args_list]
		self.assertTrue(any("shift_date" in str(call) or call for call in order_calls))
