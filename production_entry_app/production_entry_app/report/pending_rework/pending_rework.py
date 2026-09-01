from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	get_report_rows,
	new_interactive_report_timeout_guard,
)
from production_entry_app.production_entry_app.rework import (
	_build_rework_produced_query,
	_get_pending_rework_by_item,
)

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
	item_codes = [item_filter] if item_filter else None
	pending_by_item = {
		item_code: flt(qty, 6)
		for item_code, qty in _get_pending_rework_by_item(item_codes=item_codes).items()
		if flt(qty, 6) > 0
	}
	if not pending_by_item:
		return []

	timeout_guard = new_interactive_report_timeout_guard(_("Pending Rework"))
	contributions = _get_contributions(sorted(pending_by_item), timeout_guard=timeout_guard)
	contribution_pairs = {
		(row.item_code, row.rejection_warehouse)
		for row in contributions
		if row.get("item_code") and row.get("rejection_warehouse")
	}
	balances = _get_bin_balances(contribution_pairs)
	return _build_rows(pending_by_item, balances, contributions)


def _get_contributions(
	item_codes: list[str],
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
			item_codes,
			last_breakup_name,
			last_detail_name,
			effective_chunk_size,
		)
		if not chunk:
			break
		if max_rows > 0 and len(rows) + len(chunk) > max_rows:
			frappe.throw(
				_("Pending Rework exceeds {0} contributing rows. Filter by Item and retry.").format(
					max_rows
				)
			)
		rows.extend(chunk)
		last_breakup_name = chunk[-1].get("breakup_name")
		last_detail_name = chunk[-1].get("detail_name")
		if len(chunk) < effective_chunk_size:
			break
	return rows


def _fetch_contribution_chunk(
	item_codes: list[str],
	last_breakup_name: str | None,
	last_detail_name: str | None,
	chunk_size: int,
) -> list[frappe._dict]:
	query, StockEntry, StockEntryDetail, RejectionBreakup = _build_rework_produced_query(
		item_codes=item_codes
	)
	query = query.select(
		RejectionBreakup.name.as_("breakup_name"),
		StockEntryDetail.name.as_("detail_name"),
		StockEntry.name.as_("source_entry"),
		StockEntryDetail.item_code,
		StockEntryDetail.t_warehouse.as_("rejection_warehouse"),
		RejectionBreakup.rejection_reason,
		RejectionBreakup.qty.as_("flagged_rework_qty"),
	)
	if last_breakup_name and last_detail_name:
		query = query.where(
			(RejectionBreakup.name > last_breakup_name)
			| (
				(RejectionBreakup.name == last_breakup_name)
				& (StockEntryDetail.name > last_detail_name)
			)
		)
	return (
		query.orderby(RejectionBreakup.name)
		.orderby(StockEntryDetail.name)
		.limit(chunk_size)
		.run(as_dict=True)
	)


def _get_bin_balances(
	item_warehouse_pairs: set[tuple[str, str]],
	*,
	chunk_size: int = _BIN_ITEM_CHUNK_SIZE,
) -> dict[str, float]:
	if not item_warehouse_pairs:
		return {}
	pairs = set(item_warehouse_pairs)
	item_codes = sorted({item_code for item_code, _warehouse in pairs})
	effective_chunk_size = max(int(chunk_size or _BIN_ITEM_CHUNK_SIZE), 1)
	balances: defaultdict[str, float] = defaultdict(float)
	for offset in range(0, len(item_codes), effective_chunk_size):
		item_chunk = item_codes[offset : offset + effective_chunk_size]
		warehouses = sorted(
			{
				warehouse
				for item_code, warehouse in pairs
				if item_code in item_chunk and warehouse
			}
		)
		for row in get_report_rows(
			"Bin",
			filters={"item_code": ["in", item_chunk], "warehouse": ["in", warehouses]},
			fields=["item_code", "warehouse", "actual_qty"],
			limit_page_length=0,
		):
			pair = (row.get("item_code"), row.get("warehouse"))
			if pair in pairs:
				balances[pair[0]] += flt(row.get("actual_qty"))
	return dict(balances)


def _build_rows(
	pending_by_item: dict[str, float],
	balances: dict[str, float],
	contributions: list[frappe._dict],
) -> list[dict]:
	details_by_item: defaultdict[str, dict[tuple[str, str, str], float]] = defaultdict(
		lambda: defaultdict(float)
	)
	for row in contributions:
		key = (
			row.get("source_entry") or "",
			row.get("rejection_reason") or "",
			row.get("rejection_warehouse") or "",
		)
		details_by_item[row.item_code][key] += flt(row.get("flagged_rework_qty"))

	rows: list[dict] = []
	for item_code in sorted(pending_by_item):
		details = details_by_item.get(item_code, {})
		flagged_qty = flt(sum(details.values()), 6)
		pending_qty = flt(pending_by_item[item_code], 6)
		warehouse_balance = flt(balances.get(item_code), 6)
		source_entries = {source_entry for source_entry, _reason, _warehouse in details if source_entry}
		rows.append(
			{
				"item_code": item_code,
				"flagged_rework_qty": flagged_qty,
				"derived_pending_qty": pending_qty,
				"rejection_warehouse_balance": warehouse_balance,
				"pool_balance_difference": flt(pending_qty - warehouse_balance, 6),
				"source_entry_count": len(source_entries),
				"indent": 0,
			}
		)
		for (source_entry, reason, warehouse), qty in sorted(details.items()):
			rows.append(
				{
					"item_code": item_code,
					"rejection_reason": reason,
					"flagged_rework_qty": flt(qty, 6),
					"source_entry": source_entry,
					"rejection_warehouse": warehouse,
					"indent": 1,
				}
			)
	return rows
