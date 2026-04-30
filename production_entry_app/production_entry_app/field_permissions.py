from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from production_entry_app.production_entry_app.access_control import (
	DEFAULT_READ_ROLE,
	DEFAULT_WRITE_ROLE,
	DOCPERM_FIELDS,
)

APP_MODULE: str = "Production Entry App"
PEA_FIELD_PERMLEVEL: int = 9


def ensure_pea_field_permissions(
	*, write_role: str | None = None, read_role: str | None = None, managed_roles: tuple[str | None, ...] = ()
) -> None:
	"""Ensure native Frappe permlevel access for app-owned custom fields on standard DocTypes."""
	effective_write_role, effective_read_role = _get_effective_access_roles(
		write_role=write_role, read_role=read_role
	)
	active_roles = _unique_roles(effective_write_role, effective_read_role)
	cleanup_roles = tuple(role for role in _unique_roles(*managed_roles) if role not in active_roles)
	for doctype in _get_pea_custom_field_doctypes():
		_validate_permlevel_is_pea_owned(doctype)
		_remove_stale_docperms(doctype=doctype, candidate_roles=cleanup_roles)
		_sync_docperm(doctype=doctype, role=effective_write_role, values=_write_permlevel_values())
		if effective_read_role != effective_write_role:
			_sync_docperm(doctype=doctype, role=effective_read_role, values=_read_permlevel_values())
		frappe.clear_cache(doctype=doctype)


def _get_effective_access_roles(*, write_role: str | None, read_role: str | None) -> tuple[str, str]:
	if write_role is not None and read_role is not None:
		return write_role, read_role

	from production_entry_app.production_entry_app import access_control

	configured_write_role, configured_read_role = access_control._get_setup_access_roles()
	return write_role or configured_write_role, read_role or configured_read_role


def _get_pea_custom_field_doctypes() -> tuple[str, ...]:
	rows = frappe.get_all(
		"Custom Field",
		filters={"module": APP_MODULE, "permlevel": PEA_FIELD_PERMLEVEL},
		fields=["dt"],
		order_by="dt asc",
	)
	return tuple(dict.fromkeys(str(row.get("dt")) for row in rows if row.get("dt")))


def _unique_roles(*roles: str | None) -> tuple[str, ...]:
	seen: dict[str, None] = {}
	for role in roles:
		cleaned = str(role or "").strip()
		if cleaned:
			seen.setdefault(cleaned, None)
	return tuple(seen)


def _remove_stale_docperms(*, doctype: str, candidate_roles: tuple[str, ...]) -> None:
	if not candidate_roles:
		return

	templates = _pea_docperm_templates()
	rows = frappe.get_all(
		"DocPerm",
		filters={"parent": doctype, "parenttype": "DocType", "parentfield": "permissions"},
		fields=["name", "role", "permlevel", *DOCPERM_FIELDS],
	)
	stale_names = [
		row["name"]
		for row in rows
		if row.get("role") in candidate_roles and _matches_any_docperm_template(row, templates)
	]
	for name in stale_names:
		frappe.delete_doc("DocPerm", name, ignore_permissions=True, force=True)


def _sync_docperm(*, doctype: str, role: str, values: dict[str, int]) -> None:
	existing_name = frappe.db.exists(
		"DocPerm",
		{
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": role,
			"permlevel": PEA_FIELD_PERMLEVEL,
		},
	)
	if existing_name:
		existing_values = frappe.db.get_value(
			"DocPerm",
			existing_name,
			["permlevel", *DOCPERM_FIELDS],
			as_dict=True,
		)
		if not existing_values or not _matches_any_docperm_template(
			existing_values, _pea_docperm_templates()
		):
			frappe.throw(
				_(
					"Existing permlevel {0} permission for role {1} on {2} is not managed by Production Entry App."
				).format(PEA_FIELD_PERMLEVEL, role, doctype),
				frappe.ValidationError,
			)
		frappe.db.set_value("DocPerm", existing_name, values, update_modified=False)
		return

	frappe.get_doc(
		{
			"doctype": "DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": role,
			"idx": _get_next_docperm_idx(doctype),
			**values,
		}
	).insert(ignore_permissions=True)


def _write_permlevel_values() -> dict[str, int]:
	values = _empty_docperm_values()
	values.update(
		{
			"permlevel": PEA_FIELD_PERMLEVEL,
			"select": 1,
			"read": 1,
			"write": 1,
			"print": 1,
			"email": 1,
			"export": 1,
			"report": 1,
		}
	)
	return values


def _read_permlevel_values() -> dict[str, int]:
	values = _empty_docperm_values()
	values.update(
		{
			"permlevel": PEA_FIELD_PERMLEVEL,
			"select": 1,
			"read": 1,
			"print": 1,
			"email": 1,
			"export": 1,
			"report": 1,
		}
	)
	return values


def _empty_docperm_values() -> dict[str, int]:
	return {
		"permlevel": PEA_FIELD_PERMLEVEL,
		"select": 0,
		"read": 0,
		"write": 0,
		"create": 0,
		"delete": 0,
		"submit": 0,
		"cancel": 0,
		"amend": 0,
		"report": 0,
		"export": 0,
		"import": 0,
		"share": 0,
		"print": 0,
		"email": 0,
		"if_owner": 0,
	}


def _pea_docperm_templates() -> tuple[dict[str, int], dict[str, int]]:
	return _write_permlevel_values(), _read_permlevel_values()


def _matches_any_docperm_template(row: dict[str, Any], templates: tuple[dict[str, int], ...]) -> bool:
	return any(_matches_docperm_template(row, template) for template in templates)


def _matches_docperm_template(row: dict[str, Any], template: dict[str, int]) -> bool:
	return all(
		int(row.get(field) or 0) == int(template.get(field) or 0) for field in ("permlevel", *DOCPERM_FIELDS)
	)


def _validate_permlevel_is_pea_owned(doctype: str) -> None:
	app_fieldnames = set(
		frappe.get_all(
			"Custom Field",
			filters={"dt": doctype, "module": APP_MODULE, "permlevel": PEA_FIELD_PERMLEVEL},
			pluck="fieldname",
		)
	)
	custom_conflicts = frappe.get_all(
		"Custom Field",
		filters={"dt": doctype, "permlevel": PEA_FIELD_PERMLEVEL, "module": ("!=", APP_MODULE)},
		pluck="fieldname",
	)
	standard_conflicts = [
		fieldname
		for fieldname in frappe.get_all(
			"DocField",
			filters={"parent": doctype, "parenttype": "DocType", "permlevel": PEA_FIELD_PERMLEVEL},
			pluck="fieldname",
		)
		if fieldname not in app_fieldnames
	]
	conflicts = tuple(dict.fromkeys([*custom_conflicts, *standard_conflicts]))
	if not conflicts:
		return

	frappe.throw(
		_("Permlevel {0} on {1} is already used by non-PEA field(s): {2}").format(
			PEA_FIELD_PERMLEVEL,
			doctype,
			", ".join(conflicts),
		),
		frappe.ValidationError,
	)


def _get_next_docperm_idx(doctype: str) -> int:
	rows: list[dict[str, Any]] = frappe.get_all(
		"DocPerm",
		filters={"parent": doctype, "parenttype": "DocType"},
		fields=["idx"],
		order_by="idx desc",
		limit=1,
	)
	if not rows:
		return 1
	return int(rows[0].get("idx") or 0) + 1
