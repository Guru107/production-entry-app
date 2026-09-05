from __future__ import annotations

import datetime
from unittest.mock import patch

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime

from production_entry_app.production_entry_app import e2e_api, rework
from production_entry_app.production_entry_app.report.pending_rework import pending_rework
from production_entry_app.production_entry_app.report.rework_register import rework_register
from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
	bootstrap_manufacture_masters,
	make_direct_manufacture_entry,
	make_running_shift,
)
from production_entry_app.production_entry_app.utils.stock_entry_branch import stock_entry_has_branch_field
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	ensure_operator,
	ensure_workstation,
)


class TestReworkLifecycle(FrappeTestCase):
	def setUp(self) -> None:
		frappe.db.rollback()
		self.masters = bootstrap_manufacture_masters()
		self.suffix = frappe.generate_hash(length=6)
		self.entry_type = f"Lifecycle Rework Transfer {self.suffix}"
		self.rework_type = f"Lifecycle Rework Type {self.suffix}"
		self.workstation = f"Lifecycle Rework Workstation {self.suffix}"
		self.operator = f"Lifecycle Rework Operator {self.suffix}"
		self.expense_account = self._ensure_rework_expense_account()
		ensure_workstation(self.workstation, standard_spm=10)
		frappe.db.set_value("Workstation", self.workstation, "hour_rate", 120, update_modified=False)
		ensure_operator(self.operator)
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": self.entry_type,
				"purpose": "Material Transfer",
				"custom_pea_rework_entry": 1,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Rework Type",
				"rework_type_name": self.rework_type,
				"default_workstation": self.workstation,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_production_rejection_rework_submit_reports_and_cancel(self) -> None:
		shift = make_running_shift(self.masters)
		source = make_direct_manufacture_entry(
			self.masters,
			shift=shift.name,
			fg_qty=100,
			rejection_qty=5,
		)
		source.custom_pea_rejection_breakup[0].is_rework = 1
		source.set_posting_time = 1
		source.posting_time = "10:00:00"
		source.save(ignore_permissions=True)
		funding_entry = self._make_source_funding_entry(source)
		source.submit()

		self.assertEqual(rework.get_pending_rework(self.masters["fg_item"])[0]["pending_qty"], 5)
		pending_before = pending_rework.execute({"item_code": self.masters["fg_item"]})[1]
		self.assertEqual(pending_before[0]["derived_pending_qty"], 5)
		self.assertEqual(pending_before[0]["rejection_warehouse_balance"], 5)

		rejection_before = self._stock_qty(self.masters["rejection_warehouse"])
		good_before = self._stock_qty(self.masters["fg_warehouse"])
		rework_entry = self._make_rework_entry(shift.shift_date)
		self.assertLessEqual(self._posting_datetime(funding_entry), self._posting_datetime(source))
		self.assertLessEqual(self._posting_datetime(source), self._posting_datetime(rework_entry))
		rework_entry.insert(ignore_permissions=True)
		self.assertEqual(rework_entry.from_warehouse, self.masters["rejection_warehouse"])
		self.assertEqual(rework_entry.items[0].s_warehouse, self.masters["rejection_warehouse"])
		rework_entry.submit()

		self.assertEqual(rework.get_pending_rework(self.masters["fg_item"])[0]["pending_qty"], 0)
		self.assertEqual(self._stock_qty(self.masters["rejection_warehouse"]), rejection_before - 5)
		self.assertEqual(self._stock_qty(self.masters["fg_warehouse"]), good_before + 5)
		self.assertAlmostEqual(rework_entry.custom_pea_rework_cost, 120, places=6)
		self.assertAlmostEqual(rework_entry.items[0].additional_cost, 120, places=6)
		self.assertGreater(rework_entry.items[0].valuation_rate, rework_entry.items[0].basic_rate)

		pending_after_submit = pending_rework.execute({"item_code": self.masters["fg_item"]})[1]
		register_after_submit = rework_register.execute(
			{
				"from_date": str(shift.shift_date),
				"to_date": str(shift.shift_date),
				"item_code": self.masters["fg_item"],
			}
		)[1]
		self.assertEqual(pending_after_submit, [])
		self.assertEqual([row["rework_entry"] for row in register_after_submit], [rework_entry.name])
		self.assertEqual(register_after_submit[0]["total_qty"], 5)
		self.assertEqual(register_after_submit[0]["computed_cost"], 120)

		rework_entry.cancel()

		self.assertEqual(rework.get_pending_rework(self.masters["fg_item"])[0]["pending_qty"], 5)
		self.assertEqual(self._stock_qty(self.masters["rejection_warehouse"]), rejection_before)
		self.assertEqual(self._stock_qty(self.masters["fg_warehouse"]), good_before)
		pending_after_cancel = pending_rework.execute({"item_code": self.masters["fg_item"]})[1]
		register_after_cancel = rework_register.execute(
			{
				"from_date": str(shift.shift_date),
				"to_date": str(shift.shift_date),
				"item_code": self.masters["fg_item"],
			}
		)[1]
		self.assertEqual(pending_after_cancel[0]["derived_pending_qty"], 5)
		self.assertEqual(pending_after_cancel[0]["rejection_warehouse_balance"], 5)
		self.assertEqual(register_after_cancel, [])

	def _ensure_rework_expense_account(self) -> str:
		company = self.masters["company"]
		expense_account = frappe.db.get_value("Company", company, "default_operating_cost_account")
		if not expense_account:
			expense_account = frappe.db.get_value(
				"Account",
				{
					"company": company,
					"account_type": "Expenses Included In Valuation",
					"is_group": 0,
				},
				"name",
			)
		self.assertTrue(expense_account)
		frappe.db.set_single_value("Production Entry Settings", "rework_expense_account", expense_account)
		return expense_account

	def _make_source_funding_entry(self, source: Document) -> Document:
		items = [
			{
				"item_code": row.item_code,
				"qty": row.qty,
				"t_warehouse": row.s_warehouse,
				"basic_rate": row.basic_rate or 50,
			}
			for row in source.items
			if row.s_warehouse and float(row.qty or 0) > 0
		]
		self.assertTrue(items)
		funding_entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"company": self.masters["company"],
				"purpose": "Material Receipt",
				"stock_entry_type": "Material Receipt",
				"set_posting_time": 1,
				"posting_date": source.posting_date,
				"posting_time": "09:00:00",
				"items": items,
			}
		).insert(ignore_permissions=True)
		funding_entry.submit()
		return funding_entry

	@staticmethod
	def _posting_datetime(doc: Document) -> datetime.datetime:
		return get_datetime(f"{doc.posting_date} {doc.posting_time}")

	def test_rework_entry_saved_with_a_shift_drops_the_shift_and_its_planned_window(self) -> None:
		shift = make_running_shift(self.masters)
		doc = self._make_rework_entry(shift.shift_date)
		doc.custom_pea_shift = shift.name
		doc.custom_pea_planned_start_date = get_datetime(f"{shift.shift_date} 08:00:00")
		doc.custom_pea_planned_end_date = get_datetime(f"{shift.shift_date} 16:00:00")
		doc.custom_pea_is_late_entry = 1
		doc.insert(ignore_permissions=True)

		saved = frappe.get_doc("Stock Entry", doc.name)
		self.assertFalse(saved.get("custom_pea_shift"))
		self.assertFalse(saved.get("custom_pea_planned_start_date"))
		self.assertFalse(saved.get("custom_pea_planned_end_date"))
		self.assertFalse(saved.get("custom_pea_is_late_entry"))

	def _make_rework_entry(self, posting_date: object) -> Document:
		start = get_datetime(f"{posting_date} 10:00:00")
		end = get_datetime(f"{posting_date} 11:00:00")
		doc = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"company": self.masters["company"],
				"purpose": "Material Transfer",
				"stock_entry_type": self.entry_type,
				"from_warehouse": self.masters["rejection_warehouse"],
				"to_warehouse": self.masters["fg_warehouse"],
				"set_posting_time": 1,
				"posting_date": posting_date,
				"posting_time": "11:00:00",
				"custom_pea_rework_type": self.rework_type,
				"custom_pea_rework_workstation": self.workstation,
				"custom_pea_rework_actual_start": start,
				"custom_pea_rework_actual_end": end,
			}
		)
		if stock_entry_has_branch_field():
			doc.branch = self.masters["branch"]
		doc.append("custom_pea_rework_operators", {"operator": self.operator})
		doc.append(
			"items",
			{
				"item_code": self.masters["fg_item"],
				"qty": 5,
				"s_warehouse": self.masters["rejection_warehouse"],
				"t_warehouse": self.masters["fg_warehouse"],
			},
		)
		return doc

	def _stock_qty(self, warehouse: str) -> float:
		return float(
			frappe.db.get_value(
				"Bin",
				{"item_code": self.masters["fg_item"], "warehouse": warehouse},
				"actual_qty",
			)
			or 0
		)


