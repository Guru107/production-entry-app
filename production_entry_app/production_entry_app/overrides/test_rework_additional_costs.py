from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.e2e_api import (
	insert_pending_rework_source,
)
from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
	before_validate_stock_entry,
	validate_stock_entry,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	ensure_branch,
	ensure_item,
	ensure_operator,
	ensure_stock,
	ensure_warehouse,
	ensure_workstation,
	resolve_test_branch,
	resolve_test_company,
	set_test_branch_warehouse_defaults,
)


class TestReworkAdditionalCosts(FrappeTestCase):
	def setUp(self) -> None:
		self.company = resolve_test_company()
		self.expense_account = frappe.db.get_value(
			"Company",
			self.company,
			"default_operating_cost_account",
		) or frappe.db.get_value(
			"Account",
			{"company": self.company, "account_type": "Expenses Included In Valuation", "is_group": 0},
			"name",
		)
		self.assertTrue(self.expense_account)
		frappe.db.set_value(
			"Company",
			self.company,
			"default_operating_cost_account",
			self.expense_account,
			update_modified=False,
		)
		frappe.db.set_single_value("Production Entry Settings", "rework_expense_account", None)
		suffix = frappe.generate_hash(length=6)
		self.stock_entry_type = f"Rework Cost Transfer {suffix}"
		self.workstation = f"Rework Cost Workstation {suffix}"
		self.rework_type = f"Rework Cost Type {suffix}"
		self.operators = [f"Rework Cost Operator {suffix} A", f"Rework Cost Operator {suffix} B"]
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"name": self.stock_entry_type,
				"purpose": "Material Transfer",
				"custom_pea_rework_entry": 1,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Rework Type",
				"rework_type_name": self.rework_type,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		ensure_workstation(self.workstation, standard_spm=10)
		frappe.db.set_value("Workstation", self.workstation, "hour_rate", 120, update_modified=False)
		for operator in self.operators:
			ensure_operator(operator)

	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_rework_cost_is_rebuilt_idempotently_without_removing_manual_costs(self) -> None:
		doc = self._make_rework_entry()
		doc.append(
			"additional_costs",
			{
				"expense_account": self.expense_account,
				"description": "Manual inspection cost",
				"amount": 25,
			},
		)

		before_validate_stock_entry(doc)
		before_validate_stock_entry(doc)

		self.assertEqual(doc.custom_pea_rework_cost, 360)
		self.assertEqual(len(doc.additional_costs), 2)
		manual_rows = [row for row in doc.additional_costs if not row.get("custom_pea_is_rework_cost")]
		owned_rows = [row for row in doc.additional_costs if row.get("custom_pea_is_rework_cost")]
		self.assertEqual(
			[(row.description, row.amount) for row in manual_rows], [("Manual inspection cost", 25)]
		)
		self.assertEqual(len(owned_rows), 1)
		self.assertEqual(owned_rows[0].expense_account, self.expense_account)
		self.assertEqual(owned_rows[0].description, "Rework Cost")
		self.assertEqual(owned_rows[0].amount, 360)

	def test_rework_expense_account_setting_takes_precedence_over_company_default(self) -> None:
		override_account = frappe.db.get_value(
			"Account",
			{
				"company": self.company,
				"root_type": "Expense",
				"is_group": 0,
				"name": ["!=", self.expense_account],
			},
			"name",
		)
		self.assertTrue(override_account)
		frappe.db.set_single_value("Production Entry Settings", "rework_expense_account", override_account)
		doc = self._make_rework_entry()

		before_validate_stock_entry(doc)

		self.assertEqual(doc.additional_costs[0].expense_account, override_account)

	def test_rework_cost_requires_an_expense_account(self) -> None:
		frappe.db.set_single_value("Production Entry Settings", "rework_expense_account", None)
		frappe.db.set_value(
			"Company", self.company, "default_operating_cost_account", None, update_modified=False
		)

		with self.assertRaisesRegex(
			frappe.ValidationError,
			"Set Rework Expense Account.*Default Operating Cost Account",
		):
			before_validate_stock_entry(self._make_rework_entry())

	def test_rework_rejects_zero_duration(self) -> None:
		doc = self._make_rework_entry()
		doc.custom_pea_rework_actual_end = doc.custom_pea_rework_actual_start

		with self.assertRaisesRegex(frappe.ValidationError, "Rework Actual End must be after"):
			validate_stock_entry(doc)

	def test_rework_cost_requires_a_complete_duration(self) -> None:
		doc = self._make_rework_entry()
		doc.custom_pea_rework_actual_end = None

		with self.assertRaisesRegex(frappe.ValidationError, "Rework duration must be greater than zero"):
			before_validate_stock_entry(doc)

	def test_rework_cost_skips_additional_cost_without_workstation(self) -> None:
		doc = self._make_rework_entry()
		doc.custom_pea_rework_workstation = None

		before_validate_stock_entry(doc)

		self.assertFalse(doc.additional_costs)

	def test_submit_uses_native_valuation_and_gl_and_cancel_reverses_them(self) -> None:
		suffix = frappe.generate_hash(length=6)
		posting_date = "2092-09-01"
		stock_account = frappe.db.get_value(
			"Account",
			{"company": self.company, "account_type": "Stock", "is_group": 0},
			"name",
		)
		stock_adjustment_account = frappe.db.get_value(
			"Account",
			{"company": self.company, "account_type": "Stock Adjustment", "is_group": 0},
			"name",
		)
		self.assertTrue(stock_account)
		self.assertTrue(stock_adjustment_account)
		frappe.db.set_value(
			"Company",
			self.company,
			{
				"enable_perpetual_inventory": 1,
				"default_inventory_account": stock_account,
				"stock_adjustment_account": stock_adjustment_account,
			},
			update_modified=False,
		)
		frappe.clear_document_cache("Company", self.company)
		frappe.local.enable_perpetual_inventory = {self.company: 1}
		item_code = ensure_item(f"_Rework Cost Item {suffix}")
		source_warehouse = ensure_warehouse(f"_Rework Cost Rejection {suffix}", self.company)
		target_warehouse = ensure_warehouse(f"_Rework Cost Target {suffix}", self.company)
		branch = ensure_branch(f"_Rework Cost Header Branch {suffix}")
		set_test_branch_warehouse_defaults(
			self.company,
			branch,
			rejection_warehouse=source_warehouse,
		)
		ensure_stock(item_code, source_warehouse, self.company, target_qty=10, posting_date=posting_date)
		insert_pending_rework_source(
			stock_entry_type=None,
			breakups=[(None, None, 10)],
			rejection_items=[item_code],
		)
		doc = self._make_rework_entry()
		doc.set_posting_time = 1
		doc.posting_date = posting_date
		doc.posting_time = "00:00:00"
		doc.branch = branch
		doc.from_warehouse = source_warehouse
		doc.to_warehouse = target_warehouse
		doc.append(
			"items",
			{
				"item_code": item_code,
				"qty": 10,
				"s_warehouse": source_warehouse,
				"t_warehouse": target_warehouse,
				"branch": branch,
			},
		)
		doc.insert(ignore_permissions=True)
		doc.submit()

		detail = doc.items[0]
		self.assertAlmostEqual(detail.additional_cost, 360, places=6)
		self.assertAlmostEqual(detail.valuation_rate - detail.basic_rate, 36, places=6)
		sles = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": doc.name, "is_cancelled": 0},
			fields=["warehouse", "actual_qty", "incoming_rate", "valuation_rate"],
		)
		incoming_sle = next(row for row in sles if row.warehouse == target_warehouse)
		outgoing_sle = next(row for row in sles if row.warehouse == source_warehouse)
		self.assertGreater(incoming_sle.incoming_rate, outgoing_sle.valuation_rate)

		gl_entries = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": doc.name, "is_cancelled": 0},
			fields=["account", "debit", "credit"],
		)
		expense_credit = sum(
			float(row.credit or 0) - float(row.debit or 0)
			for row in gl_entries
			if row.account == self.expense_account
		)
		stock_accounts = set(
			frappe.get_all(
				"Account",
				filters={"name": ["in", [row.account for row in gl_entries]], "account_type": "Stock"},
				pluck="name",
			)
		)
		stock_debit = sum(
			float(row.debit or 0) - float(row.credit or 0)
			for row in gl_entries
			if row.account in stock_accounts
		)
		self.assertAlmostEqual(expense_credit, 360, places=2)
		self.assertAlmostEqual(stock_debit, 360, places=2)

		doc.cancel()
		self.assertFalse(
			frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": doc.name, "is_cancelled": 0},
				pluck="name",
			)
		)
		self.assertTrue(
			frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": doc.name, "is_cancelled": 1},
				pluck="name",
			)
		)
		cancelled_gl_entries = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": doc.name},
			fields=["account", "debit", "credit"],
		)
		self.assertAlmostEqual(
			sum(
				float(row.credit or 0) - float(row.debit or 0)
				for row in cancelled_gl_entries
				if row.account == self.expense_account
			),
			0,
			places=2,
		)

	def _make_rework_entry(self) -> Document:
		doc = frappe.new_doc("Stock Entry")
		doc.company = self.company
		doc.purpose = "Material Transfer"
		doc.stock_entry_type = self.stock_entry_type
		doc.custom_pea_rework_type = self.rework_type
		doc.custom_pea_rework_workstation = self.workstation
		doc.custom_pea_rework_actual_start = "2026-09-01 08:00:00"
		doc.custom_pea_rework_actual_end = "2026-09-01 09:30:00"
		for operator in self.operators:
			doc.append("custom_pea_rework_operators", {"operator": operator})
		return doc
