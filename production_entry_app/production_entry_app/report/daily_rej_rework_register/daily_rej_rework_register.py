from __future__ import annotations

import datetime
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, getdate

from production_entry_app.production_entry_app.report.report_utils import (
	apply_system_precision,
	build_stock_entry_filters,
	get_entry_output_quantities,
	get_entry_report_operation,
	get_report_rows,
	iter_stock_entries_in_chunks,
	new_interactive_report_timeout_guard,
)
from production_entry_app.production_entry_app.rework import SECONDS_PER_HOUR
from production_entry_app.production_entry_app.utils.system_precision import get_system_float_precision

PPM_MULTIPLIER: int = 1_000_000
_CHILD_PARENT_CHUNK_SIZE: int = 500
_MAX_REWORK_ENTRIES: int = 10_000
_ENTRY_FIELDS: list[str] = ["name", "fg_completed_qty", "custom_pea_operation"]


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
	return _get_columns(), _get_rows(filters or {})


def _get_columns() -> list[dict]:
	return apply_system_precision(
		[
			{
				"label": _("Production Date"),
				"fieldname": "production_date",
				"fieldtype": "Date",
				"width": 120,
			},
			{
				"label": _("Total FG Qty for Day"),
				"fieldname": "day_fg_qty",
				"fieldtype": "Float",
				"width": 150,
			},
			{
				"label": _("No. of Operators(working)"),
				"fieldname": "operator_count",
				"fieldtype": "Int",
				"width": 170,
			},
			{"label": _("Time(hrs.)"), "fieldname": "rework_hours", "fieldtype": "Float", "width": 110},
			{
				"label": _("Defective Item Code"),
				"fieldname": "defective_item_code",
				"fieldtype": "Link",
				"options": "Item",
				"width": 180,
			},
			{
				"label": _("Rejection Reason"),
				"fieldname": "rejection_reason",
				"fieldtype": "Data",
				"width": 160,
			},
			{"label": _("Rejection Qty"), "fieldname": "rejection_qty", "fieldtype": "Float", "width": 130},
			{"label": _("Rework Qty"), "fieldname": "rework_qty", "fieldtype": "Float", "width": 120},
			{
				"label": _("Rejection Stage"),
				"fieldname": "rejection_stage",
				"fieldtype": "Data",
				"width": 140,
			},
			{
				"label": _("Finished Goods Qty"),
				"fieldname": "finished_goods_qty",
				"fieldtype": "Float",
				"width": 150,
			},
			{"label": _("Rej PPM"), "fieldname": "rej_ppm", "fieldtype": "Float", "width": 110},
			{"label": _("Rework PPM"), "fieldname": "rework_ppm", "fieldtype": "Float", "width": 130},
			{
				"label": _("Responsibility Remark"),
				"fieldname": "responsibility_remark",
				"fieldtype": "Data",
				"width": 180,
			},
			{"label": _("Reinspection"), "fieldname": "reinspection", "fieldtype": "Data", "width": 150},
			{"label": _("Operator Name"), "fieldname": "operator_name", "fieldtype": "Data", "width": 200},
		]
	)


