from __future__ import annotations

from unittest.mock import call, patch

import frappe
from frappe.desk.query_report import run as run_query_report
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.report.pending_rework import pending_rework
from production_entry_app.production_entry_app.test_native_permissions import _ensure_user_with_exact_roles
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	ensure_item,
	ensure_warehouse,
	resolve_test_company,
)


class TestPendingReworkReport(FrappeTestCase):
	def setUp(self) -> None:
		frappe.db.rollback()
		suffix = frappe.generate_hash(length=6)
		self.item = ensure_item(f"_Test Pending Report {suffix}")
		self.warehouse = ensure_warehouse(f"Pending Rework {suffix}", resolve_test_company())

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_report_shows_derived_pool_beside_actual_balance_with_reason_drilldown(self) -> None:
		source = self._insert_source([("Burr", 4), ("Crack", 3)])
		self._insert_rework_consumption(2)
		self._set_bin_balance(3)

		columns, rows = pending_rework.execute({"item_code": self.item})

		self.assertEqual(
			[column["fieldname"] for column in columns],
			[
				"item_code",
				"rejection_reason",
				"flagged_rework_qty",
				"derived_pending_qty",
				"rejection_warehouse_balance",
				"pool_balance_difference",
				"source_entry_count",
				"source_entry",
				"rejection_warehouse",
			],
		)
		summary = rows[0]
		self.assertEqual(summary["item_code"], self.item)
		self.assertEqual(summary["indent"], 0)
		self.assertEqual(summary["flagged_rework_qty"], 7)
		self.assertEqual(summary["derived_pending_qty"], 5)
		self.assertEqual(summary["rejection_warehouse_balance"], 3)
		self.assertEqual(summary["pool_balance_difference"], 2)
		self.assertEqual(summary["source_entry_count"], 1)

		details = rows[1:]
		self.assertEqual(
			[(row["rejection_reason"], row["flagged_rework_qty"]) for row in details],
			[("Burr", 4), ("Crack", 3)],
		)
		for row in details:
			self.assertEqual(row["indent"], 1)
			self.assertEqual(row["source_entry"], source)
			self.assertEqual(row["rejection_warehouse"], self.warehouse)

	def test_item_filter_excludes_other_pending_items(self) -> None:
		self._insert_source([("Burr", 2)])
		other_item = ensure_item(f"_Test Pending Report Other {frappe.generate_hash(length=6)}")
		self._insert_source([("Crack", 6)], item_code=other_item)
		self._set_bin_balance(2)

		_rows = pending_rework.execute({"item_code": self.item})[1]

		self.assertEqual({row["item_code"] for row in _rows}, {self.item})

	def test_pea_read_only_runs_report_without_source_doctype_permissions(self) -> None:
		self._insert_source([("Burr", 2)])
		self._set_bin_balance(2)
		frappe.reload_doc("production_entry_app", "report", "pending_rework")
		frappe.reload_doc("production_entry_app", "doctype", "shift")
		user = f"test_pending_rework_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(user, ("PEA Read Only",))

		try:
			frappe.set_user(user)
			self.assertFalse(frappe.has_permission("Stock Entry", "read"))
			self.assertFalse(frappe.has_permission("Bin", "read"))
			result = run_query_report(
				"Pending Rework",
				filters={"item_code": self.item},
				ignore_prepared_report=True,
			)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result["result"][0]["item_code"], self.item)

	def test_contribution_reads_use_keyset_chunks(self) -> None:
		with patch.object(
			pending_rework,
			"_fetch_contribution_chunk",
			side_effect=[
				[
					frappe._dict(
						breakup_name="RB-1",
						detail_name="SED-1",
						item_code="ITEM-1",
					)
				],
				[
					frappe._dict(
						breakup_name="RB-2",
						detail_name="SED-2",
						item_code="ITEM-1",
					)
				],
				[],
			],
		) as fetch:
			rows = pending_rework._get_contributions(["ITEM-1"], chunk_size=1, max_rows=2)

		self.assertEqual(len(rows), 2)
		self.assertEqual(
			fetch.call_args_list,
			[
				call(["ITEM-1"], None, None, 1),
				call(["ITEM-1"], "RB-1", "SED-1", 1),
				call(["ITEM-1"], "RB-2", "SED-2", 1),
			],
		)

	def test_contribution_read_rejects_unbounded_result(self) -> None:
		row = frappe._dict(breakup_name="RB-1", detail_name="SED-1", item_code="ITEM-1")
		with (
			patch.object(pending_rework, "_fetch_contribution_chunk", side_effect=[[row], [row]]),
			self.assertRaisesRegex(frappe.ValidationError, "exceeds 1 contributing rows"),
		):
			pending_rework._get_contributions(["ITEM-1"], chunk_size=1, max_rows=1)

	def test_bin_balances_are_read_in_item_chunks(self) -> None:
		pairs = {("ITEM-1", "WH-1"), ("ITEM-2", "WH-2"), ("ITEM-3", "WH-3")}
		with patch.object(
			pending_rework,
			"get_report_rows",
			side_effect=[
				[
					{"item_code": "ITEM-1", "warehouse": "WH-1", "actual_qty": 1},
					{"item_code": "ITEM-2", "warehouse": "WH-2", "actual_qty": 2},
				],
				[{"item_code": "ITEM-3", "warehouse": "WH-3", "actual_qty": 3}],
			],
		) as get_rows:
			balances = pending_rework._get_bin_balances(pairs, chunk_size=2)

		self.assertEqual(balances, {"ITEM-1": 1, "ITEM-2": 2, "ITEM-3": 3})
		self.assertEqual(get_rows.call_count, 2)

	def test_single_chunk_report_uses_four_data_queries(self) -> None:
		self._insert_source([("Burr", 2)])
		self._set_bin_balance(2)
		pending_rework._get_columns()
		with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
			rows = pending_rework._get_rows({"item_code": self.item})

		self.assertEqual(sql.call_count, 4)
		self.assertEqual(rows[0]["derived_pending_qty"], 2)

	def _insert_source(self, reasons: list[tuple[str, float]], *, item_code: str | None = None) -> str:
		item_code = item_code or self.item
		name = f"PENDING-SOURCE-{frappe.generate_hash(length=8)}"
		StockEntry = frappe.qb.DocType("Stock Entry")
		StockEntryDetail = frappe.qb.DocType("Stock Entry Detail")
		RejectionBreakup = frappe.qb.DocType("Rejection Breakup")
		(
			frappe.qb.into(StockEntry)
			.columns(StockEntry.name, StockEntry.docstatus, StockEntry.stock_entry_type)
			.insert(name, 1, "Manufacture")
		).run()
		(
			frappe.qb.into(StockEntryDetail)
			.columns(
				StockEntryDetail.name,
				StockEntryDetail.parent,
				StockEntryDetail.parenttype,
				StockEntryDetail.parentfield,
				StockEntryDetail.item_code,
				StockEntryDetail.qty,
				StockEntryDetail.t_warehouse,
				StockEntryDetail.custom_pea_is_rejection_item,
			)
			.insert(
				frappe.generate_hash(length=10),
				name,
				"Stock Entry",
				"items",
				item_code,
				sum(qty for _reason, qty in reasons),
				self.warehouse,
				1,
			)
		).run()
		for reason, qty in reasons:
			(
				frappe.qb.into(RejectionBreakup)
				.columns(
					RejectionBreakup.name,
					RejectionBreakup.parent,
					RejectionBreakup.parenttype,
					RejectionBreakup.parentfield,
					RejectionBreakup.item_code,
					RejectionBreakup.rejection_reason,
					RejectionBreakup.qty,
					RejectionBreakup.is_rework,
				)
				.insert(
					frappe.generate_hash(length=10),
					name,
					"Stock Entry",
					"custom_pea_rejection_breakup",
					item_code,
					reason,
					qty,
					1,
				)
			).run()
		return name

	def _insert_rework_consumption(self, qty: float) -> None:
		stock_entry_type = f"Pending Rework Transfer {frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": stock_entry_type,
				"purpose": "Material Transfer",
				"custom_pea_rework_entry": 1,
			}
		).insert(ignore_permissions=True)
		name = f"PENDING-CONSUME-{frappe.generate_hash(length=8)}"
		StockEntry = frappe.qb.DocType("Stock Entry")
		StockEntryDetail = frappe.qb.DocType("Stock Entry Detail")
		(
			frappe.qb.into(StockEntry)
			.columns(StockEntry.name, StockEntry.docstatus, StockEntry.stock_entry_type)
			.insert(name, 1, stock_entry_type)
		).run()
		(
			frappe.qb.into(StockEntryDetail)
			.columns(
				StockEntryDetail.name,
				StockEntryDetail.parent,
				StockEntryDetail.parenttype,
				StockEntryDetail.parentfield,
				StockEntryDetail.item_code,
				StockEntryDetail.qty,
			)
			.insert(
				frappe.generate_hash(length=10),
				name,
				"Stock Entry",
				"items",
				self.item,
				qty,
			)
		).run()

	def _set_bin_balance(self, qty: float) -> None:
		bin_name = frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": self.warehouse})
		if not bin_name:
			bin_name = frappe.get_doc(
				{"doctype": "Bin", "item_code": self.item, "warehouse": self.warehouse}
			).insert(ignore_permissions=True).name
		frappe.db.set_value("Bin", bin_name, "actual_qty", qty, update_modified=False)
