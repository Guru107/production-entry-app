from __future__ import annotations

import frappe

from production_entry_app.production_entry_app import access_control, performance_indexes

APP_MODULE = "Production Entry App"


def after_sync() -> None:
	_setup_app()


def after_migrate() -> None:
	_setup_app()


def before_uninstall() -> None:
	performance_indexes.drop_performance_indexes_if_exists()
	_delete_customizations("Property Setter")
	_delete_customizations("Custom Field")


def _setup_app() -> None:
	access_control.invalidate_access_control_cache()
	performance_indexes.ensure_performance_indexes_with_recovery()


def _delete_customizations(doctype: str) -> None:
	for name in frappe.get_all(doctype, filters={"module": APP_MODULE}, pluck="name"):
		# Uninstall must remove app-owned customizations from ERPNext doctypes even if they
		# still reference app doctypes being dropped in the same uninstall transaction.
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
