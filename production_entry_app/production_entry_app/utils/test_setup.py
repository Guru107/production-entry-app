from __future__ import annotations

import frappe
from frappe.test_runner import make_test_records

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


def before_tests() -> None:
	"""Bootstrap site-local ERPNext test records for deterministic local/CI runs."""
	install_test_run_cleanup()
	cleanup_reserved_benchmark_data()
	for doctype in ("Company", "Cost Center"):
		if frappe.db.exists(doctype, None):
			continue
		make_test_records(doctype, commit=True)
	_ensure_company_defaults()
	_ensure_gender_records()
