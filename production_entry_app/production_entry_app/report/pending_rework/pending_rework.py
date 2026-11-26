from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

import frappe
from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	get_report_rows,
	new_interactive_report_timeout_guard,
)
from production_entry_app.production_entry_app.rework import (
	PoolKey,
	PoolScope,
	_build_rework_produced_query,
	_get_pending_rework_pool,
	_pool_key_columns,
)
from production_entry_app.production_entry_app.utils.system_precision import get_system_float_precision

_CONTRIBUTION_CHUNK_SIZE = 500
_MAX_CONTRIBUTION_ROWS = 10_000
_BIN_ITEM_CHUNK_SIZE = 200


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
	filters = filters or {}
	return _get_columns(), _get_rows(filters)


def _get_columns() -> list[dict]:
	return apply_system_precision(
		[
			{
				"label": _("Company"),
				"fieldname": "company",
				"fieldtype": "Link",
				"options": "Company",
				"width": 160,
			},
			{
				"label": _("Branch"),
				"fieldname": "branch",
				"fieldtype": "Link",
				"options": "Branch",
				"width": 140,
			},
			{
				"label": _("Item Code"),
				"fieldname": "item_code",
				"fieldtype": "Link",
				"options": "Item",
				"width": 200,
			},
			{
				"label": _("Rejection Reason"),
				"fieldname": "rejection_reason",
				"fieldtype": "Data",
				"width": 180,
			},
			{
				"label": _("Flagged Rework Qty"),
				"fieldname": "flagged_rework_qty",
				"fieldtype": "Float",
				"width": 150,
			},
			{
				"label": _("Derived Pending Qty"),
				"fieldname": "derived_pending_qty",
				"fieldtype": "Float",
				"width": 160,
			},
			{
				"label": _("Rejection Warehouse Balance"),
				"fieldname": "rejection_warehouse_balance",
				"fieldtype": "Float",
				"width": 210,
			},
			{
				"label": _("Pool - Warehouse"),
				"fieldname": "pool_balance_difference",
				"fieldtype": "Float",
				"width": 160,
			},
			{
				"label": _("Source Entries"),
				"fieldname": "source_entry_count",
				"fieldtype": "Int",
				"width": 110,
			},
			{
				"label": _("Contributing Production Entry"),
				"fieldname": "source_entry",
				"fieldtype": "Data",
				"width": 220,
			},
			{
				"label": _("Rejection Warehouse"),
				"fieldname": "rejection_warehouse",
				"fieldtype": "Data",
				"width": 220,
			},
		]
	)


def _get_rows(filters: dict) -> list[dict]:
	item_filter = filters.get("item_code")
	scope = PoolScope(
		item_codes=[item_filter] if item_filter else None,
		company=filters.get("company") or None,
		branch=filters.get("branch") or None,
	)
	precision = get_system_float_precision()
	pending_by_key = {
		key: flt(qty, precision)
		for key, qty in _get_pending_rework_pool(scope).items()
		if flt(qty, precision) > 0
	}
	if not pending_by_key:
		return []

	timeout_guard = new_interactive_report_timeout_guard(_("Pending Rework"))
	contributions = _get_contributions(
		scope._replace(item_codes=sorted({key.item_code for key in pending_by_key})),
		timeout_guard=timeout_guard,
	)
	contribution_pairs = {
		(row.item_code, row.rejection_warehouse)
		for row in contributions
		if row.get("item_code") and row.get("rejection_warehouse")
	}
	balances = _get_bin_balances(contribution_pairs)
	return _build_rows(pending_by_key, balances, contributions, precision)


def _get_contributions(
	scope: PoolScope,
	*,
	chunk_size: int = _CONTRIBUTION_CHUNK_SIZE,
	max_rows: int = _MAX_CONTRIBUTION_ROWS,
	timeout_guard: Callable[[], None] | None = None,
) -> list[frappe._dict]:
	effective_chunk_size = max(int(chunk_size or _CONTRIBUTION_CHUNK_SIZE), 1)
	guard = timeout_guard or (lambda: None)
	rows: list[frappe._dict] = []
	last_breakup_name: str | None = None
	last_detail_name: str | None = None
	while True:
		guard()
		chunk = _fetch_contribution_chunk(
			scope,
			last_breakup_name,
			last_detail_name,
			effective_chunk_size,
		)
		if not chunk:
			break
		if max_rows > 0 and len(rows) + len(chunk) > max_rows:
			frappe.throw(
				_("Pending Rework exceeds {0} contributing rows. Filter by Item and retry.").format(max_rows)
			)
		rows.extend(chunk)
		last_breakup_name = chunk[-1].get("breakup_name")
		last_detail_name = chunk[-1].get("detail_name")
		if len(chunk) < effective_chunk_size:
			break
	return rows


