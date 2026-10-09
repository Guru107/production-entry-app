"""One-shot install migration: remove the legacy parallel time-capture fields.

The production site captures production time through host custom fields — the
``custom_operation_details`` / ``custom_actual_time`` / ``custom_loss_time``
sections and their leaf fields (planned/actual dates, workstation, press
rate, standard SPM, time logs, loss rows, totals) on Stock Entry, plus
``Workstation.custom_standard_spm`` / ``Workstation.custom_press_rate`` —
driven by the ``Actual & Loss Time Calculation`` and ``Stock Auto Time``
client scripts. The app ships its own Shift-based capture, and this is a
hard cutover release, so the install removes the legacy workflow in one
ordered, idempotent step:

1. Disable the two legacy time client scripts by name (only when present and
   enabled; the Branch Fetching, BOM and Stock Entry Type scripts are never
   touched).
2. Delete every legacy time custom field (section and leaf alike). Deleting a
   custom field removes its metadata, so the legacy fields leave forms and the
   ORM and the workflow has no path back into use; frappe never drops the
   physical column, so historical values survive in orphaned columns until an
   optional manual DDL after go-live (release runbook). This is a cutover, not
   a bridge: entries before the release are not considered by the app or its
   reports, and no value is backfilled into the app's own fields. The
   pre-install site backup from the release runbook is the recovery path.
3. Hide any obsolete Production-Entry-App-module custom fields that current
   fixtures no longer ship (staging-drift pattern), same hide-only rule.

Entry point (also called from the install-migration post-sync step):
``execute_legacy_time_cutover``, e.g. via ``bench execute``.

Scripts are disabled before fields are removed, so no enabled script ever
writes into a disappearing field. Only genuine custom fields are deleted — a
target that is absent, or exists as a native field, is reported and skipped.
Every step guards on current state, so a re-run after a partial failure
converges instead of duplicating or throwing.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe.utils import cint

APP_MODULE = "Production Entry App"
STOCK_ENTRY = "Stock Entry"
WORKSTATION = "Workstation"
PROPERTY_TYPE_CHECK = "Check"

LEGACY_TIME_CLIENT_SCRIPTS: tuple[str, ...] = (
	"Actual & Loss Time Calculation",
	"Stock Auto Time",
)
# (doctype, fieldname) legacy time-capture targets removed by the cutover.
# Sections and leaves alike: the field metadata is deleted so the legacy
# workflow has no path back into use (see the module docstring for what
# happens to the physical columns).
LEGACY_TIME_FIELDS: tuple[tuple[str, str], ...] = (
	(STOCK_ENTRY, "custom_operation_details"),
	(STOCK_ENTRY, "custom_workstation"),
	(STOCK_ENTRY, "custom_press_rate"),
	(STOCK_ENTRY, "custom_actual_time"),
	(STOCK_ENTRY, "custom_planned_start_date"),
	(STOCK_ENTRY, "custom_planned_end_date"),
	(STOCK_ENTRY, "custom_actual_start_date"),
	(STOCK_ENTRY, "custom_actual_end_date"),
	(STOCK_ENTRY, "custom_standard_spm"),
	(STOCK_ENTRY, "custom_time_logs"),
	(STOCK_ENTRY, "custom_loss_time"),
	(STOCK_ENTRY, "custom_loss_time_details"),
	(STOCK_ENTRY, "custom_total_actual_time"),
	(STOCK_ENTRY, "custom_total_loss_time"),
	(WORKSTATION, "custom_standard_spm"),
	(WORKSTATION, "custom_press_rate"),
)


def execute_legacy_time_cutover() -> None:
	"""Run the ordered legacy cutover: disable scripts, then remove fields."""
	_disable_legacy_client_scripts()
	_remove_legacy_time_custom_fields()
	_hide_obsolete_pea_custom_fields()
	frappe.logger("production_entry_app").info("Legacy time cutover: complete.")


def _disable_legacy_client_scripts() -> None:
	for name in LEGACY_TIME_CLIENT_SCRIPTS:
		if not frappe.db.exists("Client Script", name):
			frappe.logger("production_entry_app").info(
				"Legacy time cutover: client script %s absent; skipped.", name
			)
			continue
		if not cint(frappe.db.get_value("Client Script", name, "enabled")):
			frappe.logger("production_entry_app").info(
				"Legacy time cutover: client script %s already disabled; skipped.", name
			)
			continue
		frappe.db.set_value("Client Script", name, "enabled", 0)
		frappe.logger("production_entry_app").info("Legacy time cutover: disabled client script %s.", name)


def _remove_legacy_time_custom_fields() -> None:
	for doctype, fieldname in LEGACY_TIME_FIELDS:
		_remove_custom_field(doctype, fieldname)


def _remove_custom_field(doctype: str, fieldname: str) -> None:
	name = f"{doctype}-{fieldname}"
	meta = frappe.get_meta(doctype, cached=False)
	if meta.get_field(fieldname) is None:
		frappe.logger("production_entry_app").info(
			"Legacy time cutover: %s.%s absent on this site; skipped.", doctype, fieldname
		)
		return
	if not frappe.db.exists("Custom Field", name):
		# A native field carrying a cutover name: never delete DocFields.
		frappe.logger("production_entry_app").warning(
			"Legacy time cutover: %s is not a custom field; left untouched.", name
		)
		return
	_delete_field_property_setters(doctype, fieldname)
	frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype=doctype)
	frappe.logger("production_entry_app").info(
		"Legacy time cutover: removed custom field %s (metadata deleted; frappe retains the column).", name
	)


def _delete_field_property_setters(doctype: str, fieldname: str) -> None:
	"""Drop setters orphaned by the field removal (host- or app-owned alike)."""
	for row in frappe.get_all(
		"Property Setter",
		filters={"doc_type": doctype, "field_name": fieldname},
		pluck="name",
	):
		frappe.delete_doc("Property Setter", row, ignore_permissions=True)


def _hide_obsolete_pea_custom_fields() -> None:
	fixture_names = _fixture_custom_field_names()
	drift = frappe.get_all(
		"Custom Field",
		filters={"module": APP_MODULE},
		fields=["name", "dt", "fieldname"],
	)
	obsolete = [row for row in drift if row.name not in fixture_names]
	if not obsolete:
		frappe.logger("production_entry_app").info(
			"Legacy time cutover: no obsolete app custom fields on this site; skipped."
		)
		return
	for row in obsolete:
		_hide_field(row.dt, row.fieldname)


def _hide_field(doctype: str, fieldname: str) -> None:
	meta = frappe.get_meta(doctype, cached=False)
	if meta.get_field(fieldname) is None:
		frappe.logger("production_entry_app").info(
			"Legacy time cutover: %s.%s absent on this site; skipped.", doctype, fieldname
		)
		return
	name = f"{doctype}-{fieldname}-hidden"
	if frappe.db.exists("Property Setter", name):
		value, module = frappe.db.get_value("Property Setter", name, ["value", "module"])
		if module != APP_MODULE:
			# Never hijack a host customization: a host-owned setter on a drift
			# target is an unaudited host shape, so report it and leave it alone.
			if cint(value) != 1:
				frappe.logger("production_entry_app").warning(
					"Legacy time cutover: %s has a host-owned setter forcing it visible;"
					" left untouched. Hide %s manually via Customize Form.",
					name,
					f"{doctype}.{fieldname}",
				)
			return
		if cint(value) == 1:
			frappe.logger("production_entry_app").info(
				"Legacy time cutover: %s.%s already hidden; skipped.", doctype, fieldname
			)
			return
		frappe.db.set_value("Property Setter", name, "value", "1", update_modified=False)
		frappe.clear_cache(doctype=doctype)
		return
	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": doctype,
			"field_name": fieldname,
			"property": "hidden",
			"property_type": PROPERTY_TYPE_CHECK,
			"value": "1",
			"module": APP_MODULE,
		}
	).insert(ignore_permissions=True)
	frappe.logger("production_entry_app").info("Legacy time cutover: hid %s.%s.", doctype, fieldname)


def _fixture_custom_field_names() -> frozenset[str]:
	"""Names of the custom fields current app fixtures ship (``{dt}-{fieldname}``)."""
	path = Path(frappe.get_app_path("production_entry_app")) / "fixtures" / "custom_field.json"
	entries = json.loads(path.read_text())
	return frozenset(entry["name"] for entry in entries)
