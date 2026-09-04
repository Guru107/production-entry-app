from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.rejection_warehouse import get_rejected_warehouses
from production_entry_app.production_entry_app.utils.test_bootstrap import bootstrap_manufacturing_test_context


class TestRejectedWarehouseLookup(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_rejected_warehouse_lookup_returns_only_flagged_names(self) -> None:
		ctx = bootstrap_manufacturing_test_context("Rejected Lookup")

		self.assertEqual(
			get_rejected_warehouses([ctx["rejection_warehouse"], ctx["fg_warehouse"], None, ""]),
			{ctx["rejection_warehouse"]},
		)

	def test_rejected_warehouse_lookup_skips_the_query_for_empty_input(self) -> None:
		self.assertEqual(get_rejected_warehouses([]), set())
