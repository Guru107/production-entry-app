from __future__ import annotations

import frappe


def execute() -> None:
	frappe.db.sql(
		"""
		UPDATE `tabStock Entry`
		SET custom_stock_entry_purpose = purpose
		WHERE COALESCE(custom_stock_entry_purpose, '') = ''
			AND COALESCE(purpose, '') != ''
		"""
	)
	frappe.clear_cache(doctype="Stock Entry")
