from __future__ import annotations

import datetime
from collections import defaultdict

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import flt, get_datetime


def build_stock_entry_filters(filters: dict, filter_keys: tuple[str, ...]) -> dict:
	db_filters: dict = {"docstatus": 1, "purpose": "Manufacture"}

	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	if from_date and to_date:
		db_filters["posting_date"] = ["between", [from_date, to_date]]
	elif from_date:
		db_filters["posting_date"] = [">=", from_date]
	elif to_date:
		db_filters["posting_date"] = ["<=", to_date]

	for key in filter_keys:
		if filters.get(key):
			db_filters[key] = filters.get(key)

	fg_item = filters.get("fg_item")
	if fg_item:
		parent_names = get_stock_entries_for_fg_item(fg_item)
		db_filters["name"] = ["in", parent_names or [""]]

	return db_filters


def get_stock_entries_for_fg_item(item_code: str) -> list[str]:
	stock_entry_detail = DocType("Stock Entry Detail")
	rows = (
		frappe.qb.from_(stock_entry_detail)
		.select(stock_entry_detail.parent)
		.distinct()
		.where((stock_entry_detail.item_code == item_code) & (stock_entry_detail.is_finished_item == 1))
	).run(as_dict=True)
	return [row.get("parent") for row in rows if row.get("parent")]


def get_entry_qty_maps(
	stock_entry_names: list[str],
	include_fg_item: bool = False,
) -> tuple[dict[str, float], dict[str, float], dict[str, str]]:
	if not stock_entry_names:
		return {}, {}, {}

	stock_entry_detail = DocType("Stock Entry Detail")
	good_query = frappe.qb.from_(stock_entry_detail).where(
		(stock_entry_detail.parent.isin(stock_entry_names)) & (stock_entry_detail.is_finished_item == 1)
	)
	if include_fg_item:
		good_rows = (
			good_query.select(
				stock_entry_detail.parent,
				stock_entry_detail.item_code,
				Sum(stock_entry_detail.qty).as_("qty"),
			).groupby(stock_entry_detail.parent, stock_entry_detail.item_code)
		).run(as_dict=True)
	else:
		good_rows = (
			good_query.select(stock_entry_detail.parent, Sum(stock_entry_detail.qty).as_("qty")).groupby(
				stock_entry_detail.parent
			)
		).run(as_dict=True)
	rejection_rows = (
		frappe.qb.from_(stock_entry_detail)
		.select(stock_entry_detail.parent, Sum(stock_entry_detail.qty).as_("qty"))
		.where(
			(stock_entry_detail.parent.isin(stock_entry_names))
			& (stock_entry_detail.custom_is_rejection_item == 1)
		)
		.groupby(stock_entry_detail.parent)
	).run(as_dict=True)

	good_qty_map: dict[str, float] = {}
	fg_item_map: dict[str, str] = {}
	for row in good_rows:
		parent = row.get("parent")
		if not parent:
			continue
		good_qty_map[parent] = flt(row.get("qty") or 0, 3)
		if include_fg_item and row.get("item_code"):
			fg_item_map[parent] = row.get("item_code")

	rejection_qty_map: dict[str, float] = {}
	for row in rejection_rows:
		parent = row.get("parent")
		if not parent:
			continue
		rejection_qty_map[parent] = flt(row.get("qty") or 0, 3)

	return good_qty_map, rejection_qty_map, fg_item_map


def get_duration_minutes(start_value, end_value) -> float:
	if not start_value or not end_value:
		return 0
	start_dt = get_datetime(start_value)
	end_dt = get_datetime(end_value)
	if not isinstance(start_dt, datetime.datetime) or not isinstance(end_dt, datetime.datetime):
		return 0
	duration = (end_dt - start_dt).total_seconds() / 60
	return flt(duration if duration > 0 else 0, 3)


def aggregate_efficiency_by_field(
	entries: list[dict],
	group_field: str,
	group_label_default: str = "Unassigned",
) -> dict[str, dict]:
	aggregates = defaultdict(
		lambda: {
			"entries": 0,
			"good_qty": 0.0,
			"rejection_qty": 0.0,
			"total_units": 0.0,
			"duration_mins": 0.0,
			"standard_units": 0.0,
			"actual_spm_sum": 0.0,
			"standard_spm_sum": 0.0,
		}
	)

	for entry in entries:
		group_value = entry.get(group_field) or group_label_default
		good_qty = flt(entry.get("_good_qty") or 0, 3)
		rejection_qty = flt(entry.get("_rejection_qty") or 0, 3)
		total_units = flt(good_qty + rejection_qty, 3)
		duration_mins = flt(entry.get("_duration_mins") or 0, 3)
		standard_spm = flt(entry.get("custom_standard_spm") or 0, 3)

		agg = aggregates[group_value]
		agg["entries"] += 1
		agg["good_qty"] += good_qty
		agg["rejection_qty"] += rejection_qty
		agg["total_units"] += total_units
		agg["duration_mins"] += duration_mins
		agg["standard_units"] += standard_spm * duration_mins
		agg["actual_spm_sum"] += flt(entry.get("custom_actual_spm") or 0, 3)
		agg["standard_spm_sum"] += standard_spm

	return aggregates


def build_efficiency_rows(
	aggregates: dict[str, dict],
	group_result_field: str,
	efficiency_result_field: str,
) -> list[dict]:
	rows = []
	for group_value, agg in sorted(aggregates.items()):
		entry_count = int(agg["entries"])
		duration_mins = flt(agg["duration_mins"], 3)
		actual_spm = flt((agg["total_units"] / duration_mins), 3) if duration_mins > 0 else 0
		standard_spm = flt((agg["standard_units"] / duration_mins), 3) if duration_mins > 0 else 0
		if duration_mins <= 0 and entry_count:
			actual_spm = flt((agg["actual_spm_sum"] / entry_count), 3)
			standard_spm = flt((agg["standard_spm_sum"] / entry_count), 3)
		efficiency_pct = flt((actual_spm / standard_spm) * 100, 2) if standard_spm > 0 else 0
		rows.append(
			{
				group_result_field: group_value,
				"entries": entry_count,
				"good_qty": flt(agg["good_qty"], 3),
				"rejection_qty": flt(agg["rejection_qty"], 3),
				"total_units": flt(agg["total_units"], 3),
				"actual_spm": actual_spm,
				"standard_spm": standard_spm,
				efficiency_result_field: efficiency_pct,
			}
		)
	return rows
