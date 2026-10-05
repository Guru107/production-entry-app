"""Host-parity builders for the Downtime Reason adoption tests.

These helpers swap the app-owned ``Downtime Reason`` DocType for the host
(production) custom shape and back, mirroring the production site where the
DocType is a submittable custom master named by ``downtime_issue`` with a
custom ``Loss Time`` child table linked from Stock Entry.
"""

from __future__ import annotations

from pathlib import Path

import frappe

from production_entry_app.production_entry_app.utils.downtime_reason_adoption import (
	adoption_export_path,
)

HOST_MODULE = "Manufacturing"


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


def install_host_downtime_reason_doctype(*, extra_fields: tuple[dict, ...] = ()) -> None:
	"""Create the production host custom DocType: submittable, named by downtime_issue."""
	frappe.get_doc(
		{
			"doctype": "DocType",
			"__islocal": 1,
			"name": "Downtime Reason",
			"module": HOST_MODULE,
			"custom": 1,
			"is_submittable": 1,
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


def insert_host_downtime_reason(name: str, *, submit: bool = False) -> None:
	doc = frappe.get_doc(
		{
			"doctype": "Downtime Reason",
			"downtime_issue": name,
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()


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
