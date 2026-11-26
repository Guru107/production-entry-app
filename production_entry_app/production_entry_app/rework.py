from __future__ import annotations

from collections import defaultdict
from typing import Any, NamedTuple

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Coalesce, Count, Min, Sum
from frappe.utils import flt

from production_entry_app.production_entry_app.utils.production_warehouses import (
	get_branch_warehouse_defaults,
	get_configured_scrap_warehouses,
)
from production_entry_app.production_entry_app.utils.rejection_warehouse import get_rejected_warehouses
from production_entry_app.production_entry_app.utils.stock_entry_branch import stock_entry_has_branch_field
from production_entry_app.production_entry_app.utils.stock_entry_type_flags import (
	is_rework_stock_entry_type,
)
from production_entry_app.production_entry_app.utils.system_precision import get_system_float_precision

SECONDS_PER_HOUR: int = 3600


class _ReworkRoute(NamedTuple):
	item_code: str
	source: str | None
	target: str | None


class PoolKey(NamedTuple):
	company: str
	branch: str
	item_code: str


class PoolScope(NamedTuple):
	"""Pool filters; a None company or branch means any, a blank branch is its own bucket."""

	item_codes: list[str] | None = None
	company: str | None = None
	branch: str | None = None
	exclude_stock_entry: str | None = None


@frappe.whitelist(methods=["GET"])
def get_pending_rework(
	item_code: str | None = None, company: str | None = None, branch: str | None = None
) -> list[dict[str, Any]]:
	"""Return the submitted, derived rework pool of one Company and Branch, optionally for one item."""
	if not frappe.has_permission("Stock Entry", "read"):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)
	if not company:
		frappe.throw(_("Company is required to read the Pending Rework Pool."))

	item_codes = [item_code] if item_code else None
	precision = get_system_float_precision()
	pending_by_item = _get_pending_rework_by_item(item_codes=item_codes, company=company, branch=branch)
	return [
		{"item_code": code, "pending_qty": flt(pending_by_item[code], precision)}
		for code in sorted(pending_by_item)
		if flt(pending_by_item[code], precision) > 0
	]


def validate_rework_submission(doc: Document) -> None:
	"""Reject a submitted rework entry that consumes more than the derived pool.

	This must run from ``before_submit``, before the Stock Entry is written as submitted,
	so every competing transaction acquires locks in Item -> Stock Entry order.
	Item-row locks serialize rework submissions for the same items. The pool is read
	after acquiring the locks, so a waiting transaction sees the preceding committed
	consumption before it validates. Sorted locking avoids cross-item deadlocks.
	"""
	if not is_rework_stock_entry_type(doc):
		return
	_validate_rework_route(doc)

	# Stock UOM on both sides: the pool is Rejection Breakup qty, the consumed side transfer_qty.
	requested_by_item: defaultdict[str, float] = defaultdict(float)
	for row in doc.get("items") or []:
		item_code = row.get("item_code")
		qty = flt(row.get("transfer_qty"))
		if item_code and qty > 0:
			requested_by_item[item_code] += qty
	if not requested_by_item:
		return

	item_codes = sorted(requested_by_item)
	_lock_items_for_rework_submission(item_codes)
	pending_by_item = _get_pending_rework_by_item(
		item_codes=item_codes,
		company=doc.get("company"),
		branch=doc.get("branch"),
		exclude_stock_entry=doc.get("name"),
		lock_rows=True,
	)
	precision = get_system_float_precision()
	for item_code in item_codes:
		requested_qty = flt(requested_by_item[item_code], precision)
		available_qty = flt(pending_by_item.get(item_code), precision)
		if requested_qty <= available_qty:
			continue
		frappe.throw(
			_("Cannot submit rework for item {0}: requested {1}. Available quantity is {2} in {3}.").format(
				frappe.bold(frappe.utils.escape_html(item_code)),
				requested_qty,
				available_qty,
				_describe_pool_bucket(doc.get("company"), doc.get("branch")),
			)
		)


def _describe_pool_bucket(company: str | None, branch: str | None) -> str:
	"""Name the bucket a rework entry was checked against, with a hint for a blank branch."""
	label = _("Company {0}").format(frappe.bold(frappe.utils.escape_html(company or "")))
	if not stock_entry_has_branch_field():
		return label
	if branch:
		return _("{0}, Branch {1}").format(label, frappe.bold(frappe.utils.escape_html(branch)))
	return _(
		"{0}, no Branch. Pending rework may exist under a Branch: set Branch on this entry and retry"
	).format(label)


