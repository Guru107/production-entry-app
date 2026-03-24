from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.test_bootstrap import (
	_resolve_company_from_candidates,
	bootstrap_manufacturing_test_context,
	ensure_default_bom,
	ensure_department,
	ensure_downtime_reason,
	ensure_item,
	ensure_operator,
	ensure_rejection_reason,
	ensure_warehouse,
	ensure_workstation,
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

	def test_resolve_test_company_error_mentions_before_tests(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.utils.test_bootstrap._resolve_company_from_candidates",
			return_value=None,
		):
			with self.assertRaisesRegex(frappe.ValidationError, "before_tests"):
				resolve_test_company()

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

	def test_ensure_department_filters_existing_by_company(self) -> None:
		class _Meta:
			def has_field(self, fieldname: str) -> bool:
				return fieldname == "company"

		with patch(
			"production_entry_app.production_entry_app.utils.test_bootstrap.frappe.db.exists",
			return_value=False,
		):
			with patch(
				"production_entry_app.production_entry_app.utils.test_bootstrap.frappe.get_meta",
				return_value=_Meta(),
			):
				with patch(
					"production_entry_app.production_entry_app.utils.test_bootstrap.frappe.get_all",
					return_value=["Dept A - TC"],
				) as get_all:
					result = ensure_department("Dept A", company="Target Company")

		self.assertEqual(result, "Dept A - TC")
		get_all.assert_called_once_with(
			"Department",
			filters={"department_name": "Dept A", "company": "Target Company"},
			limit=1,
			pluck="name",
		)

	def test_ensure_default_bom_filters_existing_by_company(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.utils.test_bootstrap.frappe.db.get_value",
			return_value="BOM-TEST-0001",
		) as get_value:
			self.assertEqual(
				ensure_default_bom(fg_item="_Test FG", rm_item="_Test RM", company="Target Company"),
				"BOM-TEST-0001",
			)
		get_value.assert_called_once_with(
			"BOM",
			{
				"item": "_Test FG",
				"company": "Target Company",
				"is_default": 1,
				"is_active": 1,
				"docstatus": 1,
			},
			"name",
		)

	def test_ensure_operator_is_idempotent(self) -> None:
		name = "Bootstrap Operator"
		ensure_operator(name)
		ensure_operator(name)
		self.assertTrue(frappe.db.exists("Operator", name))

	def test_ensure_workstation_updates_existing_standard_spm(self) -> None:
		name = "Bootstrap Workstation"
		ensure_workstation(name, standard_spm=2)
		ensure_workstation(name, standard_spm=7)
		standard_spm = frappe.db.get_value("Workstation", name, "custom_standard_spm")
		self.assertEqual(float(standard_spm), 7.0)

	def test_reason_helpers_are_idempotent(self) -> None:
		ensure_rejection_reason("Bootstrap Rejection")
		ensure_rejection_reason("Bootstrap Rejection")
		self.assertTrue(frappe.db.exists("Rejection Reason", "Bootstrap Rejection"))
		ensure_downtime_reason("Bootstrap Downtime")
		ensure_downtime_reason("Bootstrap Downtime")
		self.assertTrue(frappe.db.exists("Downtime Reason", "Bootstrap Downtime"))

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

	def test_bootstrap_manufacturing_test_context_resets_shift_warehouse_defaults(self) -> None:
		company = resolve_test_company()
		abbr = get_company_abbr(company)
		stale_wip = ensure_warehouse(f"Bootstrap Stale WIP - {abbr}", company)
		stale_rejection = ensure_warehouse(f"Bootstrap Stale Rejection - {abbr}", company)
		frappe.db.set_single_value("Manufacturing Settings", "shift_wip_warehouse", stale_wip)
		frappe.db.set_single_value("Manufacturing Settings", "shift_rejection_warehouse", stale_rejection)

		context = bootstrap_manufacturing_test_context("Bootstrap Fresh")

		self.assertEqual(
			frappe.db.get_single_value("Manufacturing Settings", "shift_wip_warehouse"),
			context["wip_warehouse"],
		)
		self.assertEqual(
			frappe.db.get_single_value("Manufacturing Settings", "shift_rejection_warehouse"),
			context["rejection_warehouse"],
		)

	def test_standard_rejection_reason_fixtures_exist(self) -> None:
		expected = [
			"Double Stroke",
			"Part Shift",
			"Piercing Shift",
			"Blank Cut",
			"Crack",
			"Part Dent/Damage",
			"Taper Shearing",
			"Burr",
		]
		for name in expected:
			self.assertTrue(frappe.db.exists("Rejection Reason", name), msg=f"Missing fixture: {name}")
