"""One-shot install migration: retire the legacy parallel time-capture UI.

The production site captures production time through host custom fields — the
``custom_operation_details`` / ``custom_actual_time`` / ``custom_loss_time``
sections on Stock Entry and ``Workstation.custom_standard_spm`` — driven by the
``Actual & Loss Time Calculation`` and ``Stock Auto Time`` client scripts. The
app ships its own Shift-based capture, so from go-live the legacy UI is retired
in one ordered, idempotent step:

1. Disable the two legacy time client scripts by name (only when present and
   enabled; the Branch Fetching, BOM and Stock Entry Type scripts are never
   touched).
2. Hide the legacy sections and the Workstation SPM field via Property Setters
   (``hidden=1``, module Production Entry App). Hide only — no field or data is
   deleted; historical values stay reachable via Show Hidden Fields, reports
   and exports.
3. Hide any obsolete Production-Entry-App-module custom fields that current
   fixtures no longer ship (staging-drift pattern), same hide-only rule.

Entry points (also called from the install-migration post-sync step):

- ``execute_legacy_time_cutover`` — the ordered engine, e.g. via ``bench execute``.
- ``unhide_legacy_time_fields`` — reverses step 2 (rollback or pilot course correction).

Scripts are disabled before sections are hidden, so no enabled script ever
writes to a hidden section. Host-owned customizations are never hijacked: if a
host Property Setter already sits on a cutover target, the engine reports it
and leaves it alone. Every step guards on current state, so a re-run after a
partial failure converges instead of duplicating or throwing. Because the hide
Property Setters carry the app module, the existing ``before_uninstall``
customization cleanup un-hides on uninstall.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe.utils import cint

APP_MODULE = "Production Entry App"
STOCK_ENTRY = "Stock Entry"
WORKSTATION = "Workstation"
HIDDEN_PROPERTY = "hidden"
HIDDEN_VALUE = "1"
PROPERTY_TYPE_CHECK = "Check"

LEGACY_TIME_CLIENT_SCRIPTS: tuple[str, ...] = (
	"Actual & Loss Time Calculation",
	"Stock Auto Time",
)
# (doctype, fieldname) legacy time-capture targets hidden by the cutover. Hiding
# a section hides all its leaf fields; leaf fields themselves stay unhidden so
# the host form layout stays coherent.
LEGACY_TIME_FIELDS: tuple[tuple[str, str], ...] = (
	(STOCK_ENTRY, "custom_operation_details"),
	(STOCK_ENTRY, "custom_actual_time"),
	(STOCK_ENTRY, "custom_loss_time"),
	(WORKSTATION, "custom_standard_spm"),
)


def execute_legacy_time_cutover() -> None:
	"""Run the ordered legacy cutover: disable scripts, then hide fields."""
	_disable_legacy_client_scripts()
	_hide_legacy_time_sections()
	_hide_obsolete_pea_custom_fields()
	frappe.logger("production_entry_app").info("Legacy time cutover: complete.")


def unhide_legacy_time_fields() -> None:
	"""Reverse the hiding step: drop the app-owned hide Property Setters."""
	for doctype, fieldname in LEGACY_TIME_FIELDS:
		_delete_app_hidden_property_setter(doctype, fieldname)
	frappe.logger("production_entry_app").info("Legacy time cutover: fields un-hidden.")


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


def _hide_legacy_time_sections() -> None:
	for doctype, fieldname in LEGACY_TIME_FIELDS:
		_hide_field(doctype, fieldname)


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
	_ensure_hidden_property_setter(doctype, fieldname)


def _ensure_hidden_property_setter(doctype: str, fieldname: str) -> None:
	name = _hidden_property_setter_name(doctype, fieldname)
	if frappe.db.exists("Property Setter", name):
		value, module = frappe.db.get_value("Property Setter", name, ["value", "module"])
		if module != APP_MODULE:
			# Never hijack a host customization: a host-owned setter on a legacy
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
		frappe.db.set_value("Property Setter", name, "value", HIDDEN_VALUE, update_modified=False)
		frappe.clear_cache(doctype=doctype)
		frappe.logger("production_entry_app").info("Legacy time cutover: re-hid %s.%s.", doctype, fieldname)
		return
	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": doctype,
			"field_name": fieldname,
			"property": HIDDEN_PROPERTY,
			"property_type": PROPERTY_TYPE_CHECK,
			"value": HIDDEN_VALUE,
			"module": APP_MODULE,
		}
	).insert(ignore_permissions=True)
	frappe.logger("production_entry_app").info("Legacy time cutover: hid %s.%s.", doctype, fieldname)


def _delete_app_hidden_property_setter(doctype: str, fieldname: str) -> None:
	name = _hidden_property_setter_name(doctype, fieldname)
	if not frappe.db.exists("Property Setter", name):
		return
	if frappe.db.get_value("Property Setter", name, "module") != APP_MODULE:
		return
	frappe.delete_doc("Property Setter", name, ignore_permissions=True)


def _hidden_property_setter_name(doctype: str, fieldname: str) -> str:
	return f"{doctype}-{fieldname}-{HIDDEN_PROPERTY}"


def _fixture_custom_field_names() -> frozenset[str]:
	"""Names of the custom fields current app fixtures ship (``{dt}-{fieldname}``)."""
	path = Path(frappe.get_app_path("production_entry_app")) / "fixtures" / "custom_field.json"
	entries = json.loads(path.read_text())
	return frozenset(entry["name"] for entry in entries)
