from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.desk.query_report import run as run_query_report
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from production_entry_app.production_entry_app.joint_production import JOINT_LH_RH_STOCK_ENTRY_TYPE
from production_entry_app.production_entry_app.report.daily_rej_rework_register import (
	daily_rej_rework_register,
)
from production_entry_app.production_entry_app.test_native_permissions import (
	_ensure_user_with_exact_roles,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import resolve_test_company


class TestDailyRejReworkRegister(FrappeTestCase):
	def setUp(self) -> None:
		frappe.db.rollback()
		self.suffix = frappe.generate_hash(length=6)
		self.rework_entry_type = f"RejReg Rework {self.suffix}"
		self.normal_entry_type = f"RejReg Normal {self.suffix}"
		self.item_a = f"_Test RejReg A {self.suffix}"
		self.item_b = f"_Test RejReg B {self.suffix}"

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_columns_and_row_values_with_same_day_item_rework_match(self) -> None:
		day = "2092-06-10"
		shift = self._insert_shift(day, "1", status="Completed")
		bom_a = self._insert_bom(self.item_a)
		entry_a = self._insert_production_entry(
			shift_name=shift, posting_date=day, fg_qty=1000, bom=bom_a, rejection_qty=10
		)
		# Day total includes production entries with no rejections of their own.
		self._insert_production_entry(shift_name=shift, posting_date=day, fg_qty=500, bom=bom_a)
		self._insert_rejection_item(entry_a, self.item_a, 10)
		self._insert_breakup(entry_a, [("", "Burr", 5, 0), ("", "Crack", 3, 0), ("", "Dent", 2, 1)])
		responsible = self._insert_employee("RejReg Responsible")
		reinspector = self._insert_employee("RejReg Reinspector")
		self._insert_rework_entry(
			rework_date=day,
			items=[(self.item_a, 4)],
			operators=[
				("Operator A", f"{day} 08:00:00", f"{day} 09:00:00"),
				("Operator B", f"{day} 09:00:00", f"{day} 09:30:00"),
			],
			responsibility=[responsible],
			reinspection=[reinspector],
		)

		columns, rows = daily_rej_rework_register.execute({"from_date": day, "to_date": day})
		precision = daily_rej_rework_register.get_system_float_precision()

		self.assertEqual(
			[column["fieldname"] for column in columns],
			[
				"production_date",
				"day_fg_qty",
				"operator_count",
				"rework_hours",
				"defective_item_code",
				"rejection_reason",
				"rejection_qty",
				"rework_qty",
				"rejection_stage",
				"finished_goods_qty",
				"rej_ppm",
				"rework_ppm",
				"responsibility_remark",
				"reinspection",
				"operator_name",
			],
		)
		self.assertEqual(len(rows), 6)
		header = rows[0]
		self.assertEqual(header["bold"], 1)
		self.assertEqual(str(header["production_date"]), day)
		self.assertEqual(header["day_fg_qty"], 1500)
		self.assertEqual(header["operator_count"], 2)
		self.assertEqual(header["rework_hours"], 1.5)
		item_row = rows[1]
		self.assertEqual(item_row["bold"], 1)
		# Blank breakup item resolves to the entry's single rejection item.
		self.assertEqual(item_row["defective_item_code"], self.item_a)
		self.assertEqual(item_row["rework_qty"], 4)
		self.assertAlmostEqual(item_row["rework_ppm"], flt(4 / 1500 * 1_000_000, precision))
		self.assertEqual(item_row["operator_count"], 2)
		self.assertEqual(item_row["rework_hours"], 1.5)
		self.assertEqual(item_row["operator_name"], "Operator A, Operator B")
		# Employees show by name, not by ID.
		self.assertEqual(item_row["responsibility_remark"], f"RejReg Responsible {self.suffix}")
		self.assertEqual(item_row["reinspection"], f"RejReg Reinspector {self.suffix}")
		# The item's day-total OK quantity (produced minus rejected), matching the
		# Shift's aggregate-entries view: (1000-10) + 500.
		self.assertEqual(item_row["finished_goods_qty"], 1490)
		details = rows[2:5]
		self.assertEqual([row["rejection_reason"] for row in details], ["Burr", "Crack", "Dent"])
		for detail in details:
			self.assertIsNone(detail.get("defective_item_code"))
			self.assertNotIn("finished_goods_qty", detail)
		burr = details[0]
		self.assertEqual(burr["rejection_qty"], 5)
		self.assertEqual(burr["rework_qty"], 0)
		self.assertEqual(burr["rework_ppm"], 0)
		self.assertEqual(burr["rejection_stage"], self.normal_entry_type)
		self.assertAlmostEqual(burr["rej_ppm"], flt(5 / 1500 * 1_000_000, precision))
		self.assertEqual(details[1]["rejection_qty"], 3)
		# A reworkable (is_rework) breakup line is not rejection: it shows its qty
		# under Rework Qty; the actual rework block lives on the item group row.
		dent = details[2]
		self.assertEqual(dent["rejection_qty"], 0)
		self.assertEqual(dent["rej_ppm"], 0)
		self.assertEqual(dent["rework_qty"], 2)
		self.assertAlmostEqual(dent["rework_ppm"], flt(2 / 1500 * 1_000_000, precision))
		subtotal = rows[5]
		self.assertEqual(subtotal["bold"], 1)
		self.assertEqual(subtotal["day_fg_qty"], 1500)
		self.assertEqual(subtotal["operator_count"], 2)
		self.assertEqual(subtotal["rework_hours"], 1.5)
		# The subtotal sums the lines above it: rejection 5+3, declared reworkable 2.
		self.assertEqual(subtotal["rejection_qty"], 8)
		self.assertEqual(subtotal["rework_qty"], 2)
		self.assertAlmostEqual(subtotal["rej_ppm"], flt(8 / 1500 * 1_000_000, precision))
		self.assertAlmostEqual(subtotal["rework_ppm"], flt(2 / 1500 * 1_000_000, precision))

	def test_lines_group_by_item_within_a_day(self) -> None:
		day = "2092-06-12"
		shift = self._insert_shift(day, "1", status="Completed")
		entry = self._insert_production_entry(
			shift_name=shift, posting_date=day, fg_qty=100, bom=self._insert_bom(self.item_a)
		)
		self._insert_rejection_item(entry, self.item_a, 8)
		self._insert_rejection_item(entry, self.item_b, 2)
		self._insert_breakup(
			entry,
			[(self.item_b, "Burr", 2, 1), (self.item_a, "Crack", 3, 0), (self.item_a, "Burr", 5, 0)],
		)
		self._insert_rework_entry(
			rework_date=day,
			items=[(self.item_a, 4), (self.item_b, 1)],
			operators=[("Operator A", f"{day} 08:00:00", f"{day} 09:00:00")],
		)

		rows = daily_rej_rework_register.execute({"from_date": day, "to_date": day})[1]

		# Day header, item A group (2 lines), item B group (1 line), day subtotal.
		self.assertEqual(len(rows), 7)
		item_rows = [row for row in rows if row.get("defective_item_code")]
		self.assertEqual([row["defective_item_code"] for row in item_rows], [self.item_a, self.item_b])
		self.assertEqual(item_rows[0]["rework_qty"], 4)
		self.assertEqual(item_rows[1]["rework_qty"], 1)
		# Item A was produced that day (fg 100 via its BOM); item B was not.
		self.assertEqual(item_rows[0]["finished_goods_qty"], 100)
		self.assertEqual(item_rows[1]["finished_goods_qty"], 0)
		details = [row for row in rows if row.get("rejection_reason")]
		# Lines order within the day follows their item group, keeping breakup row order.
		self.assertEqual(
			[(row["rejection_reason"], row["rejection_qty"], row["rework_qty"]) for row in details],
			[("Crack", 3, 0), ("Burr", 5, 0), ("Burr", 0, 2)],
		)
		subtotal = rows[-1]
		self.assertEqual(subtotal["rejection_qty"], 8)
		# Declared reworkable: only item B's Burr line (qty 2), not the actual 5 reworked.
		self.assertEqual(subtotal["rework_qty"], 2)

	def test_rework_matches_only_same_day_and_same_item(self) -> None:
		day = "2092-06-11"
		shift = self._insert_shift(day, "1", status="Completed")
		entry = self._insert_production_entry(shift_name=shift, posting_date=day, fg_qty=100)
		self._insert_rejection_item(entry, self.item_a, 5)
		self._insert_breakup(entry, [(self.item_a, "Burr", 5)])
		# Later day: no match.
		self._insert_rework_entry(
			rework_date="2092-06-12",
			items=[(self.item_a, 2)],
			operators=[("Operator A", "2092-06-12 08:00:00", "2092-06-12 09:00:00")],
		)
		# Other item on the same day: no match.
		self._insert_rework_entry(
			rework_date=day,
			items=[(self.item_b, 3)],
			operators=[("Operator B", f"{day} 08:00:00", f"{day} 09:00:00")],
		)
		# Draft rework entry for the right day and item: no match.
		self._insert_rework_entry(
			rework_date=day,
			items=[(self.item_a, 1)],
			operators=[("Operator C", f"{day} 08:00:00", f"{day} 09:00:00")],
			docstatus=0,
		)

		rows = daily_rej_rework_register.execute({"from_date": day, "to_date": day})[1]

		self.assertEqual(len(rows), 4)
		# The day header covers ALL the day's submitted rework, including item B's,
		# even though item B has no rejection line that day. Drafts stay excluded.
		header = rows[0]
		self.assertEqual(header["operator_count"], 1)
		self.assertEqual(header["rework_hours"], 1.0)
		item_row = rows[1]
		self.assertEqual(item_row["defective_item_code"], self.item_a)
		self.assertEqual(item_row["rework_qty"], 0)
		self.assertEqual(item_row["rework_ppm"], 0)
		self.assertEqual(item_row["operator_count"], 0)
		self.assertEqual(item_row["rework_hours"], 0)
		self.assertEqual(item_row["operator_name"], "")
		self.assertEqual(rows[2]["rejection_reason"], "Burr")
		self.assertEqual(rows[2]["rejection_qty"], 5)

	def test_rework_entry_read_rejects_unbounded_result(self) -> None:
		day = "2092-07-21"
		for _unused in range(2):
			self._insert_rework_entry(
				rework_date=day,
				items=[(self.item_a, 1)],
				operators=[("Operator A", f"{day} 08:00:00", f"{day} 09:00:00")],
			)

		with self.assertRaisesRegex(frappe.ValidationError, "matches more than 1"):
			daily_rej_rework_register._get_rework_by_day_item(
				[{"day": frappe.utils.getdate(day), "defective_item_code": self.item_a}],
				max_rework_entries=1,
			)

	def test_single_rejection_item_lookup_skipped_when_breakup_items_are_set(self) -> None:
		day = "2092-07-22"
		shift = self._insert_shift(day, "1", status="Completed")
		entry = self._insert_production_entry(shift_name=shift, posting_date=day, fg_qty=100)
		self._insert_breakup(entry, [(self.item_a, "Burr", 5)])

		with patch.object(daily_rej_rework_register, "_get_single_rejection_items") as fallback_lookup:
			rows = daily_rej_rework_register.execute({"from_date": day, "to_date": day})[1]

		fallback_lookup.assert_not_called()
		self.assertEqual(rows[1]["defective_item_code"], self.item_a)

	def test_unresolvable_blank_breakup_item_is_logged(self) -> None:
		day = "2092-07-23"
		shift = self._insert_shift(day, "1", status="Completed")
		entry = self._insert_production_entry(shift_name=shift, posting_date=day, fg_qty=100)
		# Legacy shape: blank breakup item and no rejection item rows to resolve it.
		self._insert_breakup(entry, [("", "Burr", 5)])

		with patch.object(frappe, "log_error") as log_error:
			rows = daily_rej_rework_register.execute({"from_date": day, "to_date": day})[1]

		self.assertEqual(log_error.call_count, 1)
		self.assertIn(entry, log_error.call_args.kwargs["message"])
		self.assertEqual(rows[1]["defective_item_code"], "")
		self.assertEqual(rows[1]["rework_qty"], 0)

	def test_scope_excludes_drafts_running_shifts_and_generic_repacks(self) -> None:
		day = "2092-06-15"
		completed_shift = self._insert_shift(day, "1", status="Completed")
		running_shift = self._insert_shift(day, "2", status="Running")
		draft_entry = self._insert_production_entry(
			shift_name=completed_shift, posting_date=day, fg_qty=100, docstatus=0
		)
		self._insert_breakup(draft_entry, [(self.item_a, "Burr", 5)])
		running_entry = self._insert_production_entry(shift_name=running_shift, posting_date=day, fg_qty=100)
		self._insert_breakup(running_entry, [(self.item_a, "Burr", 5)])
		repack_entry = self._insert_production_entry(
			shift_name=completed_shift,
			posting_date=day,
			fg_qty=100,
			purpose="Repack",
			stock_entry_type=self.rework_entry_type,
		)
		self._insert_breakup(repack_entry, [(self.item_a, "Burr", 5)])

		rows = daily_rej_rework_register.execute({"from_date": day, "to_date": day})[1]

		self.assertEqual(rows, [])

	def test_filters_restrict_rows(self) -> None:
		day = "2092-06-20"
		shift = self._insert_shift(day, "1", status="Completed")
		entry = self._insert_production_entry(shift_name=shift, posting_date=day, fg_qty=100)
		self._insert_rejection_item(entry, self.item_a, 8)
		self._insert_breakup(entry, [("", "Burr", 5), ("", "Crack", 3)])

		date_range = {"from_date": day, "to_date": day}
		details = lambda rows: [row for row in rows if row.get("rejection_reason")]  # noqa: E731
		rows = daily_rej_rework_register.execute({**date_range, "item_code": self.item_a})[1]
		self.assertEqual(len(details(rows)), 2)
		rows = daily_rej_rework_register.execute({**date_range, "item_code": self.item_b})[1]
		self.assertEqual(rows, [])
		rows = daily_rej_rework_register.execute({**date_range, "rejection_reason": "Crack"})[1]
		self.assertEqual([row["rejection_reason"] for row in details(rows)], ["Crack"])
		# The Operation filter matches the resolved Rejection Stage: the Stock Entry
		# Type for normal Manufacture entries.
		rows = daily_rej_rework_register.execute(
			{**date_range, "custom_pea_operation": self.normal_entry_type}
		)[1]
		self.assertEqual(len(details(rows)), 2)
		rows = daily_rej_rework_register.execute({**date_range, "custom_pea_operation": "No Such Operation"})[
			1
		]
		self.assertEqual(rows, [])

	def test_joint_entry_uses_operation_as_rejection_stage(self) -> None:
		day = "2092-06-25"
		shift = self._insert_shift(day, "1", status="Completed")
		bom = self._insert_bom(self.item_a)
		entry = self._insert_production_entry(
			shift_name=shift,
			posting_date=day,
			fg_qty=0,
			purpose="Repack",
			stock_entry_type=JOINT_LH_RH_STOCK_ENTRY_TYPE,
			operation="Blanking",
			lh_bom=bom,
			rh_bom=bom,
			lh_gross=40,
			rh_gross=60,
			lh_rejection=2,
		)
		self._insert_breakup(entry, [(self.item_a, "Burr", 2)])

		rows = daily_rej_rework_register.execute({"from_date": day, "to_date": day})[1]

		self.assertEqual(len(rows), 4)
		row = rows[2]
		self.assertEqual(row["rejection_stage"], "Blanking")
		# OK qty: (40-2) + 60.
		self.assertEqual(rows[1]["finished_goods_qty"], 98)
		self.assertEqual(rows[1]["day_fg_qty"], 100)
		self.assertEqual(row["rej_ppm"], 20000)

	def test_ppm_divides_raw_quantities_before_display_rounding(self) -> None:
		# At display precision 2, rounding inputs first would give 0.01/1 -> 10000.
		day = "2092-07-14"
		shift = self._insert_shift(day, "1", status="Completed")
		entry = self._insert_production_entry(shift_name=shift, posting_date=day, fg_qty=1)
		self._insert_rejection_item(entry, self.item_a, 0.006)
		self._insert_breakup(entry, [(self.item_a, "Burr", 0.006)])

		with patch.object(daily_rej_rework_register, "get_system_float_precision", return_value=2):
			rows = daily_rej_rework_register.execute({"from_date": day, "to_date": day})[1]

		self.assertEqual(rows[2]["rejection_qty"], 0.01)
		self.assertEqual(rows[2]["rej_ppm"], 6000)

	def test_pea_read_only_runs_report_without_stock_entry_permission(self) -> None:
		frappe.reload_doc("production_entry_app", "report", "daily_rej_rework_register")
		frappe.reload_doc("production_entry_app", "doctype", "shift")
		user = f"test_rej_rework_register_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(user, ("PEA Read Only",))
		day = "2092-08-10"
		shift = self._insert_shift(day, "1", status="Completed")
		entry = self._insert_production_entry(shift_name=shift, posting_date=day, fg_qty=100)
		self._insert_rejection_item(entry, self.item_a, 2)
		self._insert_breakup(entry, [(self.item_a, "Burr", 2)])
		try:
			frappe.set_user(user)
			self.assertFalse(frappe.has_permission("Stock Entry", "read"))
			result = run_query_report(
				"Daily Rej Rework Register",
				filters={"from_date": day, "to_date": day},
				ignore_prepared_report=True,
			)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(len([row for row in result["result"] if row.get("rejection_reason")]), 1)
		row = next(row for row in result["result"] if row.get("rejection_reason"))
		self.assertEqual(row["rejection_qty"], 2.0)

	def _insert_employee(self, first_name: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": f"{first_name} {self.suffix}",
					"company": resolve_test_company(),
					"gender": "Male",
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

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
		name = f"SHIFT-REJREG-{self.suffix}-{shift_date}-{label}"
		Shift = frappe.qb.DocType("Shift")
		(
			frappe.qb.into(Shift)
			.columns(Shift.name, Shift.docstatus, Shift.status, Shift.shift_date)
			.insert(name, 0, status, shift_date)
		).run()
		return name

	def _insert_bom(self, item_code: str) -> str:
		name = f"BOM-{item_code}-{frappe.generate_hash(length=6)}"
		BOM = frappe.qb.DocType("BOM")
		(frappe.qb.into(BOM).columns(BOM.name, BOM.docstatus, BOM.item).insert(name, 1, item_code)).run()
		return name

	def _insert_production_entry(
		self,
		*,
		shift_name: str,
		posting_date: str,
		fg_qty: float,
		purpose: str = "Manufacture",
		stock_entry_type: str | None = None,
		operation: str | None = None,
		bom: str | None = None,
		lh_bom: str | None = None,
		rh_bom: str | None = None,
		lh_gross: float | None = None,
		rh_gross: float | None = None,
		rejection_qty: float | None = None,
		lh_rejection: float | None = None,
		rh_rejection: float | None = None,
		docstatus: int = 1,
	) -> str:
		self._ensure_entry_types()
		name = f"REJREG-PROD-{frappe.generate_hash(length=10)}"
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
		for column, value in (
			(StockEntry.custom_pea_operation, operation),
			(StockEntry.bom_no, bom),
			(StockEntry.custom_pea_lh_bom, lh_bom),
			(StockEntry.custom_pea_rh_bom, rh_bom),
			(StockEntry.custom_pea_lh_gross_qty, lh_gross),
			(StockEntry.custom_pea_rh_gross_qty, rh_gross),
			(StockEntry.custom_pea_rejection_qty, rejection_qty),
			(StockEntry.custom_pea_lh_rejection_qty, lh_rejection),
			(StockEntry.custom_pea_rh_rejection_qty, rh_rejection),
		):
			if value is not None:
				columns.append(column)
				values.append(value)
		frappe.qb.into(StockEntry).columns(*columns).insert(*values).run()
		return name

	def _insert_rejection_item(self, parent: str, item_code: str, qty: float) -> None:
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
				StockEntryDetail.idx,
			)
			.insert(
				frappe.generate_hash(length=10),
				parent,
				"Stock Entry",
				"items",
				item_code,
				qty,
				1,
				1,
			)
		).run()

	def _insert_breakup(self, parent: str, rows: list[tuple]) -> None:
		RejectionBreakup = frappe.qb.DocType("Rejection Breakup")
		for idx, row in enumerate(rows, start=1):
			item_code, rejection_reason, qty = row[0], row[1], row[2]
			is_rework = row[3] if len(row) > 3 else 0
			(
				frappe.qb.into(RejectionBreakup)
				.columns(
					RejectionBreakup.name,
					RejectionBreakup.parent,
					RejectionBreakup.parenttype,
					RejectionBreakup.parentfield,
					RejectionBreakup.custom_pea_rb_item_code,
					RejectionBreakup.rejection_reason,
					RejectionBreakup.qty,
					RejectionBreakup.is_rework,
					RejectionBreakup.idx,
				)
				.insert(
					frappe.generate_hash(length=10),
					parent,
					"Stock Entry",
					"custom_pea_rejection_breakup",
					item_code,
					rejection_reason,
					qty,
					is_rework,
					idx,
				)
			).run()

	def _insert_rework_entry(
		self,
		*,
		rework_date: str,
		items: list[tuple[str, float]],
		operators: list[tuple[str, str | None, str | None]],
		responsibility: list[str] | None = None,
		reinspection: list[str] | None = None,
		docstatus: int = 1,
	) -> str:
		self._ensure_entry_types()
		name = f"REJREG-REW-{frappe.generate_hash(length=10)}"
		StockEntry = frappe.qb.DocType("Stock Entry")
		(
			frappe.qb.into(StockEntry)
			.columns(
				StockEntry.name,
				StockEntry.docstatus,
				StockEntry.purpose,
				StockEntry.stock_entry_type,
				StockEntry.posting_date,
				StockEntry.custom_pea_rework_date,
			)
			.insert(name, docstatus, "Material Transfer", self.rework_entry_type, rework_date, rework_date)
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
		for idx, (operator, start, end) in enumerate(operators, start=1):
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
		for doctype, parentfield, employees in (
			("Rework Responsibility Employee", "custom_pea_rework_responsibility", responsibility),
			("Rework Reinspection Employee", "custom_pea_rework_reinspection", reinspection),
		):
			table = frappe.qb.DocType(doctype)
			for idx, employee in enumerate(employees or [], start=1):
				(
					frappe.qb.into(table)
					.columns(
						table.name,
						table.parent,
						table.parenttype,
						table.parentfield,
						table.employee,
						table.idx,
					)
					.insert(
						frappe.generate_hash(length=10),
						name,
						"Stock Entry",
						parentfield,
						employee,
						idx,
					)
				).run()
		return name
