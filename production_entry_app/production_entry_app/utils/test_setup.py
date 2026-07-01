from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any

import frappe
from frappe.utils import now_datetime

from production_entry_app.production_entry_app.utils.test_bootstrap import ensure_branch
from production_entry_app.production_entry_app.utils.test_cleanup import install_test_run_cleanup

_ERPNEXT_TEST_FISCAL_YEAR_START = 2012
_ERPNEXT_TEST_FISCAL_YEAR_LOOKAHEAD_YEARS = 25


def _ensure_company_defaults() -> None:
	company = "_Test Company" if frappe.db.exists("Company", "_Test Company") else None
	if not company:
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not company:
		return

	frappe.db.set_single_value("Global Defaults", "default_company", company)
	frappe.defaults.set_user_default("company", company)


def _ensure_gender_records() -> None:
	for gender in (
		"Male",
		"Female",
		"Non-Conforming",
		"Transgender",
		"Genderqueer",
		"Other",
		"Prefer not to say",
	):
		if frappe.db.exists("Gender", gender):
			continue
		frappe.get_doc({"doctype": "Gender", "gender": gender}).insert(ignore_permissions=True)


def _ensure_branch_defaults() -> None:
	branch = ensure_branch("_Test Branch")
	frappe.defaults.set_user_default("branch", branch)
	frappe.defaults.set_user_default("Branch", branch)


def _run_installed_app_before_tests(app_name: str) -> None:
	if app_name not in frappe.get_installed_apps():
		return

	for hook in frappe.get_hooks("before_tests", app_name=app_name):
		before_tests = frappe.get_attr(hook)
		if callable(before_tests):
			before_tests()


def _get_erpnext_before_tests() -> Callable[[], None] | None:
	try:
		erpnext_setup_utils = import_module("erpnext.setup.utils")
	except ImportError:
		return None

	before_tests = getattr(erpnext_setup_utils, "before_tests", None)
	return before_tests if callable(before_tests) else None


def _bootstrap_erpnext_defaults_without_hook() -> None:
	if not frappe.db.exists("Company", None):
		from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

		current_year = now_datetime().year
		setup_complete(
			{
				"currency": "USD",
				"full_name": "Test User",
				"company_name": "_Test Company",
				"timezone": "America/New_York",
				"company_abbr": "_TC",
				"industry": "Manufacturing",
				"country": "United States",
				"fy_start_date": f"{current_year}-01-01",
				"fy_end_date": f"{current_year}-12-31",
				"language": "english",
				"company_tagline": "Testing",
				"email": "test@erpnext.com",
				"password": "test",
				"chart_of_accounts": "Standard",
			}
		)

	try:
		erpnext_setup_utils = import_module("erpnext.setup.utils")
	except ImportError:
		erpnext_setup_utils = None

	for fn_name in ("_enable_all_roles_for_admin", "set_defaults_for_tests"):
		fn = getattr(erpnext_setup_utils, fn_name, None) if erpnext_setup_utils else None
		if callable(fn):
			fn()

	frappe.db.commit()  # nosemgrep: frappe-manual-commit - test bootstrap must persist baseline fixtures


def _get_company_for_existing_fiscal_years() -> str | None:
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if company:
		return company

	return frappe.db.get_value("Company", {}, "name", order_by="creation asc")


def _scope_global_fiscal_years_for_erpnext_tests() -> None:
	meta = frappe.get_meta("Fiscal Year", cached=True)
	if not meta.has_field("companies"):
		return

	company = _get_company_for_existing_fiscal_years()
	if not company:
		return

	current_year = now_datetime().year
	window_start = f"{_ERPNEXT_TEST_FISCAL_YEAR_START}-01-01"
	window_end = f"{current_year + _ERPNEXT_TEST_FISCAL_YEAR_LOOKAHEAD_YEARS - 1}-12-31"
	fiscal_years = frappe.get_all(
		"Fiscal Year",
		filters={
			"year_start_date": ("<=", window_end),
			"year_end_date": (">=", window_start),
		},
		fields=["name"],
	)

	for fiscal_year in fiscal_years:
		if fiscal_year.name.startswith("_Test "):
			continue
		if frappe.db.exists("Fiscal Year Company", {"parent": fiscal_year.name}):
			continue

		doc = frappe.get_doc("Fiscal Year", fiscal_year.name)
		if doc.get("companies"):
			continue
		doc.append("companies", {"company": company})
		doc.save(ignore_permissions=True)


def _install_skip_test_records_compat() -> None:
	if not frappe.flags.skip_test_records:
		return

	try:
		from frappe.tests import utils as test_utils
		from frappe.tests.utils import generators
	except ImportError:
		return

	original_make_test_records = getattr(test_utils, "make_test_records", None)
	if not callable(original_make_test_records):
		return
	if getattr(original_make_test_records, "_production_entry_skip_aware", False) is True:
		return

	def make_test_records(doctype: str, *args: Any, **kwargs: Any) -> Any:
		if frappe.flags.skip_test_records:
			return []
		return original_make_test_records(doctype, *args, **kwargs)

	make_test_records._production_entry_skip_aware = True
	test_utils.make_test_records = make_test_records
	generators.make_test_records = make_test_records


def before_tests() -> None:
	"""Bootstrap site-local ERPNext test records for deterministic local/CI runs."""
	install_test_run_cleanup()
	if not frappe.db.exists("Company", None) or not frappe.db.exists("Cost Center", None):
		if erpnext_before_tests := _get_erpnext_before_tests():
			erpnext_before_tests()
		else:
			_bootstrap_erpnext_defaults_without_hook()
	_scope_global_fiscal_years_for_erpnext_tests()
	_run_installed_app_before_tests("india_compliance")
	_install_skip_test_records_compat()
	_ensure_company_defaults()
	_ensure_branch_defaults()
	_ensure_gender_records()
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - test bootstrap must persist cross-app setup