class TestReworkLifecycleE2ESeed(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_e2e_seed_creates_a_real_rework_flagged_production_source(self) -> None:
		prefix = f"E2E_REWORK_LIFECYCLE_{frappe.generate_hash(length=6)}"
		try:
			with patch.object(e2e_api, "_assert_e2e_api_allowed"):
				context = e2e_api.create_e2e_rework_lifecycle_source(prefix=prefix, qty=5)

			self.assertEqual(context["pending_qty"], 5)
			self.assertEqual(context["rejection_warehouse_qty"], 5)
			self.assertEqual(context["rework_workstation"], context["workstation"])
			self.assertEqual(
				frappe.db.get_value(
					"Rejection Breakup",
					{"parent": context["source_entry"]},
					"is_rework",
				),
				1,
			)
		finally:
			e2e_api._cleanup_e2e_context(prefix)

	def test_cleanup_then_reseed_same_lifecycle_prefix_is_isolated(self) -> None:
		prefix = f"E2E_REWORK_RERUN_{frappe.generate_hash(length=6)}"
		try:
			with patch.object(e2e_api, "_assert_e2e_api_allowed"):
				first = e2e_api.create_e2e_rework_lifecycle_source(prefix=prefix, qty=5)
			first_source = first["source_entry"]

			self.assertEqual(e2e_api._cleanup_e2e_context(prefix), {"ok": True})
			self.assertFalse(frappe.db.exists("Stock Entry", first_source))

			with patch.object(e2e_api, "_assert_e2e_api_allowed"):
				second = e2e_api.create_e2e_rework_lifecycle_source(prefix=prefix, qty=5)
			self.assertTrue(frappe.db.exists("Stock Entry", second["source_entry"]))
			self.assertEqual(second["pending_qty"], 5)
		finally:
			e2e_api._cleanup_e2e_context(prefix)
