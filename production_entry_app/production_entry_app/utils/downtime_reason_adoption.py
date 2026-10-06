"""One-shot install migration: adopt the host custom Downtime Reason DocType in place.

Production ships a custom, non-submittable ``Downtime Reason`` DocType (module
Manufacturing, autoname ``field:downtime_issue``) whose name collides with this
app's DocType. The adoption engine reshapes the host DocType to the app schema
in place — same name, same table, same rows — so doctype sync proceeds without
a collision, then seeds and converts masters to code identities (ADR 0005).

Entry points (also wired from install hooks and migration patches):

- ``adopt_host_downtime_reason_schema`` — pre-sync: export + reshape.
- ``convert_host_downtime_reasons`` — post-sync: seed + convert + verify.
- ``adopt_host_downtime_reason`` — the full sequence, e.g. via ``bench execute``.

Every step guards on current state, so re-running after a partial failure
converges instead of duplicating or throwing.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe import _
from frappe.model.meta import Meta
from frappe.model.rename_doc import get_link_fields
from frappe.utils import cint

from production_entry_app.production_entry_app.doctype.downtime_reason.downtime_reason import (
	CODE_FORMAT,
)
from production_entry_app.production_entry_app.utils.downtime_reason_conversion import (
	EXTRA_DOWNTIME_REASON_CODES,
	LEGACY_DOWNTIME_REASON_CODES,
	convert_legacy_downtime_reasons,
)
from production_entry_app.production_entry_app.utils.downtime_reason_seed import (
	STANDARD_DOWNTIME_REASONS,
	seed_standard_downtime_reasons,
)

APP_MODULE = "Production Entry App"
DOCTYPE = "Downtime Reason"
HOST_AUTONAME = "field:downtime_issue"
HOST_IDENTITY_FIELD = "downtime_issue"
APP_AUTONAME = "field:code"
APP_NAMING_RULE = "By fieldname"

# Field definitions mirrored from the app's Downtime Reason DocType JSON; doctype
# sync right after adoption would install them anyway, but the reshape keeps the
# engine independently correct.
APP_SCHEMA_FIELDS = (
	{
		"fieldname": "code",
		"fieldtype": "Data",
		"label": "Code",
		"reqd": 1,
		"unique": 1,
		"search_index": 1,
		"in_list_view": 1,
	},
	{
		"fieldname": "description",
		"fieldtype": "Data",
		"label": "Description",
		"reqd": 1,
		"in_list_view": 1,
	},
	{
		"fieldname": "is_active",
		"fieldtype": "Check",
		"label": "Is Active",
		"default": "1",
		"in_list_view": 1,
	},
)

STATE_ABSENT = "absent"
STATE_ADOPTED = "adopted"
STATE_RESHAPED = "reshaped"
STATE_HOST = "host"
STATE_UNEXPECTED = "unexpected"


def adoption_export_path() -> str:
	"""Path of the pre-adoption recovery export inside the site's private backups."""
	return str(Path(frappe.get_site_path()) / "private" / "backups" / "downtime_reason_adoption_export.json")


def classify_downtime_reason_doctype() -> str:
	"""Classify the current Downtime Reason DocType for adoption."""
	if not frappe.db.exists("DocType", DOCTYPE):
		return STATE_ABSENT
	meta = frappe.get_meta(DOCTYPE, cached=False)
	if _is_adopted_shape(meta):
		return STATE_ADOPTED
	if _is_host_shape(meta):
		return STATE_HOST
	if _is_reshaped_custom_shape(meta):
		return STATE_RESHAPED
	return STATE_UNEXPECTED


def _is_host_shape(meta: Meta) -> bool:
	return (
		bool(meta.custom)
		and cint(meta.is_submittable) == 0
		and (meta.autoname or "") == HOST_AUTONAME
		and meta.get_field(HOST_IDENTITY_FIELD) is not None
		and meta.get_field("code") is None
	)


def _is_reshaped_custom_shape(meta: Meta) -> bool:
	"""The fresh-install intermediate: app schema on a still-custom record.

	``before_install`` runs before the installer has registered Module Defs, so
	the reshape keeps the record custom there (a standard DocType must carry a
	module whose controller imports); doctype sync standardizes the record right
	after. The recovery export on disk is the evidence this shape is our own
	partial reshape and not an unknown host state: the export is written before
	any mutation, so without it the shape must fail fast instead of skipping.
	"""
	return bool(meta.custom) and _has_app_schema(meta) and Path(adoption_export_path()).exists()


