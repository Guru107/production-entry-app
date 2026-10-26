from __future__ import annotations

import datetime
from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import flt, get_datetime, getdate

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	get_entry_output_quantities,
	get_report_rows,
	iter_stock_entries_in_chunks,
	stock_entry_qb_criteria,
)
from production_entry_app.production_entry_app.report.rework_register.rework_register import (
	_MAX_ENTRY_ROWS,
	_get_child_rows,
	_get_entries,
)
from production_entry_app.production_entry_app.rework import (
	SECONDS_PER_HOUR,
)
from production_entry_app.production_entry_app.utils.system_precision import (
	get_system_float_precision,
)

PPM_MULTIPLIER: int = 1_000_000
_NO_MATCHING_REWORK_ENTRY: str = "__no_matching_rework_entry__"
_PRODUCTION_ENTRY_FIELDS: list[str] = ["name", "posting_date", "fg_completed_qty", "custom_pea_shift"]


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict], None, dict | None]:
	columns = _get_columns()
	rows, daily_ppm_points = _get_rows(filters or {})
	return columns, rows, None, _get_chart(daily_ppm_points)


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
			{"label": _("Items + Qty"), "fieldname": "items", "fieldtype": "Data", "width": 260},
			{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 110},
			{
				"label": _("Rejection Reason"),
				"fieldname": "rejection_reason",
				"fieldtype": "Data",
				"width": 150,
			},
			{
				"label": _("Operation"),
				"fieldname": "operation",
				"fieldtype": "Data",
				"width": 130,
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
			{
				"label": _("Operators"),
				"fieldname": "operator_names",
				"fieldtype": "Data",
				"width": 220,
			},
			{
				"label": _("No. of Man"),
				"fieldname": "operator_count",
				"fieldtype": "Int",
				"width": 110,
			},
			{
				"label": _("Rework Hours"),
				"fieldname": "duration_hours",
				"fieldtype": "Float",
				"width": 120,
			},
			{
				"label": _("Daily REW PPM"),
				"fieldname": "daily_rew_ppm",
				"fieldtype": "Float",
				"width": 140,
			},
		]
	)


def _build_entry_filters(
	filters: dict,
	rework_entry_types: list[str],
	*,
	max_parent_matches: int = _MAX_ENTRY_ROWS,
) -> dict:
	db_filters: dict = {"docstatus": 1, "stock_entry_type": ["in", rework_entry_types]}
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	if from_date and to_date:
		db_filters["posting_date"] = ["between", [from_date, to_date]]
	elif from_date:
		db_filters["posting_date"] = [">=", from_date]
	elif to_date:
		db_filters["posting_date"] = ["<=", to_date]
	if filters.get("rework_type"):
		db_filters["custom_pea_rework_type"] = filters["rework_type"]
	if filters.get("workstation"):
		db_filters["custom_pea_rework_workstation"] = filters["workstation"]
	if filters.get("rejection_reason"):
		db_filters["custom_pea_rework_rejection_reason"] = filters["rejection_reason"]
	if filters.get("operation"):
		db_filters["custom_pea_rework_operation"] = filters["operation"]

	name_matches: list[set[str]] = []
	if filters.get("item_code"):
		name_matches.append(
			set(
				_get_matching_parent_names(
					"Stock Entry Detail",
					"items",
					"item_code",
					filters["item_code"],
					db_filters,
					max_matches=max_parent_matches,
					filter_label=_("Item"),
				)
			)
		)
	if filters.get("operator"):
		name_matches.append(
			set(
				_get_matching_parent_names(
					"Rework Operator",
					"custom_pea_rework_operators",
					"operator",
					filters["operator"],
					db_filters,
					max_matches=max_parent_matches,
					filter_label=_("Operator"),
				)
			)
		)
	if name_matches:
		matched = set.intersection(*name_matches)
		db_filters["name"] = ["in", sorted(matched) or [_NO_MATCHING_REWORK_ENTRY]]
	return db_filters


def _get_matching_parent_names(
	child_doctype: str,
	parentfield: str,
	child_field: str,
	child_value: str,
	parent_filters: dict,
	*,
	max_matches: int,
	filter_label: str,
) -> list[str]:
	"""Distinct parent IDs for a child-row filter, joined through the scoped parent entries.

	Scoping the join keeps unrelated child rows (drafts, other dates, non-rework
	types) from consuming the match budget, and the checked limit fails loudly
	instead of silently dropping matching entries.
	"""
	child = DocType(child_doctype)
	stock_entry = DocType("Stock Entry")
	query = (
		frappe.qb.from_(child)
		.inner_join(stock_entry)
		.on(stock_entry.name == child.parent)
		.select(child.parent)
		.distinct()
		.where(child.parenttype == "Stock Entry")
		.where(child.parentfield == parentfield)
		.where(child[child_field] == child_value)
	)
	for criterion in stock_entry_qb_criteria(stock_entry, parent_filters):
		query = query.where(criterion)
	rows = query.limit(max_matches + 1).run(as_dict=True)
	if len(rows) > max_matches:
		frappe.throw(
			_(
				"Daily Rework Report {0} filter matches more than {1} Stock Entries. Narrow the date range and retry."
			).format(filter_label, max_matches)
		)
	return [row.parent for row in rows if row.parent]


