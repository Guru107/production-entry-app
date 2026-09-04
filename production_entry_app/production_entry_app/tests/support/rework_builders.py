from __future__ import annotations

import frappe


def insert_pending_rework_source(
	*,
	stock_entry_type: str | None,
	stock_entry_name: str | None = None,
	purpose: str | None = None,
	breakups: list[tuple[str | None, float] | tuple[str | None, str | None, float]],
	rejection_items: list[str],
	rejection_warehouse: str | None = None,
) -> str:
	"""Insert a submitted production source for derived-pool integration tests."""
	stock_entry_name = stock_entry_name or f"POOL-SOURCE-{frappe.generate_hash(length=10)}"
	StockEntry = frappe.qb.DocType("Stock Entry")
	StockEntryDetail = frappe.qb.DocType("Stock Entry Detail")
	RejectionBreakup = frappe.qb.DocType("Rejection Breakup")
	(
		frappe.qb.into(StockEntry)
		.columns(StockEntry.name, StockEntry.docstatus, StockEntry.stock_entry_type, StockEntry.purpose)
		.insert(stock_entry_name, 1, stock_entry_type, purpose)
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
				StockEntryDetail.t_warehouse,
				StockEntryDetail.custom_pea_is_rejection_item,
			)
			.insert(
				frappe.generate_hash(length=10),
				stock_entry_name,
				"Stock Entry",
				"items",
				item_code,
				1,
				rejection_warehouse,
				1,
			)
		).run()
	for breakup in breakups:
		if len(breakup) == 2:
			item_code, qty = breakup
			rejection_reason = None
		else:
			item_code, rejection_reason, qty = breakup
		(
			frappe.qb.into(RejectionBreakup)
			.columns(
				RejectionBreakup.name,
				RejectionBreakup.parent,
				RejectionBreakup.parenttype,
				RejectionBreakup.parentfield,
				RejectionBreakup.item_code,
				RejectionBreakup.rejection_reason,
				RejectionBreakup.qty,
				RejectionBreakup.is_rework,
			)
			.insert(
				frappe.generate_hash(length=10),
				stock_entry_name,
				"Stock Entry",
				"custom_pea_rejection_breakup",
				item_code or "",
				rejection_reason,
				qty,
				1,
			)
		).run()
	return stock_entry_name
