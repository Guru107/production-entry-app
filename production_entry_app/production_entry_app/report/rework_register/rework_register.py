from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, get_datetime

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	get_report_rows,
	new_interactive_report_timeout_guard,
)

_ENTRY_CHUNK_SIZE = 500
_MAX_ENTRY_ROWS = 10_000
_CHILD_PARENT_CHUNK_SIZE = 500
_ENTRY_FIELDS = [
	"name",
	"posting_date",
	"custom_pea_rework_type",
	"custom_pea_rework_workstation",
	"custom_pea_rework_actual_start",
	"custom_pea_rework_actual_end",
	"custom_pea_rework_cost",
]


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
	return _get_columns(), _get_rows(filters or {})


def _get_columns() -> list[dict]:
	return apply_system_precision(
		[
			{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 110},
			{
				"label": _("Rework Entry"),
				"fieldname": "rework_entry",
				"fieldtype": "Data",
				"width": 190,
			},
			{
				"label": _("Rework Type"),
				"fieldname": "rework_type",
				"fieldtype": "Data",
				"width": 160,
			},
			{
				"label": _("Workstation"),
				"fieldname": "workstation",
				"fieldtype": "Data",
				"width": 170,
			},
			{"label": _("Items + Qty"), "fieldname": "items", "fieldtype": "Data", "width": 260},
			{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 110},
			{
				"label": _("Duration (Hours)"),
				"fieldname": "duration_hours",
				"fieldtype": "Float",
				"width": 140,
			},
			{
				"label": _("Operators"),
				"fieldname": "operator_names",
				"fieldtype": "Data",
				"width": 220,
			},
			{
				"label": _("Operator Count"),
				"fieldname": "operator_count",
				"fieldtype": "Int",
				"width": 120,
			},
			{
				"label": _("Computed Cost"),
				"fieldname": "computed_cost",
				"fieldtype": "Currency",
				"width": 130,
			},
		]
	)


def _get_rows(filters: dict) -> list[dict]:
	rework_entry_types = get_report_rows(
		"Stock Entry Type",
		filters={"custom_pea_rework_entry": 1},
		pluck="name",
	)
	if not rework_entry_types:
		return []
	db_filters: dict = {"docstatus": 1, "stock_entry_type": ["in", rework_entry_types]}
	if filters.get("from_date") and filters.get("to_date"):
		db_filters["posting_date"] = ["between", [filters["from_date"], filters["to_date"]]]
	elif filters.get("from_date"):
		db_filters["posting_date"] = [">=", filters["from_date"]]
	elif filters.get("to_date"):
		db_filters["posting_date"] = ["<=", filters["to_date"]]
	if filters.get("rework_type"):
		db_filters["custom_pea_rework_type"] = filters["rework_type"]
	if filters.get("workstation"):
		db_filters["custom_pea_rework_workstation"] = filters["workstation"]
	if filters.get("item_code"):
		matching_parents = get_report_rows(
			"Stock Entry Detail",
			filters={
				"parenttype": "Stock Entry",
				"parentfield": "items",
				"item_code": filters["item_code"],
			},
			pluck="parent",
			limit_page_length=10_001,
		)
		db_filters["name"] = ["in", matching_parents or ["__no_matching_rework_entry__"]]
	entries = _get_entries(db_filters, rework_entry_types)
	parent_names = [entry.name for entry in entries]
	if not parent_names:
		return []
	item_rows = _get_child_rows(
		"Stock Entry Detail",
		parent_names,
		fields=["parent", "item_code", "qty", "idx"],
		parentfield="items",
	)
	operator_rows = _get_child_rows(
		"Rework Operator",
		parent_names,
		fields=["parent", "operator", "idx"],
		parentfield="custom_pea_rework_operators",
	)
	items_by_parent: defaultdict[str, list[dict]] = defaultdict(list)
	operators_by_parent: defaultdict[str, list[str]] = defaultdict(list)
	for row in item_rows:
		items_by_parent[row.parent].append(row)
	for row in operator_rows:
		if row.operator:
			operators_by_parent[row.parent].append(row.operator)

	rows = []
	for entry in sorted(entries, key=lambda row: (row.posting_date, row.name), reverse=True):
		items = items_by_parent[entry.name]
		operators = operators_by_parent[entry.name]
		start = get_datetime(entry.custom_pea_rework_actual_start)
		end = get_datetime(entry.custom_pea_rework_actual_end)
		rows.append(
			{
				"date": entry.posting_date,
				"rework_entry": entry.name,
				"rework_type": entry.custom_pea_rework_type,
				"workstation": entry.custom_pea_rework_workstation,
				"items": ", ".join(f"{row.item_code} ({flt(row.qty, 6):g})" for row in items),
				"total_qty": flt(sum(flt(row.qty) for row in items), 6),
				"duration_hours": flt((end - start).total_seconds() / 3600, 6),
				"operator_names": ", ".join(operators),
				"operator_count": len(operators),
				"computed_cost": flt(entry.custom_pea_rework_cost, 6),
			}
		)
	return rows


def _get_entries(
	filters: dict,
	rework_entry_types: list[str],
	*,
	chunk_size: int = _ENTRY_CHUNK_SIZE,
	max_rows: int = _MAX_ENTRY_ROWS,
) -> list[frappe._dict]:
	effective_chunk_size = max(int(chunk_size or _ENTRY_CHUNK_SIZE), 1)
	timeout_guard = new_interactive_report_timeout_guard(_("Rework Register"))
	rows: list[frappe._dict] = []
	last_name: str | None = None
	while True:
		timeout_guard()
		chunk = _fetch_entry_chunk(filters, rework_entry_types, last_name, effective_chunk_size)
		if not chunk:
			break
		if max_rows > 0 and len(rows) + len(chunk) > max_rows:
			frappe.throw(
				_("Rework Register exceeds {0} submitted entries. Narrow the filters and retry.").format(
					max_rows
				)
			)
		rows.extend(chunk)
		last_name = chunk[-1].name
		if len(chunk) < effective_chunk_size:
			break
	return rows


def _fetch_entry_chunk(
	filters: dict,
	rework_entry_types: list[str],
	last_name: str | None,
	chunk_size: int,
) -> list[frappe._dict]:
	query_filters: list[list] = [
		["docstatus", "=", 1],
		["stock_entry_type", "in", rework_entry_types],
	]
	for fieldname, condition in filters.items():
		if isinstance(condition, list | tuple) and len(condition) == 2:
			query_filters.append([fieldname, condition[0], condition[1]])
		else:
			query_filters.append([fieldname, "=", condition])
	if last_name:
		query_filters.append(["name", ">", last_name])
	return get_report_rows(
		"Stock Entry",
		filters=query_filters,
		fields=_ENTRY_FIELDS,
		order_by="name asc",
		limit_page_length=chunk_size,
	)


def _get_child_rows(
	doctype: str,
	parent_names: list[str],
	*,
	fields: list[str],
	parentfield: str,
	chunk_size: int = _CHILD_PARENT_CHUNK_SIZE,
) -> list[frappe._dict]:
	effective_chunk_size = max(int(chunk_size or _CHILD_PARENT_CHUNK_SIZE), 1)
	rows: list[frappe._dict] = []
	for offset in range(0, len(parent_names), effective_chunk_size):
		parent_chunk = parent_names[offset : offset + effective_chunk_size]
		rows.extend(
			get_report_rows(
				doctype,
				filters={
					"parent": ["in", parent_chunk],
					"parenttype": "Stock Entry",
					"parentfield": parentfield,
				},
				fields=fields,
				order_by="parent asc, idx asc",
				limit_page_length=0,
			)
		)
	return rows