def _get_rows(filters: dict) -> list[dict]:
	timeout_guard = new_interactive_report_timeout_guard(_("Daily Rej Rework Register"))
	entries: list[dict] = []
	for chunk in iter_stock_entries_in_chunks(
		build_stock_entry_filters(filters, filter_keys=("custom_pea_shift", "custom_pea_operation")),
		_ENTRY_FIELDS,
	):
		timeout_guard()
		entries.extend(entry for entry in chunk if entry.get("production_date"))
	if not entries:
		return []

	entry_by_name = {entry["name"]: entry for entry in entries}
	entry_names = sorted(entry_by_name)
	breakup_rows = _get_child_rows(
		"Rejection Breakup",
		entry_names,
		fields=["parent", "item_code", "rejection_reason", "qty", "is_rework", "idx"],
		parentfield="custom_pea_rejection_breakup",
	)
	if not breakup_rows:
		return []
	# The single-rejection-item fallback reads every in-scope Stock Entry Detail
	# row; only pay for it when some breakup row actually has a blank item.
	fallback_items = (
		_get_single_rejection_items(entry_names)
		if any(not row.get("item_code") for row in breakup_rows)
		else {}
	)

	item_filter = filters.get("item_code")
	reason_filter = filters.get("rejection_reason")
	line_rows: list[dict] = []
	unresolved_blank_parents: set[str] = set()
	for row in breakup_rows:
		entry = entry_by_name.get(row.get("parent"))
		if not entry:
			continue
		item_code = row.get("item_code") or fallback_items.get(row.get("parent"), "")
		if item_filter and item_code != item_filter:
			continue
		if reason_filter and row.get("rejection_reason") != reason_filter:
			continue
		if not item_code and not row.get("item_code"):
			# Legacy rows can predate the single-rejection-item validation; log so
			# the ungroupable line is diagnosable instead of silently zero-rework.
			unresolved_blank_parents.add(row.get("parent"))
		line_rows.append(
			{
				"day": getdate(entry["production_date"]),
				"parent": entry["name"],
				"idx": row.get("idx") or 0,
				"defective_item_code": item_code,
				"rejection_reason": row.get("rejection_reason"),
				# A breakup line is either scrap (rejection) or reworkable: its qty
				# shows under exactly one of Rejection Qty / Rework Qty.
				"rejection_qty": 0.0 if row.get("is_rework") else flt(row.get("qty")),
				"rework_qty": flt(row.get("qty")) if row.get("is_rework") else 0.0,
				"rejection_stage": get_entry_report_operation(entry),
				"finished_goods_qty": get_entry_output_quantities(entry).total_qty,
			}
		)
	if not line_rows:
		return []
	for parent in sorted(unresolved_blank_parents):
		frappe.log_error(
			title=_("Daily Rej Rework Register: unresolved rejection item"),
			message=_(
				"Rejection Breakup rows on {0} have a blank Item Code that cannot be resolved; "
				"they group under an empty item and match no rework."
			).format(parent),
		)
	line_rows.sort(key=lambda row: (row["day"], row["parent"], row["idx"]))

	day_totals = _get_daily_fg_totals(sorted({row["day"] for row in line_rows}))
	rework_by_day_item, rework_by_day = _get_rework_by_day_item(line_rows)

	precision = get_system_float_precision()
	rows: list[dict] = []
	lines_by_day: defaultdict[datetime.date, list[dict]] = defaultdict(list)
	for line in line_rows:
		lines_by_day[line["day"]].append(line)
	for day in sorted(lines_by_day):
		day_fg = day_totals.get(day, 0.0)
		day_rework = rework_by_day.get(day) or {}
		day_rejection_qty = sum(line["rejection_qty"] for line in lines_by_day[day])
		# The subtotal sums the lines above it: declared reworkable qty per reason.
		day_declared_rework_qty = sum(line["rework_qty"] for line in lines_by_day[day])
		rows.append(
			{
				"production_date": day,
				"day_fg_qty": flt(day_fg, precision),
				"operator_count": len(day_rework.get("operators", ())),
				"rework_hours": flt(day_rework.get("hours", 0.0), precision),
				"bold": 1,
			}
		)
		# Group the day's lines by item: the item row carries the same-day, same-item
		# rework block once; its rejection lines list only per-line rejection data.
		lines_by_item: defaultdict[str, list[dict]] = defaultdict(list)
		for line in lines_by_day[day]:
			lines_by_item[line["defective_item_code"]].append(line)
		for item_code in sorted(lines_by_item):
			rework = rework_by_day_item.get((day, item_code)) or {}
			rows.append(
				{
					"production_date": day,
					"day_fg_qty": flt(day_fg, precision),
					"defective_item_code": item_code,
					"operator_count": len(rework.get("operators", ())),
					"rework_hours": flt(rework.get("hours", 0.0), precision),
					"rework_qty": flt(rework.get("qty", 0.0), precision),
					"rework_ppm": flt(rework.get("qty", 0.0) / day_fg * PPM_MULTIPLIER, precision)
					if day_fg > 0
					else 0,
					"responsibility_remark": ", ".join(rework.get("responsibility", ())),
					"reinspection": ", ".join(rework.get("reinspection", ())),
					"operator_name": ", ".join(rework.get("operators", ())),
					"bold": 1,
				}
			)
			for line in lines_by_item[item_code]:
				rows.append(
					{
						"rejection_reason": line["rejection_reason"],
						"rejection_qty": flt(line["rejection_qty"], precision),
						# Line-level Rework Qty is the declared reworkable quantity for
						# that reason; the item row above carries the actual rework.
						"rework_qty": flt(line["rework_qty"], precision),
						# PPM divides raw quantities; flt() rounds the final value only.
						"rej_ppm": flt(line["rejection_qty"] / day_fg * PPM_MULTIPLIER, precision)
						if day_fg > 0
						else 0,
						"rework_ppm": flt(line["rework_qty"] / day_fg * PPM_MULTIPLIER, precision)
						if day_fg > 0
						else 0,
						"rejection_stage": line["rejection_stage"],
						"finished_goods_qty": flt(line["finished_goods_qty"], precision),
					}
				)
		rows.append(
			{
				"production_date": day,
				"rejection_qty": flt(day_rejection_qty, precision),
				"rework_qty": flt(day_declared_rework_qty, precision),
				"rej_ppm": flt(day_rejection_qty / day_fg * PPM_MULTIPLIER, precision) if day_fg > 0 else 0,
				"rework_ppm": flt(day_declared_rework_qty / day_fg * PPM_MULTIPLIER, precision)
				if day_fg > 0
				else 0,
				"bold": 1,
			}
		)
	return rows


