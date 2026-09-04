from __future__ import annotations

import frappe
from frappe.model.base_document import BaseDocument

from production_entry_app.production_entry_app.utils.production_warehouses import (
	get_production_warehouses,
	require_warehouse,
	validate_warehouse_companies,
)


def is_rejected_warehouse(warehouse: str | None) -> bool:
	if not warehouse:
		return False
	return bool(frappe.db.get_value("Warehouse", warehouse, "is_rejected_warehouse"))


def resolve_rejection_warehouse(doc: BaseDocument, preferred_warehouse: str | None = None) -> str:
	"""Resolve the configured rejection warehouse without silently using the FG warehouse."""
	if preferred_warehouse:
		validate_warehouse_companies(
			[{"company": doc.get("company"), "rejection_warehouse": preferred_warehouse}]
		)
		return preferred_warehouse
	return require_warehouse(get_production_warehouses(doc), "rejection_warehouse")
