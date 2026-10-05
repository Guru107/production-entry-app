"""Host-parity builders for the Downtime Reason adoption tests.

These helpers swap the app-owned ``Downtime Reason`` DocType for the host
(production) custom shape and back, mirroring the production site where the
DocType is a non-submittable custom master named by ``downtime_issue`` with a
custom ``Loss Time`` child table linked from Stock Entry.
"""

from __future__ import annotations

from pathlib import Path

import frappe

from production_entry_app.production_entry_app.utils.downtime_reason_adoption import (
	adoption_export_path,
)
from production_entry_app.production_entry_app.utils.legacy_time_cutover import (
	APP_MODULE,
	LEGACY_TIME_FIELDS,
)

HOST_MODULE = "Manufacturing"

KEPT_CLIENT_SCRIPTS = ("Branch Fetching Stock Entry", "BOM", "Stock Entry Type")
LEGACY_TIME_CLIENT_SCRIPTS = ("Actual & Loss Time Calculation", "Stock Auto Time")

# These helpers commit deliberately: Custom Field inserts/deletes issue DDL (implicit
# commits) and the shared dev site must keep its fixture state across FrappeTestCase
# class-boundary rollbacks, so partial test state must never survive a rollback.

_PROPERTY_SETTER_SNAPSHOT_FIELDS = (
	"name",
	"doctype_or_field",
	"doc_type",
	"field_name",
	"property",
	"property_type",
	"value",
	"module",
	"is_system_generated",
)


def clear_adoption_export() -> None:
	path = Path(adoption_export_path())
	if path.exists():
		path.unlink()


def _delete_downtime_reason_doctype_record() -> None:
	"""Delete the DocType record and its rows without touching app source files.

	``for_reload`` keeps developer mode from rmtree-ing the app's doctype folder.
	"""
	if frappe.db.exists("DocType", "Downtime Reason"):
		if frappe.db.table_exists("Downtime Reason"):
			frappe.db.delete("Downtime Reason")
		frappe.delete_doc("DocType", "Downtime Reason", force=True, ignore_permissions=True, for_reload=True)
	frappe.clear_cache(doctype="Downtime Reason")


def restore_app_downtime_reason() -> None:
	"""Bring the app-owned Downtime Reason DocType and its standard seed rows back."""
	_delete_downtime_reason_doctype_record()
	frappe.reload_doc("production_entry_app", "doctype", "downtime_reason")
	frappe.clear_cache(doctype="Downtime Reason")
	# Leave the site as a normal migrated install: standard reasons seeded.
	from production_entry_app.production_entry_app.utils.downtime_reason_seed import (
		seed_standard_downtime_reasons,
	)

	seed_standard_downtime_reasons()
	frappe.db.commit()


def delete_downtime_reason_doctype() -> None:
	"""Remove the Downtime Reason DocType entirely (rows first, then the table)."""
	_delete_downtime_reason_doctype_record()


