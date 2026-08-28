from __future__ import annotations

import frappe
from frappe import _
from frappe.model.base_document import BaseDocument


def resolve_rejection_warehouse(doc: BaseDocument, preferred_warehouse: str | None = None) -> str:
	"""Resolve the configured rejection warehouse without silently using the FG warehouse."""
	if preferred_warehouse:
		return preferred_warehouse

	if doc.get("custom_pea_shift"):
		warehouse = frappe.db.get_value("Shift", doc.get("custom_pea_shift"), "rejection_warehouse")
		if warehouse:
			return warehouse

	settings_meta = frappe.get_meta("Production Entry Settings", cached=True)
	if settings_meta.has_field("shift_rejection_warehouse"):
		warehouse = frappe.db.get_single_value("Production Entry Settings", "shift_rejection_warehouse")
		if warehouse:
			return warehouse

	frappe.throw(_("Please set a Rejection Warehouse on the Shift or in Production Entry Settings."))
