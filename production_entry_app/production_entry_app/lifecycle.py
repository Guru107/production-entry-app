from __future__ import annotations

import frappe
from frappe.utils import cint

from production_entry_app.production_entry_app import performance_indexes

APP_MODULE = "Production Entry App"
CUSTOMIZATION_DOCTYPES = ("Property Setter", "Custom Field")
REWORK_DETAILS_SECTION_CUSTOM_FIELD = "Stock Entry-custom_pea_rework_details_section"
REWORK_LAYOUT_FIELDNAMES = frozenset(
	{
		"custom_pea_rework_details_section",
		"custom_pea_rework_type",
		"custom_pea_rework_column_break",
		"custom_pea_rework_workstation",
		"custom_pea_rework_operators",
		"custom_pea_rework_cost",
		"custom_pea_rework_details_end_section",
	}
)


def after_sync() -> None:
	_setup_app()


def after_migrate() -> None:
	_setup_app()
	_warn_if_e2e_enabled_on_non_test_site()


def before_uninstall() -> None:
	performance_indexes.drop_performance_indexes_if_exists()
	for doctype in CUSTOMIZATION_DOCTYPES:
		_delete_customizations(doctype)


def _warn_if_e2e_enabled_on_non_test_site() -> None:
	if not cint(frappe.conf.get("allow_e2e_tests", 0)):
		return
	site = frappe.local.site or ""
	if not any(marker in site for marker in ("test", "dev", "localhost")):
		frappe.logger("production_entry_app").warning(
			f"allow_e2e_tests=1 is set on site '{site}', which does not look like a "
			"test/dev site. E2E APIs perform force-deletes and permission changes."
		)


def _setup_app() -> None:
	ensure_rework_details_layout()
	remove_obsolete_total_rm_consumption_field()
	reconcile_stock_entry_purpose_field()
	performance_indexes.ensure_performance_indexes_with_recovery()
	frappe.logger("production_entry_app").info(
		"Production Entry App setup ran: Rework Stock Entry layout, obsolete Total RM Consumption "
		"field, Stock Entry Purpose metadata, and performance indexes were reconciled during "
		"sync/migrate."
	)


def remove_obsolete_total_rm_consumption_field() -> None:
	"""Remove Total RM Consumption once item rows are the material source of truth (#121)."""
	fieldname = "Stock Entry-custom_pea_total_rm_consumption"
	if not frappe.db.exists("Custom Field", fieldname):
		return
	frappe.delete_doc(
		"Custom Field",
		fieldname,
		ignore_permissions=True,
		force=True,
	)
	frappe.clear_cache(doctype="Stock Entry")


def reconcile_stock_entry_purpose_field() -> None:
	"""Ensure production-owned Stock Entry Purpose exists, backfill values, drop legacy copy."""
	ensure_production_owned_stock_entry_purpose()
	_backfill_stock_entry_purpose_values()
	_delete_legacy_stock_entry_purpose_field()


def ensure_production_owned_stock_entry_purpose() -> None:
	"""Create production-owned Stock Entry Purpose on hosts that lack it (CONTEXT.md)."""
	field_name = "Stock Entry-custom_stock_entry_purpose"
	if frappe.db.exists("Custom Field", field_name):
		return
	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "Stock Entry",
			"fieldname": "custom_stock_entry_purpose",
			"label": "Stock Entry Purpose",
			"fieldtype": "Data",
			"fetch_from": "stock_entry_type.purpose",
			"read_only": 1,
			"insert_after": "stock_entry_type",
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Stock Entry")


def _backfill_stock_entry_purpose_values() -> None:
	"""Fill blank Stock Entry Purpose from a legacy column (if present) or native purpose."""
	_clear_stock_entry_column_cache()
	if not frappe.db.has_column("Stock Entry", "custom_stock_entry_purpose"):
		return

	legacy_source = (
		"NULLIF(`custom_pea_stock_entry_purpose`, ''), "
		if frappe.db.has_column("Stock Entry", "custom_pea_stock_entry_purpose")
		else ""
	)
	frappe.db.sql(
		f"""
		UPDATE `tabStock Entry`
		SET `custom_stock_entry_purpose` = COALESCE(
			NULLIF(`custom_stock_entry_purpose`, ''),
			{legacy_source}
			NULLIF(`purpose`, '')
		)
		WHERE IFNULL(`custom_stock_entry_purpose`, '') = ''
		"""
	)


def _delete_legacy_stock_entry_purpose_field() -> None:
	"""Drop the obsolete PEA-prefixed Stock Entry Purpose Custom Field and column."""
	field_name = "Stock Entry-custom_pea_stock_entry_purpose"
	fieldname = "custom_pea_stock_entry_purpose"
	if frappe.db.exists("Custom Field", field_name):
		frappe.delete_doc(
			"Custom Field",
			field_name,
			ignore_permissions=True,
			force=True,
		)
	_clear_stock_entry_column_cache()
	if frappe.db.has_column("Stock Entry", fieldname):
		frappe.model.delete_fields({"Stock Entry": [fieldname]}, delete=1)
		_clear_stock_entry_column_cache()
	frappe.clear_cache(doctype="Stock Entry")


def _clear_stock_entry_column_cache() -> None:
	frappe.cache.hdel("table_columns", "tabStock Entry")


def ensure_rework_details_layout() -> None:
	"""Place Rework Details after the installed version's opening Stock Entry section."""
	current_anchor = frappe.db.get_value("Custom Field", REWORK_DETAILS_SECTION_CUSTOM_FIELD, "insert_after")
	if not current_anchor:
		return

	meta = frappe.get_meta("Stock Entry", cached=False)
	anchor = _get_rework_details_anchor(meta.fields)
	if not anchor or anchor == current_anchor:
		return

	frappe.db.set_value(
		"Custom Field",
		REWORK_DETAILS_SECTION_CUSTOM_FIELD,
		"insert_after",
		anchor,
		update_modified=False,
	)
	frappe.clear_cache(doctype="Stock Entry")


def _get_rework_details_anchor(fields: list) -> str | None:
	previous_fieldname = None
	inside_opening_section = False
	for field in fields:
		fieldname = field.get("fieldname")
		if not fieldname or fieldname in REWORK_LAYOUT_FIELDNAMES:
			continue
		if fieldname == "stock_entry_type":
			inside_opening_section = True
		if not inside_opening_section:
			continue
		if field.get("fieldtype") in ("Section Break", "Tab Break"):
			return previous_fieldname
		previous_fieldname = fieldname
	return None


def _delete_customizations(doctype: str) -> None:
	for name in frappe.get_all(doctype, filters={"module": APP_MODULE}, pluck="name"):
		# Uninstall must remove app-owned customizations from ERPNext doctypes even if they
		# still reference app doctypes being dropped in the same uninstall transaction.
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