def install_host_downtime_reason_doctype(
	*, is_submittable: bool = False, extra_fields: tuple[dict, ...] = ()
) -> None:
	"""Create the production host custom DocType: non-submittable, named by downtime_issue.

	Production was aligned with staging (non-submittable) before install; rows
	submitted while the doctype was still submittable keep docstatus=1 in the
	table, so callers simulate that via ``legacy_docstatus``.
	"""
	frappe.get_doc(
		{
			"doctype": "DocType",
			"__islocal": 1,
			"name": "Downtime Reason",
			"module": HOST_MODULE,
			"custom": 1,
			"is_submittable": 1 if is_submittable else 0,
			"autoname": "field:downtime_issue",
			"naming_rule": "By fieldname",
			"fields": [
				{"fieldname": "section_break_6fwi", "fieldtype": "Section Break"},
				{
					"fieldname": "amended_from",
					"fieldtype": "Link",
					"options": "Downtime Reason",
					"read_only": 1,
				},
				{"fieldname": "downtime_issue", "fieldtype": "Data", "reqd": 1},
				*extra_fields,
			],
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Downtime Reason")


def insert_host_downtime_reason(name: str, *, legacy_docstatus: int = 0) -> None:
	doc = frappe.get_doc(
		{
			"doctype": "Downtime Reason",
			"downtime_issue": name,
		}
	).insert(ignore_permissions=True)
	if legacy_docstatus:
		frappe.db.set_value("Downtime Reason", doc.name, "docstatus", legacy_docstatus, update_modified=False)


def doctype_snapshot() -> dict:
	"""Capture the reshaped-relevant parts of the current Downtime Reason DocType."""
	meta = frappe.get_meta("Downtime Reason", cached=False)
	doc = frappe.get_doc("DocType", "Downtime Reason")
	return {
		"module": doc.module,
		"custom": doc.custom,
		"autoname": doc.autoname,
		"is_submittable": doc.is_submittable,
		"fieldnames": tuple(f.fieldname for f in meta.fields),
	}


def install_host_loss_time() -> None:
	"""Create the host custom Loss Time child table and its Stock Entry custom field."""
	if not frappe.db.exists("DocType", "Loss Time"):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"__islocal": 1,
				"name": "Loss Time",
				"module": HOST_MODULE,
				"custom": 1,
				"istable": 1,
				"fields": [
					{"fieldname": "from_time_loss", "fieldtype": "Datetime"},
					{"fieldname": "to_time_loss", "fieldtype": "Datetime"},
					{"fieldname": "loss_time", "fieldtype": "Float"},
					{
						"fieldname": "loss_type",
						"fieldtype": "Link",
						"options": "Downtime Reason",
					},
					{"fieldname": "remark", "fieldtype": "Data"},
				],
			}
		).insert(ignore_permissions=True)
		frappe.clear_cache(doctype="Loss Time")
	if not frappe.db.exists("Custom Field", "Stock Entry-custom_loss_time_details"):
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "Stock Entry",
				"fieldname": "custom_loss_time_details",
				"label": "Loss Time Details",
				"fieldtype": "Table",
				"options": "Loss Time",
				"module": HOST_MODULE,
			}
		).insert(ignore_permissions=True)
		frappe.clear_cache(doctype="Stock Entry")


def remove_host_loss_time() -> None:
	if frappe.db.exists("Custom Field", "Stock Entry-custom_loss_time_details"):
		frappe.delete_doc("Custom Field", "Stock Entry-custom_loss_time_details", ignore_permissions=True)
		frappe.clear_cache(doctype="Stock Entry")
	if frappe.db.exists("DocType", "Loss Time"):
		frappe.delete_doc("DocType", "Loss Time", force=True, ignore_permissions=True)
		frappe.clear_cache(doctype="Loss Time")


def make_host_stock_entry_with_loss_times(reasons: list[str], *, submit: bool = False) -> str:
	"""Create a Stock Entry carrying one Loss Time row per given reason name."""
	from production_entry_app.production_entry_app.utils.test_bootstrap import (
		ensure_item,
		ensure_warehouse,
		resolve_test_company,
	)

	company = resolve_test_company()
	abbr = frappe.db.get_value("Company", company, "abbr") or "TC"
	warehouse = ensure_warehouse(f"Host Parity WH - {abbr}", company)
	item = ensure_item("_Host Parity Item")
	doc = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"purpose": "Material Receipt",
			"stock_entry_type": "Material Receipt",
			"company": company,
			"items": [{"item_code": item, "t_warehouse": warehouse, "qty": 1, "basic_rate": 1}],
			"custom_loss_time_details": [{"loss_type": reason, "loss_time": 10} for reason in reasons],
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc.name


def discard_stock_entry(name: str) -> None:
	"""Remove a test Stock Entry whatever its docstatus."""
	if not frappe.db.exists("Stock Entry", name):
		return
	doc = frappe.get_doc("Stock Entry", name)
	if doc.docstatus == 1:
		doc.cancel()
	frappe.delete_doc("Stock Entry", name, force=True, ignore_permissions=True)


def loss_time_reason_values(stock_entry_name: str) -> list[str]:
	return sorted(
		frappe.get_all(
			"Loss Time",
			filters={"parent": stock_entry_name, "parenttype": "Stock Entry"},
			pluck="loss_type",
		)
	)


def ensure_host_custom_field(dt: str, field_values: dict) -> None:
	"""Create a host-owned (module-less) custom field if absent."""
	if frappe.db.exists("Custom Field", f"{dt}-{field_values['fieldname']}"):
		return
	frappe.get_doc({"doctype": "Custom Field", "dt": dt, **field_values}).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=dt)
	frappe.db.commit()