def _get_rows(filters: dict) -> tuple[list[dict], list[dict]]:
	rework_entry_types = get_report_rows(
		"Stock Entry Type",
		filters={"custom_pea_rework_entry": 1},
		pluck="name",
	)
	if not rework_entry_types:
		return [], []
	entries = _get_entries(
		_build_entry_filters(filters, rework_entry_types),
		rework_entry_types,
		report_label=_("Daily Rework Report"),
	)
	parent_names = [entry.name for entry in entries]
	if not parent_names:
		return [], []
	item_rows = _get_child_rows(
		"Stock Entry Detail",
		parent_names,
		fields=["parent", "item_code", "qty", "idx"],
		parentfield="items",
	)
	operator_rows = _get_child_rows(
		"Rework Operator",
		parent_names,
		fields=["parent", "operator", "actual_start", "actual_end", "idx"],
		parentfield="custom_pea_rework_operators",
	)

	precision = get_system_float_precision()
	items_by_parent: defaultdict[str, list[dict]] = defaultdict(list)
	operators_by_parent: defaultdict[str, list[str]] = defaultdict(list)
	hours_by_parent: defaultdict[str, float] = defaultdict(float)
	for row in item_rows:
		items_by_parent[row.parent].append(row)
	for row in operator_rows:
		if not row.operator:
			continue
		operators_by_parent[row.parent].append(row.operator)
		start = get_datetime(row.actual_start)
		end = get_datetime(row.actual_end)
		if start and end and end > start:
			hours_by_parent[row.parent] += (end - start).total_seconds() / SECONDS_PER_HOUR

	groups: dict[datetime.date, dict] = {}
	for entry in sorted(entries, key=lambda row: (row.posting_date, row.name)):
		day = getdate(entry.posting_date)
		items = items_by_parent[entry.name]
		operators = operators_by_parent[entry.name]
		qty = sum(flt(row.qty) for row in items)
		hours = hours_by_parent[entry.name]
		group = groups.setdefault(day, {"entries": [], "operators": set(), "qty": 0.0, "hours": 0.0})
		group["entries"].append(
			{
				"rework_entry": entry.name,
				"items": ", ".join(f"{row.item_code} ({flt(row.qty, precision):g})" for row in items),
				"total_qty": flt(qty, precision),
				"rejection_reason": entry.get("custom_pea_rework_rejection_reason") or "",
				"operation": entry.get("custom_pea_rework_operation") or "",
				"rework_type": entry.custom_pea_rework_type,
				"workstation": entry.custom_pea_rework_workstation,
				"operator_names": ", ".join(operators),
				"duration_hours": flt(hours, precision),
			}
		)
		group["operators"].update(operators)
		group["qty"] += qty
		group["hours"] += hours

	production_totals = _get_daily_production_totals(sorted(groups))
	rows: list[dict] = []
	daily_ppm_points: list[dict] = []
	for day in sorted(groups):
		group = groups[day]
		men = len(group["operators"])
		hours = flt(group["hours"], precision)
		raw_qty = group["qty"]
		production_qty = production_totals.get(day, 0.0)
		# PPM divides raw quantities; flt() rounds display values and the final PPM only.
		ppm = flt((raw_qty / production_qty) * PPM_MULTIPLIER, precision) if production_qty > 0 else 0
		qty = flt(raw_qty, precision)
		rows.append({"date": day, "operator_count": men, "duration_hours": hours, "bold": 1})
		rows.extend(group["entries"])
		rows.append(
			{
				"total_qty": qty,
				"operator_count": men,
				"duration_hours": hours,
				"daily_rew_ppm": ppm,
				"bold": 1,
			}
		)
		daily_ppm_points.append({"date": day.isoformat(), "ppm": ppm})
	return rows, daily_ppm_points


def _get_daily_production_totals(dates: list[datetime.date]) -> dict[datetime.date, float]:
	"""Day's raw total production: submitted production entries on Completed Shifts.

	Returned unrounded on purpose: the totals feed the PPM division, where
	rounding inputs first would distort the result.
	"""
	if not dates:
		return {}
	shift_rows = get_report_rows(
		"Shift",
		filters={
			"status": "Completed",
			"shift_date": ["in", [day.isoformat() for day in dates]],
		},
		fields=["name", "shift_date"],
		limit_page_length=0,
	)
	date_by_shift = {row.name: getdate(row.shift_date) for row in shift_rows}
	if not date_by_shift:
		return {}
	totals: defaultdict[datetime.date, float] = defaultdict(float)
	for entries in iter_stock_entries_in_chunks(
		{"docstatus": 1, "custom_pea_shift": ["in", sorted(date_by_shift)]},
		_PRODUCTION_ENTRY_FIELDS,
		order_by="posting_date asc, name asc",
	):
		for entry in entries:
			day = date_by_shift.get(entry.get("custom_pea_shift"))
			if day is not None:
				totals[day] += get_entry_output_quantities(entry).total_qty
	return dict(totals)


def _get_chart(daily_ppm_points: list[dict]) -> dict | None:
	if not daily_ppm_points:
		return None
	return {
		"data": {
			"labels": [point["date"] for point in daily_ppm_points],
			"datasets": [
				{
					"name": _("Daily REW PPM"),
					"values": [point["ppm"] for point in daily_ppm_points],
				},
			],
		},
		"type": "bar",
		"height": 280,
		"axisOptions": {"xAxisMode": "tick", "xIsSeries": 1},
	}
