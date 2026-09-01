from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import rework
from production_entry_app.production_entry_app.tests.support.manufacture_builders import ensure_item
from production_entry_app.production_entry_app.tests.support.rework_builders import (
	insert_pending_rework_source,
)


class TestPendingReworkPool(FrappeTestCase):
	def setUp(self) -> None:
		frappe.db.rollback()
		suffix = frappe.generate_hash(length=6)
		self.item_a = ensure_item(f"_Test Rework Pool A {suffix}")
		self.item_b = ensure_item(f"_Test Rework Pool B {suffix}")
		self.normal_type = self._insert_stock_entry_type(f"Normal Manufacture {suffix}", "Manufacture")
		self.joint_type = self._insert_stock_entry_type(f"Joint Repack {suffix}", "Repack")
		self.rework_type = self._insert_stock_entry_type(
			f"Rework Transfer {suffix}", "Material Transfer", is_rework=True
		)

	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_pool_aggregates_normal_joint_and_multi_row_rework_entries(self) -> None:
		self._insert_production_source(
			stock_entry_type=self.normal_type,
			breakups=[(None, 4), (None, 2)],
			rejection_items=[self.item_a],
		)
		self._insert_production_source(
			stock_entry_type=self.joint_type,
			breakups=[(self.item_a, 3), (self.item_b, 5)],
			rejection_items=[self.item_a, self.item_b],
		)
		self._insert_rework_entry([(self.item_a, 1), (self.item_a, 2), (self.item_b, 1)])

		self.assertEqual(
			rework.get_pending_rework(self.item_a),
			[{"item_code": self.item_a, "pending_qty": 6.0}],
		)
		self.assertEqual(
			rework.get_pending_rework(self.item_b),
			[{"item_code": self.item_b, "pending_qty": 4.0}],
		)

	def test_cancelled_rework_entry_restores_derived_availability(self) -> None:
		self._insert_production_source(
			stock_entry_type=self.normal_type,
			breakups=[(None, 5)],
			rejection_items=[self.item_a],
		)
		rework_entry = self._insert_rework_entry([(self.item_a, 3)])
		self.assertEqual(rework.get_pending_rework(self.item_a)[0]["pending_qty"], 2.0)

		StockEntry = frappe.qb.DocType("Stock Entry")
		(
			frappe.qb.update(StockEntry)
			.set(StockEntry.docstatus, 2)
			.where(StockEntry.name == rework_entry)
		).run()

		self.assertEqual(rework.get_pending_rework(self.item_a)[0]["pending_qty"], 5.0)

	def test_submission_rejects_aggregate_item_overdraw_and_excludes_itself(self) -> None:
		self._insert_production_source(
			stock_entry_type=self.normal_type,
			breakups=[(None, 5)],
			rejection_items=[self.item_a],
		)
		self._insert_rework_entry([(self.item_a, 1)])
		existing_name = self._insert_rework_entry([(self.item_a, 2)])
		doc = self._rework_doc(existing_name, [(self.item_a, 2), (self.item_a, 3)])

		with self.assertRaisesRegex(
			frappe.ValidationError,
			rf"{self.item_a}.*Available quantity is 4",
		):
			rework.validate_rework_submission(doc)

	def test_submission_locks_items_before_reading_pool(self) -> None:
		doc = self._rework_doc("REWORK-CONCURRENT", [(self.item_b, 1), (self.item_a, 1)])
		events: list[tuple[str, object]] = []

		with (
			patch.object(
				rework,
				"_lock_items_for_rework_submission",
				side_effect=lambda item_codes: events.append(("lock", item_codes)),
			),
			patch.object(
				rework,
				"_get_pending_rework_by_item",
				side_effect=lambda **kwargs: events.append(("read", kwargs))
				or {self.item_a: 1, self.item_b: 1},
			),
		):
			rework.validate_rework_submission(doc)

		self.assertEqual(events[0], ("lock", [self.item_a, self.item_b]))
		self.assertEqual(events[1][0], "read")
		self.assertEqual(events[1][1]["exclude_stock_entry"], doc.name)
		self.assertTrue(events[1][1]["lock_rows"])

	def test_api_requires_stock_entry_read_permission(self) -> None:
		with patch.object(rework.frappe, "has_permission", return_value=False):
			with self.assertRaises(frappe.PermissionError):
				rework.get_pending_rework()

	def test_pool_query_count_is_constant_for_multiple_items(self) -> None:
		self._insert_production_source(
			stock_entry_type=self.joint_type,
			breakups=[(self.item_a, 3), (self.item_b, 4)],
			rejection_items=[self.item_a, self.item_b],
		)
		with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
			rework.get_pending_rework()

		self.assertEqual(sql.call_count, 2)

	def _insert_stock_entry_type(self, name: str, purpose: str, *, is_rework: bool = False) -> str:
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": name,
				"purpose": purpose,
				"custom_pea_rework_entry": int(is_rework),
			}
		).insert(ignore_permissions=True)
		return name

	def _insert_production_source(
		self,
		*,
		stock_entry_type: str,
		breakups: list[tuple[str | None, float]],
		rejection_items: list[str],
	) -> str:
		return insert_pending_rework_source(
			stock_entry_type=stock_entry_type,
			breakups=breakups,
			rejection_items=rejection_items,
		)

	def _insert_rework_entry(self, items: list[tuple[str, float]]) -> str:
		name = f"POOL-REWORK-{frappe.generate_hash(length=10)}"
		self._insert_stock_entry(name, self.rework_type, docstatus=1)
		for item_code, qty in items:
			self._insert_stock_entry_item(name, item_code, qty)
		return name

	def _insert_stock_entry(self, name: str, stock_entry_type: str, *, docstatus: int) -> None:
		StockEntry = frappe.qb.DocType("Stock Entry")
		(
			frappe.qb.into(StockEntry)
			.columns(StockEntry.name, StockEntry.docstatus, StockEntry.stock_entry_type)
			.insert(name, docstatus, stock_entry_type)
		).run()

	def _insert_stock_entry_item(
		self, parent: str, item_code: str, qty: float, *, is_rejection: bool = False
	) -> None:
		StockEntryDetail = frappe.qb.DocType("Stock Entry Detail")
		(
			frappe.qb.into(StockEntryDetail)
			.columns(
				StockEntryDetail.name,
				StockEntryDetail.parent,
				StockEntryDetail.parenttype,
				StockEntryDetail.parentfield,
				StockEntryDetail.item_code,
				StockEntryDetail.qty,
				StockEntryDetail.custom_pea_is_rejection_item,
			)
			.insert(
				frappe.generate_hash(length=10),
				parent,
				"Stock Entry",
				"items",
				item_code,
				qty,
				int(is_rejection),
			)
		).run()

	def _rework_doc(self, name: str, items: list[tuple[str, float]]) -> frappe._dict:
		return frappe._dict(
			name=name,
			stock_entry_type=self.rework_type,
			items=[frappe._dict(item_code=item_code, qty=qty) for item_code, qty in items],
			flags=frappe._dict(),
		)
