from __future__ import annotations

from unittest.mock import call, patch

import frappe
from frappe.desk.query_report import run as run_query_report
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.report.rework_register import rework_register
from production_entry_app.production_entry_app.test_native_permissions import _ensure_user_with_exact_roles


class TestReworkRegister(FrappeTestCase):
	def setUp(self) -> None:
		frappe.db.rollback()
		suffix = frappe.generate_hash(length=6)
		self.rework_entry_type = f"Register Rework {suffix}"
		self.normal_entry_type = f"Register Normal {suffix}"
		self.item_a = f"_Test Register A {suffix}"
		self.item_b = f"_Test Register B {suffix}"

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_report_shows_one_row_per_submitted_rework_entry(self) -> None:
		entry = self._insert_entry(
			posting_date="2092-01-10",
			rework_type="Deburring",
			workstation="Register Workstation",
			items=[(self.item_a, 4), (self.item_b, 2)],
			operators=["Operator A", "Operator B"],
			start="2092-01-10 08:00:00",
			end="2092-01-10 09:30:00",
			cost=360,
		)
		self._insert_entry(
			posting_date="2092-01-10",
			rework_type="Deburring",
			workstation="Register Workstation",
			items=[(self.item_a, 1)],
			operators=["Operator A"],
			start="2092-01-10 10:00:00",
			end="2092-01-10 10:30:00",
			cost=60,
			docstatus=0,
		)
		self._insert_entry(
			posting_date="2092-01-10",
			rework_type="",
			workstation="Register Workstation",
			items=[(self.item_a, 1)],
			operators=[],
			start=None,
			end=None,
			cost=0,
			stock_entry_type=self.normal_entry_type,
		)

		columns, rows = rework_register.execute({"from_date": "2092-01-10", "to_date": "2092-01-10"})

		self.assertEqual(
			[column["fieldname"] for column in columns],
			[
				"date",
				"rework_entry",
				"rework_type",
				"workstation",
				"items",
				"total_qty",
				"duration_hours",
				"operator_names",
				"operator_count",
				"computed_cost",
			],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["rework_entry"], entry)
		self.assertEqual(rows[0]["items"], f"{self.item_a} (4), {self.item_b} (2)")
		self.assertEqual(rows[0]["total_qty"], 6)
		self.assertEqual(rows[0]["duration_hours"], 1.5)
		self.assertEqual(rows[0]["operator_names"], "Operator A, Operator B")
		self.assertEqual(rows[0]["operator_count"], 2)
		self.assertEqual(rows[0]["computed_cost"], 360)

	def test_report_filters_by_date_type_item_and_workstation(self) -> None:
		matching = self._insert_entry(
			posting_date="2092-02-10",
			rework_type="Deburring",
			workstation="Register Workstation A",
			items=[(self.item_a, 3)],
			operators=["Operator A"],
			start="2092-02-10 08:00:00",
			end="2092-02-10 09:00:00",
			cost=120,
		)
		self._insert_entry(
			posting_date="2092-02-11",
			rework_type="Polishing",
			workstation="Register Workstation B",
			items=[(self.item_b, 7)],
			operators=["Operator B"],
			start="2092-02-11 08:00:00",
			end="2092-02-11 09:00:00",
			cost=140,
		)

		for filters in (
			{"from_date": "2092-02-10", "to_date": "2092-02-10"},
			{"from_date": "2092-02-10", "to_date": "2092-02-10", "rework_type": "Deburring"},
			{"item_code": self.item_a},
			{"workstation": "Register Workstation A"},
		):
			with self.subTest(filters=filters):
				rows = rework_register.execute(filters)[1]
				self.assertEqual([row["rework_entry"] for row in rows], [matching])

	def test_pea_read_only_runs_report_without_stock_entry_permission(self) -> None:
		frappe.reload_doc("production_entry_app", "report", "rework_register")
		frappe.reload_doc("production_entry_app", "doctype", "shift")
		user = f"test_rework_register_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(user, ("PEA Read Only",))
		entry = self._insert_entry(
			posting_date="2092-03-10",
			rework_type="Deburring",
			workstation="Register Workstation",
			items=[(self.item_a, 2)],
			operators=["Operator A"],
			start="2092-03-10 08:00:00",
			end="2092-03-10 08:30:00",
			cost=60,
		)
		try:
			frappe.set_user(user)
			self.assertFalse(frappe.has_permission("Stock Entry", "read"))
			result = run_query_report(
				"Rework Register",
				filters={"item_code": self.item_a},
				ignore_prepared_report=True,
			)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result["result"][0]["rework_entry"], entry)
		self.assertEqual(result["result"][-1][5:10], [2.0, 0.5, "", 1.0, 60.0])

	def test_entry_reads_use_keyset_chunks(self) -> None:
		with patch.object(
			rework_register,
			"_fetch_entry_chunk",
			side_effect=[
				[frappe._dict(name="REWORK-1")],
				[frappe._dict(name="REWORK-2")],
				[],
			],
		) as fetch:
			rows = rework_register._get_entries({}, ["Rework Transfer"], chunk_size=1, max_rows=2)

		self.assertEqual([row.name for row in rows], ["REWORK-1", "REWORK-2"])
		self.assertEqual(
			fetch.call_args_list,
			[
				call({}, ["Rework Transfer"], None, 1),
				call({}, ["Rework Transfer"], "REWORK-1", 1),
				call({}, ["Rework Transfer"], "REWORK-2", 1),
			],
		)

	def test_entry_read_rejects_unbounded_result(self) -> None:
		row = frappe._dict(name="REWORK-1")
		with (
			patch.object(rework_register, "_fetch_entry_chunk", side_effect=[[row], [row]]),
			self.assertRaisesRegex(frappe.ValidationError, "exceeds 1 submitted entries"),
		):
			rework_register._get_entries({}, ["Rework Transfer"], chunk_size=1, max_rows=1)

	def test_child_rows_are_read_in_parent_chunks(self) -> None:
		with patch.object(
			rework_register,
			"get_report_rows",
			side_effect=[
				[frappe._dict(parent="REWORK-1", item_code="ITEM-1")],
				[frappe._dict(parent="REWORK-3", item_code="ITEM-3")],
			],
		) as get_rows:
			rows = rework_register._get_child_rows(
				"Stock Entry Detail",
				["REWORK-1", "REWORK-2", "REWORK-3"],
				fields=["parent", "item_code"],
				parentfield="items",
				chunk_size=2,
			)

		self.assertEqual([row.parent for row in rows], ["REWORK-1", "REWORK-3"])
		self.assertEqual(get_rows.call_count, 2)

	def test_single_chunk_report_uses_four_data_queries(self) -> None:
		self._insert_entry(
			posting_date="2092-04-10",
			rework_type="Deburring",
			workstation="Register Workstation",
			items=[(self.item_a, 2)],
			operators=["Operator A"],
			start="2092-04-10 08:00:00",
			end="2092-04-10 08:30:00",
			cost=60,
		)
		with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
			rows = rework_register._get_rows({"from_date": "2092-04-10", "to_date": "2092-04-10"})

		self.assertEqual(sql.call_count, 4)
		self.assertEqual(len(rows), 1)

	def test_stock_entry_report_filter_fields_are_indexed(self) -> None:
		meta = frappe.get_meta("Stock Entry")
		for fieldname in ("custom_pea_rework_type", "custom_pea_rework_workstation"):
			with self.subTest(fieldname=fieldname):
				self.assertEqual(meta.get_field(fieldname).search_index, 1)

	def test_report_is_empty_when_no_rework_entry_type_is_configured(self) -> None:
		with patch.object(rework_register, "get_report_rows", return_value=[]):
			rows = rework_register.execute({})[1]

		self.assertEqual(rows, [])

	def _insert_stock_entry_type(self, name: str, *, is_rework: bool) -> None:
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": name,
				"purpose": "Material Transfer",
				"custom_pea_rework_entry": int(is_rework),
			}
		).insert(ignore_permissions=True)

	def _ensure_entry_types(self) -> None:
		if not frappe.db.exists("Stock Entry Type", self.rework_entry_type):
			self._insert_stock_entry_type(self.rework_entry_type, is_rework=True)
		if not frappe.db.exists("Stock Entry Type", self.normal_entry_type):
			self._insert_stock_entry_type(self.normal_entry_type, is_rework=False)

	def _insert_entry(
		self,
		*,
		posting_date: str,
		rework_type: str,
		workstation: str,
		items: list[tuple[str, float]],
		operators: list[str],
		start: str | None,
		end: str | None,
		cost: float,
		docstatus: int = 1,
		stock_entry_type: str | None = None,
	) -> str:
		self._ensure_entry_types()
		name = f"REGISTER-{frappe.generate_hash(length=10)}"
		StockEntry = frappe.qb.DocType("Stock Entry")
		(
			frappe.qb.into(StockEntry)
			.columns(
				StockEntry.name,
				StockEntry.docstatus,
				StockEntry.purpose,
				StockEntry.stock_entry_type,
				StockEntry.posting_date,
				StockEntry.custom_pea_rework_type,
				StockEntry.custom_pea_rework_workstation,
				StockEntry.custom_pea_rework_actual_start,
				StockEntry.custom_pea_rework_actual_end,
				StockEntry.custom_pea_rework_cost,
			)
			.insert(
				name,
				docstatus,
				"Material Transfer",
				stock_entry_type or self.rework_entry_type,
				posting_date,
				rework_type,
				workstation,
				start,
				end,
				cost,
			)
		).run()
		StockEntryDetail = frappe.qb.DocType("Stock Entry Detail")
		for idx, (item_code, qty) in enumerate(items, start=1):
			(
				frappe.qb.into(StockEntryDetail)
				.columns(
					StockEntryDetail.name,
					StockEntryDetail.parent,
					StockEntryDetail.parenttype,
					StockEntryDetail.parentfield,
					StockEntryDetail.item_code,
					StockEntryDetail.qty,
					StockEntryDetail.idx,
				)
				.insert(
					frappe.generate_hash(length=10),
					name,
					"Stock Entry",
					"items",
					item_code,
					qty,
					idx,
				)
			).run()
		ReworkOperator = frappe.qb.DocType("Rework Operator")
		for idx, operator in enumerate(operators, start=1):
			(
				frappe.qb.into(ReworkOperator)
				.columns(
					ReworkOperator.name,
					ReworkOperator.parent,
					ReworkOperator.parenttype,
					ReworkOperator.parentfield,
					ReworkOperator.operator,
					ReworkOperator.idx,
				)
				.insert(
					frappe.generate_hash(length=10),
					name,
					"Stock Entry",
					"custom_pea_rework_operators",
					operator,
					idx,
				)
			).run()
		return name
