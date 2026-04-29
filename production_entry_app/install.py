from __future__ import annotations

import frappe

from production_entry_app.production_entry_app.access_control import DEFAULT_READ_ROLE, DEFAULT_WRITE_ROLE


def before_install() -> None:
	_ensure_role(DEFAULT_WRITE_ROLE)
	_ensure_role(DEFAULT_READ_ROLE)


def _ensure_role(role_name: str) -> None:
	if frappe.db.exists("Role", role_name):
		return

	frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert()