def remove_host_custom_field(dt: str, fieldname: str) -> None:
	name = f"{dt}-{fieldname}"
	if frappe.db.exists("Custom Field", name):
		frappe.delete_doc("Custom Field", name, ignore_permissions=True)
		frappe.clear_cache(doctype=dt)
		frappe.db.commit()


OBSOLETE_DRIFT_FIELDNAME = "custom_pea_abandoned_metric"


def ensure_obsolete_pea_custom_field() -> None:
	"""Create a staging-drift PEA-module custom field that current fixtures do not ship."""
	name = f"Stock Entry-{OBSOLETE_DRIFT_FIELDNAME}"
	if frappe.db.exists("Custom Field", name):
		return
	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "Stock Entry",
			"fieldname": OBSOLETE_DRIFT_FIELDNAME,
			"label": "Abandoned Metric",
			"fieldtype": "Data",
			"insert_after": "custom_stock_entry_purpose",
			"module": APP_MODULE,
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Stock Entry")
	frappe.db.commit()


def remove_obsolete_pea_custom_field() -> None:
	remove_property_setter("Stock Entry", OBSOLETE_DRIFT_FIELDNAME)
	remove_host_custom_field("Stock Entry", OBSOLETE_DRIFT_FIELDNAME)


def neutralize_module_pea_drift() -> dict[str, str]:
	"""Make live PEA custom fields outside current fixtures host-owned (module NULL).

	The shared dev site carries real staging-style drift. Flipping the module
	(rather than deleting fields) keeps every column and its data intact while
	making the drift invisible to the cutover's obsolete-field scan.
	"""
	from production_entry_app.production_entry_app.utils.legacy_time_cutover import (
		_fixture_custom_field_names,
	)

	rows = frappe.get_all("Custom Field", filters={"module": APP_MODULE}, fields=["name", "module"])
	neutralized: dict[str, str] = {}
	for row in rows:
		if row.name in _fixture_custom_field_names():
			continue
		frappe.db.set_value("Custom Field", row.name, "module", None, update_modified=False)
		neutralized[row.name] = row.module or ""
	if neutralized:
		frappe.db.commit()
	return neutralized


def restore_module_pea_drift(neutralized: dict[str, str]) -> None:
	for name, module in neutralized.items():
		if frappe.db.exists("Custom Field", name):
			frappe.db.set_value("Custom Field", name, "module", module or None, update_modified=False)
	if neutralized:
		frappe.db.commit()


def install_legacy_time_fields() -> None:
	"""Create the host-owned legacy time-capture fields if absent.

	Mirrors production: the three legacy Stock Entry sections (with leaf fields
	inside) and the legacy Workstation standard-SPM field.
	"""
	legacy_fields = (
		{"fieldname": "custom_operation_details", "label": "Operation Details", "fieldtype": "Section Break"},
		{
			"fieldname": "custom_workstation",
			"label": "Workstation",
			"fieldtype": "Link",
			"options": "Workstation",
			"insert_after": "custom_operation_details",
		},
		{
			"fieldname": "custom_actual_time",
			"label": "Actual Time",
			"fieldtype": "Section Break",
			"insert_after": "custom_workstation",
		},
		{
			"fieldname": "custom_actual_start_date",
			"label": "Actual Start Date",
			"fieldtype": "Datetime",
			"insert_after": "custom_actual_time",
		},
		{
			"fieldname": "custom_loss_time",
			"label": "Loss Time",
			"fieldtype": "Section Break",
			"insert_after": "custom_actual_start_date",
		},
	)
	for field_values in legacy_fields:
		ensure_host_custom_field("Stock Entry", field_values)
	ensure_host_custom_field(
		"Workstation", {"fieldname": "custom_standard_spm", "label": "Standard SPM", "fieldtype": "Float"}
	)


def remove_legacy_time_fields() -> None:
	"""Remove the legacy time-capture fields and any cutover hide property setters."""
	from production_entry_app.production_entry_app.utils.legacy_time_cutover import (
		unhide_legacy_time_fields,
	)

	unhide_legacy_time_fields()
	for dt, fieldname in LEGACY_TIME_FIELDS:
		remove_host_custom_field(dt, fieldname)
	remove_host_custom_field("Stock Entry", "custom_workstation")
	remove_host_custom_field("Stock Entry", "custom_actual_start_date")