def _get_child_rows(
	doctype: str,
	parent_names: list[str],
	*,
	fields: list[str],
	parentfield: str,
	chunk_size: int = _CHILD_PARENT_CHUNK_SIZE,
) -> list[frappe._dict]:
	rows: list[frappe._dict] = []
	for offset in range(0, len(parent_names), max(int(chunk_size), 1)):
		parent_chunk = parent_names[offset : offset + max(int(chunk_size), 1)]
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


def _get_single_rejection_items(entry_names: list[str]) -> dict[str, str]:
	"""Fallback defective item for breakup rows with a blank Item Code.

	Validation only leaves the breakup item blank when the entry has exactly one
	rejection item, so that single row resolves the blank unambiguously.
	"""
	rows = _get_child_rows(
		"Stock Entry Detail",
		entry_names,
		fields=["parent", "item_code", "custom_pea_is_rejection_item", "idx"],
		parentfield="items",
	)
	items_by_parent: defaultdict[str, set[str]] = defaultdict(set)
	for row in rows:
		if row.get("custom_pea_is_rejection_item") and row.get("item_code"):
			items_by_parent[row.parent].add(row.item_code)
	return {parent: next(iter(items)) for parent, items in items_by_parent.items() if len(items) == 1}


def _get_daily_fg_totals(dates: list[datetime.date]) -> dict[datetime.date, float]:
	"""Day's raw total production: submitted production entries on Completed Shifts.

	Returned unrounded on purpose: the totals feed the PPM division, where
	rounding inputs first would distort the result.
	"""
	if not dates:
		return {}
	shift_names = get_report_rows(
		"Shift",
		filters={
			"status": "Completed",
			"shift_date": ["in", [day.isoformat() for day in dates]],
		},
		pluck="name",
	)
	if not shift_names:
		return {}
	totals: defaultdict[datetime.date, float] = defaultdict(float)
	for chunk in iter_stock_entries_in_chunks(
		{"docstatus": 1, "custom_pea_shift": ["in", sorted(shift_names)]},
		["name", "fg_completed_qty"],
	):
		for entry in chunk:
			day = entry.get("production_date")
			if day:
				totals[getdate(day)] += get_entry_output_quantities(entry).total_qty
	return dict(totals)


