from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Sum
from frappe.utils import flt


@frappe.whitelist()
def get_pending_rework(item_code: str | None = None) -> list[dict[str, Any]]:
	"""Return the submitted, derived rework pool, optionally for one item."""
	if not frappe.has_permission("Stock Entry", "read"):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)

	item_codes = [item_code] if item_code else None
	pending_by_item = _get_pending_rework_by_item(item_codes=item_codes)
	return [
		{"item_code": code, "pending_qty": flt(pending_by_item[code], 6)} for code in sorted(pending_by_item)
	]


def validate_rework_submission(doc: Document) -> None:
	"""Reject a submitted rework entry that consumes more than the derived pool.

	This must run from ``before_submit``, before the Stock Entry is written as submitted,
	so every competing transaction acquires locks in Item -> Stock Entry order.
	Item-row locks serialize rework submissions for the same items. The pool is read
	after acquiring the locks, so a waiting transaction sees the preceding committed
	consumption before it validates. Sorted locking avoids cross-item deadlocks.
	"""
	if not _is_rework_stock_entry(doc):
		return

	requested_by_item: defaultdict[str, float] = defaultdict(float)
	for row in doc.get("items") or []:
		item_code = row.get("item_code")
		qty = flt(row.get("qty"))
		if item_code and qty > 0:
			requested_by_item[item_code] += qty
	if not requested_by_item:
		return

	item_codes = sorted(requested_by_item)
	_lock_items_for_rework_submission(item_codes)
	pending_by_item = _get_pending_rework_by_item(
		item_codes=item_codes,
		exclude_stock_entry=doc.get("name"),
		lock_rows=True,
	)
	for item_code in item_codes:
		requested_qty = flt(requested_by_item[item_code], 6)
		available_qty = flt(pending_by_item.get(item_code), 6)
		if requested_qty <= available_qty:
			continue
		frappe.throw(
			_("Cannot submit rework for item {0}: requested {1}. Available quantity is {2}.").format(
				frappe.bold(frappe.utils.escape_html(item_code)),
				requested_qty,
				available_qty,
			)
		)


def _is_rework_stock_entry(doc: Document) -> bool:
	stock_entry_type = doc.get("stock_entry_type")
	flags = getattr(doc, "flags", None)
	cached = flags.get("pea_rework_stock_entry_type") if flags is not None else None
	if cached and cached[0] == stock_entry_type:
		return bool(cached[1])
	is_rework = bool(
		stock_entry_type
		and frappe.db.get_value("Stock Entry Type", stock_entry_type, "custom_pea_rework_entry")
	)
	if flags is not None:
		flags.pea_rework_stock_entry_type = (stock_entry_type, is_rework)
	return is_rework


def _lock_items_for_rework_submission(item_codes: list[str]) -> None:
	Item = frappe.qb.DocType("Item")
	(
		frappe.qb.from_(Item)
		.select(Item.name)
		.where(Item.name.isin(item_codes))
		.orderby(Item.name)
		.for_update()
	).run()


def _get_pending_rework_by_item(
	*,
	item_codes: list[str] | None = None,
	exclude_stock_entry: str | None = None,
	lock_rows: bool = False,
) -> dict[str, float]:
	produced = _get_rework_produced(item_codes, exclude_stock_entry, lock_rows)
	consumed = _get_rework_consumed(item_codes, exclude_stock_entry, lock_rows)
	pending_by_item = {row.item_code: flt(row.qty) for row in produced}
	for row in consumed:
		pending_by_item[row.item_code] = flt(pending_by_item.get(row.item_code)) - flt(row.qty)
	return pending_by_item


def _get_rework_produced(
	item_codes: list[str] | None,
	exclude_stock_entry: str | None,
	lock_rows: bool,
) -> list[frappe._dict]:
	query, _stock_entry, StockEntryDetail, RejectionBreakup = _build_rework_produced_query(
		item_codes=item_codes,
		exclude_stock_entry=exclude_stock_entry,
	)
	query = query.select(StockEntryDetail.item_code, Sum(RejectionBreakup.qty).as_("qty")).groupby(
		StockEntryDetail.item_code
	)
	if lock_rows:
		query = query.for_update()
	return query.run(as_dict=True)


def _build_rework_produced_query(
	*,
	item_codes: list[str] | None = None,
	exclude_stock_entry: str | None = None,
) -> tuple[Any, Any, Any, Any]:
	"""Build the submitted rework-flagged source scope shared by pool consumers."""
	StockEntry = frappe.qb.DocType("Stock Entry")
	StockEntryDetail = frappe.qb.DocType("Stock Entry Detail")
	RejectionBreakup = frappe.qb.DocType("Rejection Breakup")
	item_matches_breakup = (
		(RejectionBreakup.item_code.isnull())
		| (RejectionBreakup.item_code == "")
		| (RejectionBreakup.item_code == StockEntryDetail.item_code)
	)
	query = (
		frappe.qb.from_(RejectionBreakup)
		.join(StockEntry)
		.on((RejectionBreakup.parent == StockEntry.name) & (RejectionBreakup.parenttype == "Stock Entry"))
		.join(StockEntryDetail)
		.on(
			(StockEntryDetail.parent == StockEntry.name)
			& (StockEntryDetail.parenttype == "Stock Entry")
			& (StockEntryDetail.custom_pea_is_rejection_item == 1)
			& item_matches_breakup
		)
		.where(StockEntry.docstatus == 1)
		.where(RejectionBreakup.is_rework == 1)
	)
	if item_codes is not None:
		query = query.where(StockEntryDetail.item_code.isin(item_codes))
	if exclude_stock_entry:
		query = query.where(StockEntry.name != exclude_stock_entry)
	return query, StockEntry, StockEntryDetail, RejectionBreakup


def _get_rework_consumed(
	item_codes: list[str] | None,
	exclude_stock_entry: str | None,
	lock_rows: bool,
) -> list[frappe._dict]:
	StockEntry = frappe.qb.DocType("Stock Entry")
	StockEntryDetail = frappe.qb.DocType("Stock Entry Detail")
	StockEntryType = frappe.qb.DocType("Stock Entry Type")
	query = (
		frappe.qb.from_(StockEntryDetail)
		.join(StockEntry)
		.on((StockEntryDetail.parent == StockEntry.name) & (StockEntryDetail.parenttype == "Stock Entry"))
		.join(StockEntryType)
		.on(StockEntry.stock_entry_type == StockEntryType.name)
		.select(StockEntryDetail.item_code, Sum(StockEntryDetail.qty).as_("qty"))
		.where(StockEntry.docstatus == 1)
		.where(StockEntryType.custom_pea_rework_entry == 1)
		.groupby(StockEntryDetail.item_code)
	)
	if item_codes is not None:
		query = query.where(StockEntryDetail.item_code.isin(item_codes))
	if exclude_stock_entry:
		query = query.where(StockEntry.name != exclude_stock_entry)
	if lock_rows:
		query = query.for_update()
	return query.run(as_dict=True)