def apply_rework_source_warehouse(doc: Document) -> None:
	"""Default blank Rework sources without hiding invalid explicit overrides."""
	if not is_rework_stock_entry_type(doc):
		return
	rejection_warehouse = get_branch_warehouse_defaults(doc.get("company"), doc.get("branch")).get(
		"rejection_warehouse"
	)
	if not rejection_warehouse:
		return
	if not doc.get("from_warehouse"):
		doc.from_warehouse = rejection_warehouse
	for row in doc.get("items") or []:
		if not row.get("s_warehouse"):
			row.s_warehouse = rejection_warehouse


def _validate_rework_route(doc: Document) -> None:
	"""Keep pool consumption on the configured rejection-to-good route."""
	warehouses = get_branch_warehouse_defaults(doc.get("company"), doc.get("branch"))
	rejection_warehouse = warehouses.get("rejection_warehouse")
	blocked_targets = {
		rejection_warehouse,
		warehouses.get("scrap_warehouse"),
		*get_configured_scrap_warehouses(doc.get("company")),
	}
	if rejection_warehouse and doc.get("from_warehouse") and doc.get("from_warehouse") != rejection_warehouse:
		frappe.throw(
			_("Rework must use the configured Rejection Warehouse {0} as its source.").format(
				frappe.bold(frappe.utils.escape_html(rejection_warehouse))
			)
		)
	routes = [
		_ReworkRoute(
			item_code=row.get("item_code") or "",
			source=row.get("s_warehouse") or doc.get("from_warehouse"),
			target=row.get("t_warehouse") or doc.get("to_warehouse"),
		)
		for row in doc.get("items") or []
		if flt(row.get("qty")) > 0
	]
	rejected_warehouses = get_rejected_warehouses(
		warehouse for route in routes for warehouse in (route.source, route.target)
	)
	for route in routes:
		if rejection_warehouse and route.source != rejection_warehouse:
			frappe.throw(
				_("Rework item {0} must use the configured Rejection Warehouse {1} as its source.").format(
					frappe.bold(frappe.utils.escape_html(route.item_code)),
					frappe.bold(frappe.utils.escape_html(rejection_warehouse)),
				)
			)
		elif not rejection_warehouse:
			_validate_explicit_rework_source_warehouse(route.item_code, route.source, rejected_warehouses)
		if not route.target or route.target in blocked_targets or route.target in rejected_warehouses:
			frappe.throw(
				_(
					"Rework item {0} must move to a good target warehouse, not a rejection or scrap warehouse."
				).format(frappe.bold(frappe.utils.escape_html(route.item_code)))
			)


def _validate_explicit_rework_source_warehouse(
	item_code: str,
	source: str | None,
	rejected_warehouses: set[str],
) -> None:
	if not source:
		frappe.throw(
			_("Rework item {0} must have a source Rejection Warehouse.").format(
				frappe.bold(frappe.utils.escape_html(item_code))
			)
		)
	if source not in rejected_warehouses:
		frappe.throw(
			_("Rework item {0} source Warehouse must be marked as Rejected Warehouse.").format(
				frappe.bold(frappe.utils.escape_html(item_code))
			)
		)


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
	company: str | None,
	branch: str | None,
	item_codes: list[str] | None = None,
	exclude_stock_entry: str | None = None,
	lock_rows: bool = False,
) -> dict[str, float]:
	"""Return the pool of one Company and Branch bucket per item."""
	scope = PoolScope(item_codes, company or "", branch or "", exclude_stock_entry)
	return {key.item_code: qty for key, qty in _get_pending_rework_pool(scope, lock_rows=lock_rows).items()}


def _get_pending_rework_pool(scope: PoolScope, *, lock_rows: bool = False) -> dict[PoolKey, float]:
	"""Return the pool keyed by (company, branch, item)."""
	pending: dict[PoolKey, float] = {}
	for sign, rows in (
		(1, _get_rework_produced(scope, lock_rows)),
		(-1, _get_rework_consumed(scope, lock_rows)),
	):
		for row in rows:
			# NULL and blank branches group apart in SQL but share one bucket.
			key = PoolKey(row.company or "", row.get("branch") or "", row.item_code)
			pending[key] = flt(pending.get(key)) + sign * flt(row.qty)
	return {key: max(flt(qty), 0.0) for key, qty in pending.items()}


def _pool_key_columns(StockEntry: Any) -> list[Any]:
	if stock_entry_has_branch_field():
		return [StockEntry.company, StockEntry.branch]
	return [StockEntry.company]


