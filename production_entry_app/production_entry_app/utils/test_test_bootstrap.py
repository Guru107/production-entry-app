from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.test_bootstrap import (
	_resolve_company_from_candidates,
	bootstrap_manufacturing_test_context,
	ensure_item,
	ensure_warehouse,
	get_company_abbr,
	resolve_test_company,
)


class TestTestBootstrap(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_resolve_company_from_candidates_priority(self) -> None:
		self.assertEqual(
			_resolve_company_from_candidates(
				test_company_exists=True,
				default_company="Default Co",
				default_exists=True,
				first_company="First Co",
			),
			"_Test Company",
		)
		self.assertEqual(
			_resolve_company_from_candidates(
				test_company_exists=False,
				default_company="Default Co",
				default_exists=True,
				first_company="First Co",
			),
			"Default Co",
		)
		self.assertEqual(
			_resolve_company_from_candidates(
				test_company_exists=False,
				default_company="Missing Co",
				default_exists=False,
				first_company="First Co",
			),
			"First Co",
		)

	def test_resolve_test_company_returns_existing_company(self) -> None:
		company = resolve_test_company()
		self.assertTrue(company)
		self.assertTrue(frappe.db.exists("Company", company))
		self.assertTrue(get_company_abbr(company))

	def test_ensure_warehouse_is_idempotent(self) -> None:
		company = resolve_test_company()
		abbr = get_company_abbr(company)
		name = f"Bootstrap Warehouse - {abbr}"
		first = ensure_warehouse(name, company)
		second = ensure_warehouse(name, company)
		self.assertEqual(first, second)
		self.assertTrue(frappe.db.exists("Warehouse", first))

	def test_ensure_item_is_idempotent(self) -> None:
		item_code = "_Test Bootstrap Item"
		first = ensure_item(item_code)
		second = ensure_item(item_code)
		self.assertEqual(first, second)
		self.assertTrue(frappe.db.exists("Item", first))

	def test_bootstrap_manufacturing_test_context_has_expected_keys(self) -> None:
		context = bootstrap_manufacturing_test_context("Bootstrap")
		for key in (
			"company",
			"abbr",
			"wip_warehouse",
			"rm_warehouse",
			"fg_warehouse",
			"rejection_warehouse",
		):
			self.assertIn(key, context)
		self.assertTrue(frappe.db.exists("Company", context["company"]))
