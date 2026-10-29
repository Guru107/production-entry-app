from __future__ import annotations

import os
from typing import Any

import frappe
from frappe.utils import cint

from production_entry_app.production_entry_app import e2e_api
from production_entry_app.production_entry_app.utils import test_bootstrap, test_cleanup
from production_entry_app.production_entry_app.utils.ephemeral_test_site import is_ephemeral_site_name

_PERSISTENT_DEV_TEST_DATE_CUTOFF: str = "2090-01-01"
_RESERVED_CLEANUP_ROUNDS: int = 3


def should_run_persistent_dev_cleanup() -> bool:
	"""Run full dev-bench cleanup on local persistent sites, not CI ephemeral sites."""
	if is_ephemeral_site_name(frappe.local.site):
		return False
	if os.environ.get("CI"):
		return False
	return bool(cint(getattr(frappe.conf, "allow_e2e_tests", 0)))


def cleanup_persistent_dev_site_if_applicable() -> dict[str, Any] | None:
	if not should_run_persistent_dev_cleanup():
		return None
	return cleanup_persistent_dev_site_test_data()


def cleanup_persistent_dev_site_test_data() -> dict[str, Any]:
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	frappe.in_test = True
	try:
		_purge_future_transactional_data()
		_purge_test_master_data()
		deleted_users = _delete_example_com_test_users()
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise
	return {**_remaining_test_counts(), "deleted_users": deleted_users}


def _cancel_delete_stock_entries(names: list[str]) -> None:
	seen: set[str] = set()
	for name in names:
		if not name or name in seen:
			continue
		seen.add(name)
		if not frappe.db.exists("Stock Entry", name):
			continue
		try:
			e2e_api._safe_cancel_and_delete("Stock Entry", name, context="persistent_dev_cleanup")
		except Exception:
			docstatus = frappe.db.get_value("Stock Entry", name, "docstatus")
			if docstatus == 1:
				try:
					doc = frappe.get_doc("Stock Entry", name)
					doc.flags.ignore_permissions = True
					doc.cancel()
				except Exception:
					pass
			e2e_api._delete_e2e_stock_entry_rows(name)


def _stock_entries_with_test_items() -> list[str]:
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT sed.parent
		FROM `tabStock Entry Detail` sed
		INNER JOIN `tabStock Entry` se ON se.name = sed.parent
		WHERE se.docstatus != 2
		  AND (
		    sed.item_code LIKE '_E2E%%'
		    OR sed.item_code LIKE '_Test%%'
		    OR sed.item_code LIKE '_RejReg%%'
		    OR sed.item_code LIKE '\\_%%\\_FG\\_Item' ESCAPE '\\\\'
		    OR sed.item_code LIKE '\\_%%\\_RM\\_Item' ESCAPE '\\\\'
		  )
		""",
		as_list=True,
	)
	return [row[0] for row in rows]


def _is_test_item_code(item_code: str) -> bool:
	if not item_code.startswith("_"):
		return False
	if item_code.startswith(("_Test", "_E2E", "_RejReg", "_Lifecycle")):
		return True
	return "_FG_Item" in item_code or "_RM_Item" in item_code or "_Joint_" in item_code


def _ensure_fiscal_years_for_test_stock_entries() -> None:
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT posting_date, company, custom_pea_rework_date
		FROM `tabStock Entry`
		WHERE posting_date >= %s OR custom_pea_rework_date >= %s
		""",
		(_PERSISTENT_DEV_TEST_DATE_CUTOFF, _PERSISTENT_DEV_TEST_DATE_CUTOFF),
		as_dict=True,
	)
	for row in rows:
		if row.posting_date:
			test_bootstrap.ensure_fiscal_year_for_date(str(row.posting_date), row.company)
		if row.get("custom_pea_rework_date"):
			test_bootstrap.ensure_fiscal_year_for_date(str(row.custom_pea_rework_date), row.company)
	for year in range(2090, 2101):
		for company in frappe.get_all("Company", pluck="name", limit_page_length=0):
			test_bootstrap.ensure_fiscal_year_for_date(f"{year}-06-01", company)
	frappe.db.commit()


def _purge_future_transactional_data() -> None:
	_ensure_fiscal_years_for_test_stock_entries()
	posting_names = frappe.get_all(
		"Stock Entry",
		filters={"posting_date": [">=", _PERSISTENT_DEV_TEST_DATE_CUTOFF]},
		pluck="name",
		limit_page_length=0,
	)
	rework_names = frappe.get_all(
		"Stock Entry",
		filters={"custom_pea_rework_date": [">=", _PERSISTENT_DEV_TEST_DATE_CUTOFF]},
		pluck="name",
		limit_page_length=0,
	)
	_cancel_delete_stock_entries([*posting_names, *rework_names, *_stock_entries_with_test_items()])

	for name in frappe.get_all(
		"Shift",
		filters={"shift_date": [">=", _PERSISTENT_DEV_TEST_DATE_CUTOFF]},
		pluck="name",
		limit_page_length=0,
	):
		e2e_api._safe_force_delete("Shift", name, context="persistent_dev_cleanup")

	for name in frappe.get_all("Downtime Entry", pluck="name", limit_page_length=0):
		e2e_api._safe_force_delete("Downtime Entry", name, context="persistent_dev_cleanup")