def _is_adopted_shape(meta: Meta) -> bool:
	return not meta.custom and _has_app_schema(meta)


def _has_app_schema(meta: Meta) -> bool:
	return (
		meta.get_field("code") is not None
		and (meta.autoname or "") == APP_AUTONAME
		and cint(meta.is_submittable) == 0
	)


def adopt_host_downtime_reason_schema() -> None:
	"""Pre-sync step: export the host state and reshape the DocType in place."""
	state = classify_downtime_reason_doctype()
	if state in (STATE_ABSENT, STATE_ADOPTED, STATE_RESHAPED):
		return
	if state == STATE_UNEXPECTED:
		values = frappe.db.get_value(
			"DocType", DOCTYPE, ["custom", "is_submittable", "autoname"], as_dict=True
		)
		frappe.throw(
			_(
				"Downtime Reason exists in an unexpected shape (custom={0}, is_submittable={1},"
				" autoname={2}). Refusing to adopt; resolve manually before installing."
			).format(
				cint(values.custom),
				cint(values.is_submittable),
				values.autoname,
			)
		)

	export = _export_adoption_state()
	_write_export(export)
	frappe.logger("production_entry_app").info(
		"Downtime Reason adoption: exported %s reasons and %s populated link field(s) before reshape.",
		len(export["reasons"]),
		len(export["link_inventory"]),
	)
	_reshape_doctype()
	_normalize_rows()
	frappe.logger("production_entry_app").info(
		"Downtime Reason adoption: reshaped the host DocType to the app schema in place."
	)


def _export_adoption_state() -> dict:
	"""Capture the reason masters and every populated link field value."""
	frappe.flags.link_fields = {}  # rename_doc caches these; adoption changes metadata
	reasons = frappe.get_all(DOCTYPE, fields=["name", "docstatus"], order_by="creation asc")
	link_inventory = []
	for holder in get_link_fields(DOCTYPE):
		if holder.issingle:
			continue
		rows = frappe.get_all(
			holder.parent,
			fields=[holder.fieldname, "count(name) as row_count"],
			filters={holder.fieldname: ["is", "set"]},
			group_by=holder.fieldname,
		)
		counts = {getattr(row, holder.fieldname): row.row_count for row in rows}
		if counts:
			link_inventory.append({"parent": holder.parent, "fieldname": holder.fieldname, "counts": counts})
	return {"reasons": reasons, "link_inventory": link_inventory}


def _write_export(export: dict) -> None:
	path = Path(adoption_export_path())
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(export, indent=1, default=str))


def load_adoption_export() -> dict | None:
	"""Read the pre-adoption recovery export, if one was written on this site."""
	path = Path(adoption_export_path())
	if not path.exists():
		return None
	return json.loads(path.read_text())


def _reshape_doctype() -> None:
	"""Reshape the host custom DocType to the app schema, keeping name/table/rows.

	Saving a standard (non-custom) DocType is only allowed in developer mode,
	patches, tests, or imports; and developer-mode saves export the doctype back
	to the app's JSON files. Adoption is an import-time reshape, so it runs under
	the import flag: allowed outside developer mode and never rewrites files.

	The record is standardized (module reassigned, ``custom=0``) only when the
	app Module Def already exists: on a fresh install ``before_install`` runs
	before the installer registers Module Defs, and a standard DocType must
	carry a module whose controller imports. Without it the record keeps
	``custom=1`` with the app schema, and the doctype sync right after
	re-imports the record from the app JSON (module included), so the host
	module never survives the install.
	"""
	doc = frappe.get_doc("DocType", DOCTYPE)
	if frappe.db.exists("Module Def", APP_MODULE):
		doc.module = APP_MODULE
		doc.custom = 0
	doc.autoname = APP_AUTONAME
	doc.naming_rule = APP_NAMING_RULE
	doc.is_submittable = 0
	doc.fields = []
	for field in APP_SCHEMA_FIELDS:
		doc.append("fields", {**field})
	was_in_import = frappe.flags.get("in_import")
	frappe.flags.in_import = True
	try:
		doc.save()
	finally:
		frappe.flags.in_import = was_in_import
	frappe.clear_cache(doctype=DOCTYPE)


