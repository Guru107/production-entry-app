from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.joint_production import JOINT_LH_RH_STOCK_ENTRY_TYPE
from production_entry_app.production_entry_app.report.daily_rework_report import daily_rework_report


class TestDailyReworkReport(FrappeTestCase):
	def setUp(self) -> None:
		frappe.db.rollback()
		self.suffix = frappe.generate_hash(length=6)
		self.rework_entry_type = f"Daily Rework {self.suffix}"
		self.normal_entry_type = f"Daily Normal {self.suffix}"
		self.item_a = f"_Test Daily A {self.suffix}"
		self.item_b = f"_Test Daily B {self.suffix}"
		self.rework_type_a = f"Daily Deburring {self.suffix}"
		self.rework_type_b = f"Daily Polishing {self.suffix}"
		self.workstation_a = f"Daily Workstation A {self.suffix}"
		self.workstation_b = f"Daily Workstation B {self.suffix}"

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_groups_entries_by_date_with_day_headers_and_subtotals(self) -> None:
		day_one, day_two = "2092-06-10", "2092-06-11"
		entry_one = self._insert_entry(
			posting_date=day_one,
			rework_type=self.rework_type_a,
			workstation=self.workstation_a,
			items=[(self.item_a, 4), (self.item_b, 2)],
			operators=["Operator A", "Operator B"],
			start=f"{day_one} 08:00:00",
			end=f"{day_one} 09:30:00",
			rejection_reason="Bur",
			operation="Deburring",
		)
		entry_two = self._insert_entry(
			posting_date=day_one,
			rework_type=self.rework_type_a,
			workstation=self.workstation_a,
			items=[(self.item_a, 1)],
			operators=["Operator B"],
			start=f"{day_one} 10:00:00",
			end=f"{day_one} 10:30:00",
		)
		entry_three = self._insert_entry(
			posting_date=day_two,
			rework_type=self.rework_type_b,
			workstation=self.workstation_b,
			items=[(self.item_b, 3)],
			operators=["Operator C"],
			start=f"{day_two} 09:00:00",
			end=f"{day_two} 10:00:00",
		)
		# Noise: a draft and a non-rework entry on the same days must not appear.
		self._insert_entry(
			posting_date=day_one,
			rework_type=self.rework_type_a,
			workstation=self.workstation_a,
			items=[(self.item_a, 9)],
			operators=["Operator A"],
			start=f"{day_one} 11:00:00",
			end=f"{day_one} 12:00:00",
			docstatus=0,
		)
		self._insert_entry(
			posting_date=day_two,
			rework_type="",
			workstation=self.workstation_b,
			items=[(self.item_b, 9)],
			operators=[],
			start=None,
			end=None,
			stock_entry_type=self.normal_entry_type,
		)

		columns, rows, _message, chart = daily_rework_report.execute(
			{"from_date": day_one, "to_date": day_two}
		)

		self.assertEqual(
			[column["fieldname"] for column in columns],
			[
				"date",
				"rework_entry",
				"items",
				"total_qty",
				"rejection_reason",
				"operation",
				"rework_type",
				"workstation",
				"operator_names",
				"operator_count",
				"duration_hours",
				"daily_rew_ppm",
			],
		)
		self.assertEqual(len(rows), 7)

		header_one = rows[0]
		self.assertEqual(str(header_one["date"]), day_one)
		self.assertEqual(header_one["operator_count"], 2)
		self.assertEqual(header_one["duration_hours"], 3.5)
		self.assertEqual(header_one["bold"], 1)

		day_one_entries = [row for row in rows[1:3] if row.get("rework_entry")]
		self.assertEqual([row["rework_entry"] for row in day_one_entries], sorted([entry_one, entry_two]))
		entry_one_row = next(row for row in day_one_entries if row["rework_entry"] == entry_one)
		self.assertEqual(entry_one_row["items"], f"{self.item_a} (4), {self.item_b} (2)")
		self.assertEqual(entry_one_row["total_qty"], 6)
		self.assertEqual(entry_one_row["rejection_reason"], "Bur")
		self.assertEqual(entry_one_row["operation"], "Deburring")
		self.assertEqual(entry_one_row["rework_type"], self.rework_type_a)
		self.assertEqual(entry_one_row["workstation"], self.workstation_a)
		self.assertEqual(entry_one_row["operator_names"], "Operator A, Operator B")
		self.assertEqual(entry_one_row["duration_hours"], 3.0)

		subtotal_one = rows[3]
		self.assertEqual(subtotal_one["total_qty"], 7)
		self.assertEqual(subtotal_one["operator_count"], 2)
		self.assertEqual(subtotal_one["duration_hours"], 3.5)
		self.assertEqual(subtotal_one["daily_rew_ppm"], 0)
		self.assertEqual(subtotal_one["bold"], 1)

		header_two = rows[4]
		self.assertEqual(str(header_two["date"]), day_two)
		self.assertEqual(header_two["operator_count"], 1)
		self.assertEqual(header_two["duration_hours"], 1.0)

		self.assertEqual(rows[5]["rework_entry"], entry_three)

		subtotal_two = rows[6]
		self.assertEqual(subtotal_two["total_qty"], 3)
		self.assertEqual(subtotal_two["operator_count"], 1)
		self.assertEqual(subtotal_two["duration_hours"], 1.0)

		self.assertIsNotNone(chart)
		self.assertEqual(chart["type"], "bar")
		self.assertEqual(chart["data"]["labels"], [day_one, day_two])

	def test_daily_rew_ppm_divides_by_days_completed_production(self) -> None:
		day = "2092-06-12"
		completed_shift = self._insert_shift(day, "1", status="Completed")
		self._insert_production_entry(shift_name=completed_shift, posting_date=day, fg_qty=1000)
		self._insert_production_entry(
			shift_name=completed_shift,
			posting_date=day,
			fg_qty=0,
			purpose="Repack",
			stock_entry_type=JOINT_LH_RH_STOCK_ENTRY_TYPE,
			lh_gross=40,
			rh_gross=60,
		)
		# Noise: production on a non-Completed shift and a draft entry must not count.
		running_shift = self._insert_shift(day, "2", status="Running")
		self._insert_production_entry(shift_name=running_shift, posting_date=day, fg_qty=500)
		self._insert_production_entry(shift_name=completed_shift, posting_date=day, fg_qty=700, docstatus=0)
		self._insert_entry(
			posting_date=day,
			rework_type=self.rework_type_a,
			workstation=self.workstation_a,
			items=[(self.item_a, 11)],
			operators=["Operator A"],
			start=f"{day} 08:00:00",
			end=f"{day} 09:00:00",
		)
		# A day with rework but no production must still render with PPM 0.
		empty_day = "2092-06-13"
		self._insert_entry(
			posting_date=empty_day,
			rework_type=self.rework_type_a,
			workstation=self.workstation_a,
			items=[(self.item_a, 2)],
			operators=["Operator A"],
			start=f"{empty_day} 08:00:00",
			end=f"{empty_day} 08:30:00",
		)

		_columns, rows, _message, chart = daily_rework_report.execute(
			{"from_date": day, "to_date": empty_day}
		)

		subtotals = [row for row in rows if row.get("daily_rew_ppm") is not None]
		self.assertEqual(len(subtotals), 2)
		# 11 reworked / (1000 + 40 + 60) produced * 1e6.
		self.assertEqual(subtotals[0]["total_qty"], 11)
		self.assertEqual(subtotals[0]["daily_rew_ppm"], 10000)
		self.assertEqual(subtotals[1]["total_qty"], 2)
		self.assertEqual(subtotals[1]["daily_rew_ppm"], 0)
		self.assertEqual(chart["data"]["datasets"][0]["values"], [10000, 0])

	def test_filters_restrict_rows(self) -> None:
		day_one, day_two = "2092-06-20", "2092-06-21"
		matching = self._insert_entry(
			posting_date=day_one,
			rework_type=self.rework_type_a,
			workstation=self.workstation_a,
			items=[(self.item_a, 3)],
			operators=["Operator A"],
			start=f"{day_one} 08:00:00",
			end=f"{day_one} 09:00:00",
			rejection_reason="Bur",
			operation="Deburring",
		)
		self._insert_entry(
			posting_date=day_two,
			rework_type=self.rework_type_b,
			workstation=self.workstation_b,
			items=[(self.item_b, 7)],
			operators=["Operator B"],
			start=f"{day_two} 08:00:00",
			end=f"{day_two} 09:00:00",
			rejection_reason="Crack",
			operation="Polishing",
		)
		date_range = {"from_date": day_one, "to_date": day_two}

		for filters in (
			{**date_range, "rework_type": self.rework_type_a},
			{**date_range, "item_code": self.item_a},
			{**date_range, "workstation": self.workstation_a},
			{**date_range, "rejection_reason": "Bur"},
			{**date_range, "operation": "Deburring"},
			{**date_range, "operator": "Operator A"},
			{"from_date": day_one, "to_date": day_one},
		):
			with self.subTest(filters=filters):
				rows = daily_rework_report.execute(filters)[1]
				entry_rows = [row for row in rows if row.get("rework_entry")]
				self.assertEqual([row["rework_entry"] for row in entry_rows], [matching])

	def test_daily_rew_ppm_divides_raw_quantities_before_display_rounding(self) -> None:
		# At display precision 2, rounding inputs first would give 0.01/1 -> 10000
		# and 1/0.00 -> 0. Raw division must yield 6000 and 250000.
		day_one, day_two = "2092-07-14", "2092-07-15"
		shift_one = self._insert_shift(day_one, "1", status="Completed")
		self._insert_production_entry(shift_name=shift_one, posting_date=day_one, fg_qty=1)
		self._insert_entry(
			posting_date=day_one,
			rework_type=self.rework_type_a,
			workstation=self.workstation_a,
			items=[(self.item_a, 0.006)],
			operators=["Operator A"],
			start=f"{day_one} 08:00:00",
			end=f"{day_one} 09:00:00",
		)
		shift_two = self._insert_shift(day_two, "1", status="Completed")
		self._insert_production_entry(shift_name=shift_two, posting_date=day_two, fg_qty=0.004)
		self._insert_entry(
			posting_date=day_two,
			rework_type=self.rework_type_a,
			workstation=self.workstation_a,
			items=[(self.item_a, 0.001)],
			operators=["Operator A"],
			start=f"{day_two} 08:00:00",
			end=f"{day_two} 09:00:00",
		)

		with patch.object(daily_rework_report, "get_system_float_precision", return_value=2):
			rows = daily_rework_report.execute({"from_date": day_one, "to_date": day_two})[1]

		subtotals = [row for row in rows if row.get("daily_rew_ppm") is not None]
		self.assertEqual(len(subtotals), 2)
		self.assertEqual(subtotals[0]["daily_rew_ppm"], 6000)
		self.assertEqual(subtotals[0]["total_qty"], 0.01)
		# 0.001 / 0.004 * 1e6 = 250000 even though both inputs round to 0.00 on display.
		self.assertEqual(subtotals[1]["daily_rew_ppm"], 250000)
		self.assertEqual(subtotals[1]["total_qty"], 0)

	def test_child_row_filters_count_only_parents_inside_the_entry_scope(self) -> None:
		day = "2092-07-20"
		valid = self._insert_entry(
			posting_date=day,
			rework_type=self.rework_type_a,
			workstation=self.workstation_a,
			items=[(self.item_a, 2)],
			operators=["Operator A"],
			start=f"{day} 08:00:00",
			end=f"{day} 09:00:00",
		)
		# Same item and operator, but outside the entry scope: draft, other date, non-rework type.
		for posting_date, docstatus, stock_entry_type in (
			(day, 0, self.rework_entry_type),
			("2092-07-21", 1, self.rework_entry_type),
			(day, 1, self.normal_entry_type),
		):
			self._insert_entry(
				posting_date=posting_date,
				rework_type=self.rework_type_a,
				workstation=self.workstation_a,
				items=[(self.item_a, 2)],
				operators=["Operator A"],
				start=f"{day} 08:00:00",
				end=f"{day} 09:00:00",
				docstatus=docstatus,
				stock_entry_type=stock_entry_type,
			)

		for child_filter in ({"item_code": self.item_a}, {"operator": "Operator A"}):
			with self.subTest(child_filter=child_filter):
				entry_filters = daily_rework_report._build_entry_filters(
					{"from_date": day, "to_date": day, **child_filter},
					[self.rework_entry_type],
					max_parent_matches=1,
				)
				self.assertEqual(entry_filters["name"], ["in", [valid]])

	def test_child_row_filter_overflow_throws(self) -> None:
		day = "2092-07-22"
		for _unused in range(3):
			self._insert_entry(
				posting_date=day,
				rework_type=self.rework_type_a,
				workstation=self.workstation_a,
				items=[(self.item_a, 1)],
				operators=["Operator A"],
				start=f"{day} 08:00:00",
				end=f"{day} 09:00:00",
			)

		with self.assertRaisesRegex(frappe.ValidationError, "matches more than 2"):
			daily_rework_report._build_entry_filters(
				{"from_date": day, "to_date": day, "item_code": self.item_a},
				[self.rework_entry_type],
				max_parent_matches=2,
			)

	def test_empty_date_range_returns_no_rows_and_no_chart(self) -> None:
		_columns, rows, _message, chart = daily_rework_report.execute(
			{"from_date": "2092-12-01", "to_date": "2092-12-02"}
		)

		self.assertEqual(rows, [])
		self.assertIsNone(chart)

	def _insert_stock_entry_type(self, name: str, purpose: str, **flags: int) -> None:
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": name,
				"purpose": purpose,
				**flags,
			}
		).insert(ignore_permissions=True)

	def _ensure_entry_types(self) -> None:
		if not frappe.db.exists("Stock Entry Type", self.rework_entry_type):
			self._insert_stock_entry_type(
				self.rework_entry_type, "Material Transfer", custom_pea_rework_entry=1
			)
		if not frappe.db.exists("Stock Entry Type", self.normal_entry_type):
			self._insert_stock_entry_type(self.normal_entry_type, "Manufacture")

	def _insert_shift(self, shift_date: str, label: str, *, status: str) -> str:
		self._ensure_entry_types()
		name = f"SHIFT-DAILY-{self.suffix}-{shift_date}-{label}"
		Shift = frappe.qb.DocType("Shift")
		(
			frappe.qb.into(Shift)
			.columns(Shift.name, Shift.docstatus, Shift.status, Shift.shift_date)
			.insert(name, 0, status, shift_date)
		).run()
		return name

	def _insert_production_entry(
		self,
		*,
		shift_name: str,
		posting_date: str,
		fg_qty: float,
		purpose: str = "Manufacture",
		stock_entry_type: str | None = None,
		lh_gross: float | None = None,
		rh_gross: float | None = None,
		docstatus: int = 1,
	) -> str:
		self._ensure_entry_types()
		name = f"DAILY-PROD-{frappe.generate_hash(length=10)}"
		StockEntry = frappe.qb.DocType("Stock Entry")
		columns = [
			StockEntry.name,
			StockEntry.docstatus,
			StockEntry.purpose,
			StockEntry.stock_entry_type,
			StockEntry.posting_date,
			StockEntry.custom_pea_shift,
			StockEntry.fg_completed_qty,
		]
		values = [
			name,
			docstatus,
			purpose,
			stock_entry_type or self.normal_entry_type,
			posting_date,
			shift_name,
			fg_qty,
		]
		if lh_gross is not None:
			columns.append(StockEntry.custom_pea_lh_gross_qty)
			values.append(lh_gross)
		if rh_gross is not None:
			columns.append(StockEntry.custom_pea_rh_gross_qty)
			values.append(rh_gross)
		frappe.qb.into(StockEntry).columns(*columns).insert(*values).run()
		return name

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
		docstatus: int = 1,
		stock_entry_type: str | None = None,
		rejection_reason: str | None = None,
		operation: str | None = None,
	) -> str:
		self._ensure_entry_types()
		name = f"DAILY-{frappe.generate_hash(length=10)}"
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
				StockEntry.custom_pea_rework_rejection_reason,
				StockEntry.custom_pea_rework_operation,
			)
			.insert(
				name,
				docstatus,
				"Material Transfer",
				stock_entry_type or self.rework_entry_type,
				posting_date,
				rework_type,
				workstation,
				rejection_reason,
				operation,
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
					ReworkOperator.actual_start,
					ReworkOperator.actual_end,
					ReworkOperator.idx,
				)
				.insert(
					frappe.generate_hash(length=10),
					name,
					"Stock Entry",
					"custom_pea_rework_operators",
					operator,
					start,
					end,
					idx,
				)
			).run()
		return name
