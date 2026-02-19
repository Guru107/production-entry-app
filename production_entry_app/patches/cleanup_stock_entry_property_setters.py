from __future__ import annotations

import frappe


def execute() -> None:
	legacy_property_setters = [
		"Stock Entry-section_break_7qsm-hidden",
		"Stock Entry-bom_info_section-collapsible_depends_on",
	]

	for name in legacy_property_setters:
		if not frappe.db.exists("Property Setter", name):
			continue
		frappe.delete_doc("Property Setter", name, force=True, ignore_permissions=True)

	frappe.clear_cache(doctype="Stock Entry")