def _normalize_rows() -> None:
	"""Backfill app-schema columns on the adopted rows and reset submit state.

	Rows submitted while the host DocType was still submittable keep docstatus=1
	after it was made non-submittable; a non-submittable doctype must not carry
	submitted rows, so they drop to draft. The original docstatus values are
	preserved in the recovery export.
	"""
	rows = frappe.get_all(
		DOCTYPE, fields=["name", "description", "is_active", "docstatus"], order_by="creation asc"
	)
	for row in rows:
		updates: dict[str, object] = {}
		if not row.description:
			updates["description"] = row.name
		if not row.is_active:
			updates["is_active"] = 1
		if row.docstatus:
			updates["docstatus"] = 0
		if updates:
			frappe.db.set_value(DOCTYPE, row.name, updates, update_modified=False)
	frappe.db.commit()


def convert_host_downtime_reasons() -> None:
	"""Post-sync step: seed standard codes, convert legacy masters, verify the result."""
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	seed_standard_downtime_reasons()
	convert_legacy_downtime_reasons()
	_verify_adoption()
	frappe.logger("production_entry_app").info(
		"Downtime Reason adoption: conversion and verification complete."
	)


def adopt_host_downtime_reason() -> None:
	"""Full adoption sequence: reshape, then seed/convert/verify."""
	adopt_host_downtime_reason_schema()
	convert_host_downtime_reasons()


def _verify_adoption() -> None:
	"""Assert the adopted state is complete; throw loudly on any gap."""
	issues: list[str] = []
	names = set(frappe.get_all(DOCTYPE, pluck="name"))

	non_codes = sorted(name for name in names if not CODE_FORMAT.fullmatch(str(name)))
	if non_codes:
		issues.append(_("masters without two-digit codes: {0}").format(", ".join(non_codes)))

	missing_standard = sorted(set(STANDARD_DOWNTIME_REASONS) - names)
	if missing_standard:
		issues.append(_("missing standard codes: {0}").format(", ".join(missing_standard)))

	known_targets = {**LEGACY_DOWNTIME_REASON_CODES, **EXTRA_DOWNTIME_REASON_CODES}
	export = load_adoption_export()
	if export:
		descriptions = set(frappe.get_all(DOCTYPE, pluck="description"))
		for reason in export["reasons"]:
			legacy_name = reason["name"]
			if legacy_name in names:
				issues.append(_("legacy master kept its name: {0}").format(legacy_name))
			elif (
				not (legacy_name in known_targets and known_targets[legacy_name] in names)
				and legacy_name not in descriptions
			):
				issues.append(_("exported master unaccounted: {0}").format(legacy_name))
		issues.extend(_unrewritten_link_values(export, names))

	if issues:
		frappe.throw(_("Downtime Reason adoption verification failed:\n{0}").format("\n".join(issues)))


def _unrewritten_link_values(export: dict, current_names: set[str]) -> list[str]:
	"""Legacy names from the export that still populate link fields after conversion."""
	frappe.flags.link_fields = {}
	issues = []
	for entry in export["link_inventory"]:
		for legacy_value in entry["counts"]:
			if legacy_value in current_names:
				continue
			leftover = frappe.db.count(entry["parent"], {entry["fieldname"]: legacy_value})
			if leftover:
				issues.append(
					_("{0}.{1} still references {2} ({3} rows)").format(
						entry["parent"], entry["fieldname"], legacy_value, leftover
					)
				)
		issues.extend(_link_count_mismatches(entry))
	return issues


def _link_count_mismatches(entry: dict) -> list[str]:
	"""Adoption must rewrite link rows, never add or drop them; reconcile the counts."""
	current_count = frappe.db.count(entry["parent"], {entry["fieldname"]: ["is", "set"]})
	exported_count = sum(entry["counts"].values())
	if current_count != exported_count:
		return [
			_("{0}.{1} row count changed: exported {2} rows, found {3}").format(
				entry["parent"], entry["fieldname"], exported_count, current_count
			)
		]
	return []