def _purge_die_tool_artifacts_for_items(item_codes: list[str]) -> None:
	for item_code in item_codes:
		for counter_name in frappe.get_all(
			"Die Tool Counter", filters={"die_tool_item": item_code}, pluck="name"
		):
			e2e_api._safe_force_delete("Die Tool Counter", counter_name, context="persistent_dev_cleanup")
		for log_name in frappe.get_all(
			"Die Tool Maintenance Log", filters={"die_tool_item": item_code}, pluck="name"
		):
			e2e_api._safe_cancel_and_delete(
				"Die Tool Maintenance Log", log_name, context="persistent_dev_cleanup"
			)


def _purge_test_master_data() -> None:
	for _round in range(_RESERVED_CLEANUP_ROUNDS):
		test_cleanup.cleanup_reserved_test_data()

	for pattern in ("E2E%", "RejReg%", "E2E_REWORK%"):
		for name in frappe.get_all(
			"Stock Entry Type", filters={"name": ["like", pattern]}, pluck="name", limit_page_length=0
		):
			e2e_api._safe_force_delete("Stock Entry Type", name, context="persistent_dev_cleanup")

	for pattern in ("E2E%", "RejReg%"):
		for name in frappe.get_all(
			"Rework Type", filters={"name": ["like", pattern]}, pluck="name", limit_page_length=0
		):
			e2e_api._safe_force_delete("Rework Type", name, context="persistent_dev_cleanup")

	item_codes = [
		name
		for name in frappe.get_all(
			"Item", filters={"name": ["like", "_%"]}, pluck="name", limit_page_length=0
		)
		if _is_test_item_code(name)
	]
	_purge_die_tool_artifacts_for_items(item_codes)

	for item_code in item_codes:
		for bom_name in frappe.get_all("BOM", filters={"item": item_code}, pluck="name"):
			e2e_api._safe_force_delete("BOM", bom_name, context="persistent_dev_cleanup")
		if e2e_api._item_has_live_stock_entry_references(item_code):
			continue
		if frappe.db.exists("Item", item_code):
			e2e_api._safe_force_delete("Item", item_code, context="persistent_dev_cleanup")

	for doctype, field, pattern in (
		("Operator", "name", "E2E%"),
		("Workstation", "name", "E2E%"),
		("Department", "department_name", "E2E%"),
		("Department", "department_name", "RejReg%"),
	):
		for name in frappe.get_all(
			doctype, filters={field: ["like", pattern]}, pluck="name", limit_page_length=0
		):
			e2e_api._safe_force_delete(doctype, name, context="persistent_dev_cleanup")

	for pattern in ("Lifecycle%", "RejReg%"):
		for name in frappe.get_all(
			"Employee", filters={"first_name": ["like", pattern]}, pluck="name", limit_page_length=0
		):
			e2e_api._safe_force_delete("Employee", name, context="persistent_dev_cleanup")
	for name in frappe.get_all(
		"Employee", filters={"employee_number": ["like", "%-EMP"]}, pluck="name", limit_page_length=0
	):
		e2e_api._safe_force_delete("Employee", name, context="persistent_dev_cleanup")

	for role_name in frappe.get_all("Role", filters={"name": ["like", "E2E ROLE %"]}, pluck="name"):
		e2e_api._safe_force_delete("Role", role_name, context="persistent_dev_cleanup")

	for reason_name in frappe.get_all(
		"Downtime Reason", filters={"name": ["like", "E2E-DOWNTIME-%"]}, pluck="name"
	):
		e2e_api._safe_force_delete("Downtime Reason", reason_name, context="persistent_dev_cleanup")


def _delete_example_com_test_users() -> int:
	deleted = 0
	for email in frappe.get_all(
		"User",
		filters={"name": ["like", "%@example.com"]},
		pluck="name",
		limit_page_length=0,
	):
		if email in ("Administrator", "Guest"):
			continue
		try:
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)
			deleted += 1
		except Exception:
			frappe.log_error(title="persistent dev cleanup user delete failed", message=f"User {email}")
			raise
	return deleted


def _remaining_test_counts() -> dict[str, int]:
	test_items = {
		*frappe.get_all("Item", filters={"name": ["like", "_Test%"]}, pluck="name", limit_page_length=0),
		*frappe.get_all("Item", filters={"name": ["like", "_E2E%"]}, pluck="name", limit_page_length=0),
		*frappe.get_all("Item", filters={"name": ["like", "_RejReg%"]}, pluck="name", limit_page_length=0),
	}
	return {
		"items_test": len(test_items),
		"stock_209x": frappe.db.count(
			"Stock Entry", {"posting_date": [">=", _PERSISTENT_DEV_TEST_DATE_CUTOFF]}
		),
		"users_example_com": frappe.db.count("User", {"name": ["like", "%@example.com"]}),
		"shifts_209x": frappe.db.count("Shift", {"shift_date": [">=", _PERSISTENT_DEV_TEST_DATE_CUTOFF]}),
	}