def ensure_host_property_setter(doctype: str, fieldname: str, *, value: str) -> None:
	"""Create a host-owned (Manufacturing-module) hidden setter, if absent."""
	name = f"{doctype}-{fieldname}-hidden"
	if frappe.db.exists("Property Setter", name):
		return
	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": doctype,
			"field_name": fieldname,
			"property": "hidden",
			"property_type": "Check",
			"value": value,
			"module": HOST_MODULE,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


def ensure_client_script(name: str, *, enabled: bool = True) -> None:
	"""Create (or re-enable) a host client script with the given name."""
	if frappe.db.exists("Client Script", name):
		frappe.db.set_value("Client Script", name, "enabled", 1 if enabled else 0, update_modified=False)
		frappe.db.commit()
		return
	frappe.get_doc(
		{
			"doctype": "Client Script",
			"name": name,
			"dt": "Stock Entry",
			"enabled": 1 if enabled else 0,
			"script": "console.warn('host parity client script');",
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


def remove_client_script(name: str) -> None:
	if frappe.db.exists("Client Script", name):
		frappe.delete_doc("Client Script", name, ignore_permissions=True)
		frappe.db.commit()


def remove_property_setter(doctype: str, fieldname: str, property: str = "hidden") -> None:
	name = f"{doctype}-{fieldname}-{property}"
	if frappe.db.exists("Property Setter", name):
		frappe.delete_doc("Property Setter", name, ignore_permissions=True)
		frappe.db.commit()


def snapshot_module_property_setters() -> dict[str, dict]:
	"""Capture every app-module Property Setter row for exact restore."""
	rows = frappe.get_all(
		"Property Setter", filters={"module": APP_MODULE}, fields=list(_PROPERTY_SETTER_SNAPSHOT_FIELDS)
	)
	return {row["name"]: dict(row) for row in rows}


def restore_module_property_setters(snapshot: dict[str, dict]) -> None:
	"""Bring the app-module Property Setter rows back to the snapshotted state."""
	current = set(frappe.get_all("Property Setter", filters={"module": APP_MODULE}, pluck="name"))
	for name in sorted(current - set(snapshot)):
		frappe.delete_doc("Property Setter", name, ignore_permissions=True)
	for row in snapshot.values():
		if not frappe.db.exists("Property Setter", row["name"]):
			frappe.get_doc({"doctype": "Property Setter", **row}).insert(ignore_permissions=True)
		elif frappe.db.get_value("Property Setter", row["name"], "value") != row["value"]:
			frappe.db.set_value("Property Setter", row["name"], "value", row["value"])
	frappe.db.commit()


def ensure_legacy_workstation() -> str:
	"""Create (or return) a workstation carrying the legacy standard SPM value."""
	if frappe.db.exists("Workstation", "Host Parity Workstation"):
		return "Host Parity Workstation"
	frappe.get_doc(
		{
			"doctype": "Workstation",
			"workstation_name": "Host Parity Workstation",
			"custom_standard_spm": 42,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return "Host Parity Workstation"


def remove_legacy_workstation() -> None:
	if frappe.db.exists("Workstation", "Host Parity Workstation"):
		frappe.delete_doc("Workstation", "Host Parity Workstation", force=True, ignore_permissions=True)
		frappe.db.commit()


def make_legacy_stock_entry() -> str:
	"""Create a submitted Stock Entry carrying legacy time-capture values."""
	from production_entry_app.production_entry_app.utils.test_bootstrap import (
		ensure_item,
		ensure_warehouse,
		resolve_test_company,
	)

	company = resolve_test_company()
	abbr = frappe.db.get_value("Company", company, "abbr") or "TC"
	warehouse = ensure_warehouse(f"Host Parity WH - {abbr}", company)
	item = ensure_item("_Host Parity Item")
	workstation = ensure_legacy_workstation()
	doc = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"purpose": "Material Receipt",
			"stock_entry_type": "Material Receipt",
			"company": company,
			"items": [{"item_code": item, "t_warehouse": warehouse, "qty": 1, "basic_rate": 1}],
			"custom_workstation": workstation,
			"custom_actual_start_date": "2026-10-01 09:00:00",
		}
	).insert(ignore_permissions=True)
	doc.submit()
	return doc.name
