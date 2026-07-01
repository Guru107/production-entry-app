from __future__ import annotations

import frappe

from production_entry_app.production_entry_app import access_control, field_permissions, performance_indexes

APP_MODULE = "Production Entry App"
CUSTOMIZATION_DOCTYPES = ("Property Setter", "Custom Field")


def after_sync() -> None:
	_setup_app()


def after_migrate() -> None:
	_setup_app()


def before_uninstall() -> None:
	performance_indexes.drop_performance_indexes_if_exists()
	for doctype in CUSTOMIZATION_DOCTYPES:
		_delete_customizations(doctype)


def _setup_app() -> None:
	access_control.ensure_access_roles_and_settings()
	field_permissions.ensure_pea_field_permissions()
	performance_indexes.ensure_performance_indexes_with_recovery()
	frappe.logger("production_entry_app").info(
		"Production Entry App setup ran: access roles, field permissions (permlevel 9), "
		"and performance indexes were reconciled during sync/migrate."
	)


def _delete_customizations(doctype: str) -> None:
	for name in frappe.get_all(doctype, filters={"module": APP_MODULE}, pluck="name"):
		# Uninstall must remove app-owned customizations from ERPNext doctypes even if they
		# still reference app doctypes being dropped in the same uninstall transaction.
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
