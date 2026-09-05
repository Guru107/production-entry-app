from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe.model.base_document import BaseDocument

from production_entry_app.production_entry_app.utils.production_warehouses import (
	get_production_warehouses,
	require_warehouse,
	validate_warehouse_companies,
)


def get_rejected_warehouses(warehouses: Iterable[str | None]) -> set[str]:
	"""Return which of the given warehouses are marked as rejected, in one query."""
	names = {warehouse for warehouse in warehouses if warehouse}
	if not names:
		return set()
	Warehouse = frappe.qb.DocType("Warehouse")
	rows = (
		frappe.qb.from_(Warehouse)
		.select(Warehouse.name)
		.where(Warehouse.name.isin(list(names)))
		.where(Warehouse.is_rejected_warehouse == 1)
		.run()
	)
	return {row[0] for row in rows}


def resolve_rejection_warehouse(doc: BaseDocument, preferred_warehouse: str | None = None) -> str:
	"""Resolve the configured rejection warehouse without silently using the FG warehouse."""
	if preferred_warehouse:
		validate_warehouse_companies(
			[{"company": doc.get("company"), "rejection_warehouse": preferred_warehouse}]
		)
		return preferred_warehouse
	return require_warehouse(get_production_warehouses(doc), "rejection_warehouse")