def _apply_pool_scope(query: Any, StockEntry: Any, scope: PoolScope) -> Any:
	if scope.company is not None:
		query = query.where(StockEntry.company == scope.company)
	# Stock Entry.branch is host-owned; without it the pool is per company only.
	if scope.branch is not None and stock_entry_has_branch_field():
		query = query.where(Coalesce(StockEntry.branch, "") == scope.branch)
	if scope.exclude_stock_entry:
		query = query.where(StockEntry.name != scope.exclude_stock_entry)
	return query


def _get_rework_produced(scope: PoolScope, lock_rows: bool) -> list[frappe._dict]:
	query, StockEntry, RejectionDetail, RejectionBreakup = _build_rework_produced_query(scope)
	key_columns = _pool_key_columns(StockEntry)
	query = query.select(*key_columns, RejectionDetail.item_code, Sum(RejectionBreakup.qty).as_("qty"))
	query = query.groupby(*key_columns, RejectionDetail.item_code)
	if lock_rows:
		query = query.for_update()
	return query.run(as_dict=True)


def _build_rework_produced_query(scope: PoolScope) -> tuple[Any, Any, Any, Any]:
	"""Build the submitted rework-flagged source scope shared by pool consumers."""
	StockEntry = frappe.qb.DocType("Stock Entry")
	StockEntryDetail = frappe.qb.DocType("Stock Entry Detail")
	RejectionDetail = (
		frappe.qb.from_(StockEntryDetail)
		.select(
			Min(StockEntryDetail.name).as_("name"),
			StockEntryDetail.parent,
			StockEntryDetail.item_code,
			Min(StockEntryDetail.t_warehouse).as_("t_warehouse"),
		)
		.where(StockEntryDetail.parenttype == "Stock Entry")
		.where(StockEntryDetail.custom_pea_is_rejection_item == 1)
		.groupby(StockEntryDetail.parent, StockEntryDetail.item_code)
	).as_("rejection_detail")
	RejectionItemCount = (
		frappe.qb.from_(RejectionDetail)
		.select(RejectionDetail.parent, Count(RejectionDetail.item_code).as_("item_count"))
		.groupby(RejectionDetail.parent)
	).as_("rejection_item_count")
	RejectionBreakup = frappe.qb.DocType("Rejection Breakup")
	blank_breakup_item = RejectionBreakup.custom_pea_rb_item_code.isnull() | (
		RejectionBreakup.custom_pea_rb_item_code == ""
	)
	item_matches_breakup = (RejectionBreakup.custom_pea_rb_item_code == RejectionDetail.item_code) | (
		blank_breakup_item & (RejectionItemCount.item_count == 1)
	)
	query = (
		frappe.qb.from_(RejectionBreakup)
		.join(StockEntry)
		.on((RejectionBreakup.parent == StockEntry.name) & (RejectionBreakup.parenttype == "Stock Entry"))
		.join(RejectionItemCount)
		.on(RejectionItemCount.parent == StockEntry.name)
		.join(RejectionDetail)
		.on((RejectionDetail.parent == StockEntry.name) & item_matches_breakup)
		.where(StockEntry.docstatus == 1)
		.where(RejectionBreakup.is_rework == 1)
	)
	if scope.item_codes is not None:
		query = query.where(RejectionDetail.item_code.isin(scope.item_codes))
	return _apply_pool_scope(query, StockEntry, scope), StockEntry, RejectionDetail, RejectionBreakup


def _get_rework_consumed(scope: PoolScope, lock_rows: bool) -> list[frappe._dict]:
	StockEntry = frappe.qb.DocType("Stock Entry")
	StockEntryDetail = frappe.qb.DocType("Stock Entry Detail")
	StockEntryType = frappe.qb.DocType("Stock Entry Type")
	key_columns = _pool_key_columns(StockEntry)
	query = (
		frappe.qb.from_(StockEntryDetail)
		.join(StockEntry)
		.on((StockEntryDetail.parent == StockEntry.name) & (StockEntryDetail.parenttype == "Stock Entry"))
		.join(StockEntryType)
		.on(StockEntry.stock_entry_type == StockEntryType.name)
		.select(*key_columns, StockEntryDetail.item_code, Sum(StockEntryDetail.transfer_qty).as_("qty"))
		.where(StockEntry.docstatus == 1)
		.where(StockEntryType.custom_pea_rework_entry == 1)
		.groupby(*key_columns, StockEntryDetail.item_code)
	)
	if scope.item_codes is not None:
		query = query.where(StockEntryDetail.item_code.isin(scope.item_codes))
	query = _apply_pool_scope(query, StockEntry, scope)
	if lock_rows:
		query = query.for_update()
	return query.run(as_dict=True)