def _fetch_contribution_chunk(
	scope: PoolScope,
	last_breakup_name: str | None,
	last_detail_name: str | None,
	chunk_size: int,
) -> list[frappe._dict]:
	query, StockEntry, RejectionDetail, RejectionBreakup = _build_rework_produced_query(scope)
	query = query.select(
		*_pool_key_columns(StockEntry),
		RejectionBreakup.name.as_("breakup_name"),
		RejectionDetail.name.as_("detail_name"),
		StockEntry.name.as_("source_entry"),
		RejectionDetail.item_code,
		RejectionDetail.t_warehouse.as_("rejection_warehouse"),
		RejectionBreakup.rejection_reason,
		RejectionBreakup.qty.as_("flagged_rework_qty"),
	)
	if last_breakup_name and last_detail_name:
		query = query.where(
			(RejectionBreakup.name > last_breakup_name)
			| ((RejectionBreakup.name == last_breakup_name) & (RejectionDetail.name > last_detail_name))
		)
	return (
		query.orderby(RejectionBreakup.name).orderby(RejectionDetail.name).limit(chunk_size).run(as_dict=True)
	)


def _get_bin_balances(
	item_warehouse_pairs: set[tuple[str, str]],
	*,
	chunk_size: int = _BIN_ITEM_CHUNK_SIZE,
) -> dict[tuple[str, str], float]:
	if not item_warehouse_pairs:
		return {}
	pairs = set(item_warehouse_pairs)
	item_codes = sorted({item_code for item_code, _warehouse in pairs})
	effective_chunk_size = max(int(chunk_size or _BIN_ITEM_CHUNK_SIZE), 1)
	balances: dict[tuple[str, str], float] = {}
	for offset in range(0, len(item_codes), effective_chunk_size):
		item_chunk = item_codes[offset : offset + effective_chunk_size]
		warehouses = sorted(
			{warehouse for item_code, warehouse in pairs if item_code in item_chunk and warehouse}
		)
		for row in get_report_rows(
			"Bin",
			filters={"item_code": ["in", item_chunk], "warehouse": ["in", warehouses]},
			fields=["item_code", "warehouse", "actual_qty"],
			limit_page_length=0,
		):
			pair = (row.get("item_code"), row.get("warehouse"))
			if pair in pairs:
				balances[pair] = flt(row.get("actual_qty"))
	return balances


def _build_rows(
	pending_by_key: dict[PoolKey, float],
	balances: dict[tuple[str, str], float],
	contributions: list[frappe._dict],
	precision: int,
) -> list[dict]:
	details_by_key: defaultdict[PoolKey, dict[tuple[str, str, str], float]] = defaultdict(
		lambda: defaultdict(float)
	)
	for row in contributions:
		pool_key = PoolKey(row.get("company") or "", row.get("branch") or "", row.item_code)
		key = (
			row.get("source_entry") or "",
			row.get("rejection_reason") or "",
			row.get("rejection_warehouse") or "",
		)
		details_by_key[pool_key][key] += flt(row.get("flagged_rework_qty"))

	rows: list[dict] = []
	for pool_key in sorted(pending_by_key):
		details = details_by_key.get(pool_key, {})
		bucket = pool_key._asdict()
		flagged_qty = flt(sum(details.values()), precision)
		pending_qty = flt(pending_by_key[pool_key], precision)
		warehouses = {warehouse for _source, _reason, warehouse in details if warehouse}
		warehouse_balance = flt(
			sum(flt(balances.get((pool_key.item_code, warehouse))) for warehouse in warehouses), precision
		)
		source_entries = {source_entry for source_entry, _reason, _warehouse in details if source_entry}
		rows.append(
			{
				**bucket,
				"flagged_rework_qty": flagged_qty,
				"derived_pending_qty": pending_qty,
				"rejection_warehouse_balance": warehouse_balance,
				"pool_balance_difference": flt(pending_qty - warehouse_balance, precision),
				"source_entry_count": len(source_entries),
				"indent": 0,
			}
		)
		for (source_entry, reason, warehouse), qty in sorted(details.items()):
			rows.append(
				{
					**bucket,
					"rejection_reason": reason,
					"flagged_rework_qty": flt(qty, precision),
					"source_entry": source_entry,
					"rejection_warehouse": warehouse,
					"indent": 1,
				}
			)
	return rows
