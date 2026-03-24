from __future__ import annotations

from collections.abc import Callable
from importlib import import_module

import frappe

from production_entry_app.production_entry_app.utils.test_bootstrap import ensure_branch
from production_entry_app.production_entry_app.utils.test_cleanup import (
	cleanup_reserved_benchmark_data,
	install_test_run_cleanup,
)


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


def before_tests() -> None:
	"""Bootstrap site-local ERPNext test records for deterministic local/CI runs."""
	install_test_run_cleanup()
	cleanup_reserved_benchmark_data()
	if not frappe.db.exists("Company", None) or not frappe.db.exists("Cost Center", None):
		if erpnext_before_tests := _get_erpnext_before_tests():
			erpnext_before_tests()
	_ensure_company_defaults()
	_ensure_branch_defaults()
	_ensure_gender_records()