def _get_rework_by_day_item(
	line_rows: list[dict],
	*,
	max_rework_entries: int = _MAX_REWORK_ENTRIES,
) -> tuple[dict[tuple[datetime.date, str], dict], dict[datetime.date, dict]]:
	"""Same-day, same-item rework aggregates from submitted Rework Operations.

	Returns per-(rework date, item) aggregates shown on item rows plus per-day
	aggregates for the day header. The day aggregates cover **all** of the day's
	submitted rework — including items not rejected that day and surviving every
	report filter — because No. of Operators(working) / Time(hrs.) are day-level
	figures, not line-level. Only the item match is same-day, same-item.
	"""
	rework_types = get_report_rows("Stock Entry Type", filters={"custom_pea_rework_entry": 1}, pluck="name")
	days = {row["day"] for row in line_rows}
	if not rework_types:
		return {}, {}
	rework_entries = get_report_rows(
		"Stock Entry",
		filters={
			"docstatus": 1,
			"stock_entry_type": ["in", rework_types],
			"custom_pea_rework_date": [
				"between",
				[min(days).isoformat(), max(days).isoformat()],
			],
		},
		fields=["name", "custom_pea_rework_date"],
		limit_page_length=max_rework_entries + 1,
	)
	if len(rework_entries) > max_rework_entries:
		frappe.throw(
			_(
				"Daily Rej Rework Register matches more than {0} Rework Operations. Narrow the date range and retry."
			).format(max_rework_entries)
		)
	day_by_entry = {
		entry.name: getdate(entry.custom_pea_rework_date)
		for entry in rework_entries
		if entry.get("custom_pea_rework_date") and getdate(entry.custom_pea_rework_date) in days
	}
	if not day_by_entry:
		return {}, {}

	operator_rows = _get_child_rows(
		"Rework Operator",
		sorted(day_by_entry),
		fields=["parent", "operator", "actual_start", "actual_end", "idx"],
		parentfield="custom_pea_rework_operators",
	)
	hours_by_entry: defaultdict[str, float] = defaultdict(float)
	operators_by_entry: defaultdict[str, set[str]] = defaultdict(set)
	for row in operator_rows:
		if row.get("operator"):
			operators_by_entry[row.parent].add(row.operator)
		start = get_datetime(row.get("actual_start")) if row.get("actual_start") else None
		end = get_datetime(row.get("actual_end")) if row.get("actual_end") else None
		if start and end and end > start:
			hours_by_entry[row.parent] += (end - start).total_seconds() / SECONDS_PER_HOUR

	entries_by_day: defaultdict[datetime.date, set[str]] = defaultdict(set)
	for parent, day in day_by_entry.items():
		entries_by_day[day].add(parent)
	by_day: dict[datetime.date, dict] = {}
	for day, entries in entries_by_day.items():
		by_day[day] = {
			"hours": sum(hours_by_entry.get(parent, 0.0) for parent in entries),
			"operators": sorted(set().union(*(operators_by_entry.get(parent, set()) for parent in entries))),
		}

	items = sorted({row["defective_item_code"] for row in line_rows if row["defective_item_code"]})
	if not items:
		return {}, by_day
	item_set = set(items)
	item_rows = _get_child_rows(
		"Stock Entry Detail",
		sorted(day_by_entry),
		fields=["parent", "item_code", "qty", "idx"],
		parentfield="items",
	)
	qty_by_entry_item: dict[tuple[str, str], float] = defaultdict(float)
	matched_entries: set[str] = set()
	matched_pairs: set[tuple[datetime.date, str]] = set()
	for row in item_rows:
		day = day_by_entry.get(row.get("parent"))
		item_code = row.get("item_code")
		if not day or item_code not in item_set:
			continue
		qty_by_entry_item[(row.parent, item_code)] += flt(row.get("qty"))
		matched_entries.add(row.parent)
		matched_pairs.add((day, item_code))
	if not matched_entries:
		return {}, by_day

	responsibility_rows = _get_child_rows(
		"Rework Responsibility Employee",
		sorted(matched_entries),
		fields=["parent", "employee", "idx"],
		parentfield="custom_pea_rework_responsibility",
	)
	reinspection_rows = _get_child_rows(
		"Rework Reinspection Employee",
		sorted(matched_entries),
		fields=["parent", "employee", "idx"],
		parentfield="custom_pea_rework_reinspection",
	)
	responsibility_by_entry: defaultdict[str, set[str]] = defaultdict(set)
	for row in responsibility_rows:
		if row.get("employee"):
			responsibility_by_entry[row.parent].add(row.employee)
	reinspection_by_entry: defaultdict[str, set[str]] = defaultdict(set)
	for row in reinspection_rows:
		if row.get("employee"):
			reinspection_by_entry[row.parent].add(row.employee)

	result: dict[tuple[datetime.date, str], dict] = {}
	for day, item_code in sorted(matched_pairs):
		aggregate = {
			"qty": 0.0,
			"hours": 0.0,
			"operators": set(),
			"responsibility": set(),
			"reinspection": set(),
		}
		for (parent, reworked_item), qty in qty_by_entry_item.items():
			if reworked_item != item_code or day_by_entry.get(parent) != day:
				continue
			aggregate["qty"] += qty
			aggregate["hours"] += hours_by_entry.get(parent, 0.0)
			aggregate["operators"].update(operators_by_entry.get(parent, set()))
			aggregate["responsibility"].update(responsibility_by_entry.get(parent, set()))
			aggregate["reinspection"].update(reinspection_by_entry.get(parent, set()))
		aggregate["operators"] = sorted(aggregate["operators"])
		aggregate["responsibility"] = sorted(aggregate["responsibility"])
		aggregate["reinspection"] = sorted(aggregate["reinspection"])
		result[(day, item_code)] = aggregate

	return result, by_day
