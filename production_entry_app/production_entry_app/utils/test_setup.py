from __future__ import annotations

from collections.abc import Callable
from importlib import import_module

import frappe

from production_entry_app.production_entry_app.utils.test_bootstrap import ensure_branch
from production_entry_app.production_entry_app.utils.test_cleanup import (
	cleanup_reserved_benchmark_data as _cleanup_reserved_benchmark_data,
	install_test_run_cleanup,
)


def cleanup_reserved_benchmark_data() -> None:
	"""Compatibility shim for historical benchmark cleanup entry points."""
	_cleanup_reserved_benchmark_data()


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
		from frappe.utils import now_datetime

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


def before_tests() -> None:
	"""Bootstrap site-local ERPNext test records for deterministic local/CI runs."""
	install_test_run_cleanup()
	cleanup_reserved_benchmark_data()
	if not frappe.db.exists("Company", None) or not frappe.db.exists("Cost Center", None):
		if erpnext_before_tests := _get_erpnext_before_tests():
			erpnext_before_tests()
		else:
			_bootstrap_erpnext_defaults_without_hook()
	_ensure_company_defaults()
	_ensure_branch_defaults()
	_ensure_gender_records()
