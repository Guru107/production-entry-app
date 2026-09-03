from __future__ import annotations

import frappe


def insert_pending_rework_source(
	*,
	stock_entry_type: str | None,
	breakups: list[tuple[str | None, float]],
	rejection_items: list[str],
) -> str:
	"""Insert a submitted production source for derived-pool integration tests."""
	stock_entry_name = f"POOL-SOURCE-{frappe.generate_hash(length=10)}"
	StockEntry = frappe.qb.DocType("Stock Entry")
	StockEntryDetail = frappe.qb.DocType("Stock Entry Detail")
	RejectionBreakup = frappe.qb.DocType("Rejection Breakup")
	(
		frappe.qb.into(StockEntry)
		.columns(StockEntry.name, StockEntry.docstatus, StockEntry.stock_entry_type)
		.insert(stock_entry_name, 1, stock_entry_type)
	).run()
	for item_code in rejection_items:
		(
			frappe.qb.into(StockEntryDetail)
			.columns(
				StockEntryDetail.name,
				StockEntryDetail.parent,
				StockEntryDetail.parenttype,
				StockEntryDetail.parentfield,
				StockEntryDetail.item_code,
				StockEntryDetail.qty,
				StockEntryDetail.custom_pea_is_rejection_item,
			)
			.insert(
				frappe.generate_hash(length=10),
				stock_entry_name,
				"Stock Entry",
				"items",
				item_code,
				1,
				1,
			)
		).run()
	for item_code, qty in breakups:
		(
			frappe.qb.into(RejectionBreakup)
			.columns(
				RejectionBreakup.name,
				RejectionBreakup.parent,
				RejectionBreakup.parenttype,
				RejectionBreakup.parentfield,
				RejectionBreakup.item_code,
				RejectionBreakup.qty,
				RejectionBreakup.is_rework,
			)
			.insert(
				frappe.generate_hash(length=10),
				stock_entry_name,
				"Stock Entry",
				"custom_pea_rejection_breakup",
				item_code or "",
				qty,
				1,
			)
		).run()
	return stock_entry_name
