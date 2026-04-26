from __future__ import annotations

import frappe

from production_entry_app.production_entry_app.access_control import DEFAULT_REQUIRED_ROLE


def before_install() -> None:
	if frappe.db.exists("Role", DEFAULT_REQUIRED_ROLE):
		return

	frappe.get_doc({"doctype": "Role", "role_name": DEFAULT_REQUIRED_ROLE}).insert(ignore_permissions=True)
