from __future__ import annotations

import datetime
from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import flt, get_datetime

from production_entry_app.production_entry_app.utils.loss_time import (
	SETUP_TIME_REASON,
	get_loss_duration_minutes,
)

_MAX_FG_ITEM_PARENT_MATCHES = 5000


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
	stock_entry = DocType("Stock Entry")
	rows = (
		frappe.qb.from_(stock_entry_detail)
		.inner_join(stock_entry)
		.on(stock_entry.name == stock_entry_detail.parent)
		.select(stock_entry_detail.parent)
		.distinct()
		.where(
			# Keep parent-level constraints here because this helper is reused independently
			# from report filter builders.
			(stock_entry_detail.item_code == item_code)
			& (stock_entry_detail.is_finished_item == 1)
			& (
				stock_entry_detail.custom_is_rejection_item.isnull()
				| (stock_entry_detail.custom_is_rejection_item == 0)
			)
			& (stock_entry.docstatus == 1)
			& (stock_entry.purpose == "Manufacture")
		)
		.limit(_MAX_FG_ITEM_PARENT_MATCHES + 1)
	).run(as_dict=True)
	if len(rows) > _MAX_FG_ITEM_PARENT_MATCHES:
		frappe.throw(
			_(
				"FG Item filter matches more than {0} Stock Entries. Narrow filters by date, shift, workstation, or operator."
			).format(_MAX_FG_ITEM_PARENT_MATCHES)
		)
	return [row.get("parent") for row in rows if row.get("parent")]


def get_entry_qty_maps(
	stock_entry_names: list[str],
	include_fg_item: bool = False,
) -> tuple[dict[str, float], dict[str, float], dict[str, str]]:
	if not stock_entry_names:
		return {}, {}, {}

	stock_entry_detail = DocType("Stock Entry Detail")
	good_query = frappe.qb.from_(stock_entry_detail).where(
		(stock_entry_detail.parent.isin(stock_entry_names))
		& (stock_entry_detail.is_finished_item == 1)
		& (
			stock_entry_detail.custom_is_rejection_item.isnull()
			| (stock_entry_detail.custom_is_rejection_item == 0)
		)
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
		good_qty_map[parent] = flt(good_qty_map.get(parent) or 0, 3) + flt(row.get("qty") or 0, 3)
		if include_fg_item and row.get("item_code"):
			fg_item_map[parent] = row.get("item_code")

	rejection_qty_map: dict[str, float] = {}
	for row in rejection_rows:
		parent = row.get("parent")
		if not parent:
			continue
		rejection_qty_map[parent] = flt(row.get("qty") or 0, 3)

	return good_qty_map, rejection_qty_map, fg_item_map


def get_rework_qty_map(stock_entry_names: list[str]) -> dict[str, float]:
	"""Return {entry_name: rework_qty} from Rejection Breakup rows where is_rework=1."""
	if not stock_entry_names:
		return {}

	rejection_breakup = DocType("Rejection Breakup")
	rows = (
		frappe.qb.from_(rejection_breakup)
		.select(rejection_breakup.parent, Sum(rejection_breakup.qty).as_("qty"))
		.where(rejection_breakup.parenttype == "Stock Entry")
		.where(rejection_breakup.parent.isin(stock_entry_names))
		.where(rejection_breakup.is_rework == 1)
		.groupby(rejection_breakup.parent)
	).run(as_dict=True)

	rework_qty_map: dict[str, float] = {}
	for row in rows:
		parent = row.get("parent")
		if not parent:
			continue
		rework_qty_map[parent] = flt(row.get("qty") or 0, 3)
	return rework_qty_map


def get_loss_time_maps(entry_names: list[str]) -> tuple[dict[str, float], dict[str, float]]:
	"""Return setup and non-setup loss minutes keyed by Stock Entry name."""
	if not entry_names:
		return {}, {}

	loss_rows = frappe.get_all(
		"Loss Entry",
		filters={"parenttype": "Stock Entry", "parent": ["in", entry_names]},
		fields=["parent", "downtime_reason", "start_time", "end_time"],
	)
	setup_time_map: dict[str, float] = {}
	loss_time_map: dict[str, float] = {}
	for row in loss_rows:
		parent = row.get("parent")
		if not parent:
			continue
		duration_mins = get_loss_duration_minutes(row.get("start_time"), row.get("end_time"))
		if duration_mins <= 0:
			continue
		if row.get("downtime_reason") == SETUP_TIME_REASON:
			setup_time_map[parent] = flt(setup_time_map.get(parent, 0) + duration_mins, 3)
		else:
			loss_time_map[parent] = flt(loss_time_map.get(parent, 0) + duration_mins, 3)
	return setup_time_map, loss_time_map


def get_duration_minutes(start_value, end_value) -> float:
	if not start_value or not end_value:
		return 0
	start_dt = get_datetime(start_value)
	end_dt = get_datetime(end_value)
	if not isinstance(start_dt, datetime.datetime) or not isinstance(end_dt, datetime.datetime):
		return 0
	duration = (end_dt - start_dt).total_seconds() / 60
	return flt(duration if duration > 0 else 0, 3)


def get_entry_total_strokes(
	entry: dict,
	good_qty_map: dict[str, float] | None = None,
	rejection_qty_map: dict[str, float] | None = None,
) -> tuple[float, float]:
	"""Return (total_strokes, rejection_qty) for one stock entry row."""
	entry_name = entry.get("name")
	rejection_qty = flt(entry.get("custom_rejection_qty") or 0, 3)
	if rejection_qty <= 0 and entry_name and rejection_qty_map is not None:
		rejection_qty = flt(rejection_qty_map.get(entry_name) or 0, 3)

	fg_completed_qty = flt(entry.get("fg_completed_qty") or 0, 3)
	if fg_completed_qty > 0:
		return fg_completed_qty, rejection_qty
	if entry_name and good_qty_map is not None:
		return flt(good_qty_map.get(entry_name) or 0, 3) + rejection_qty, rejection_qty
	return rejection_qty, rejection_qty


def get_entry_production_minutes(
	entry: dict,
	setup_mins: float = 0.0,
	loss_mins: float = 0.0,
) -> float:
	"""Return production minutes using custom_production_time_mins when present."""
	production_time_value = entry.get("custom_production_time_mins")
	if production_time_value is not None:
		return flt(max(production_time_value, 0), 3)

	duration_mins = get_entry_raw_duration_minutes(entry)
	return flt(max(duration_mins - flt(setup_mins, 3) - flt(loss_mins, 3), 0), 3)


def get_entry_raw_duration_minutes(entry: dict) -> float:
	"""Return wall-clock duration minutes from stored field or start/end fallback."""
	duration_mins = flt(entry.get("custom_actual_duration_mins") or 0, 3)
	if duration_mins > 0:
		return duration_mins
	return get_duration_minutes(
		entry.get("custom_actual_start_date"),
		entry.get("custom_actual_end_date"),
	)


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
			"rework_qty": 0.0,
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
		rework_qty = flt(entry.get("_rework_qty") or 0, 3)
		total_units = flt(good_qty + rejection_qty, 3)
		production_time_mins = entry.get("_production_time_mins")
		duration_mins = flt(
			production_time_mins if production_time_mins is not None else (entry.get("_duration_mins") or 0),
			3,
		)
		standard_spm = flt(entry.get("custom_standard_spm") or 0, 3)

		agg = aggregates[group_value]
		agg["entries"] += 1
		agg["good_qty"] += good_qty
		agg["rejection_qty"] += rejection_qty
		agg["rework_qty"] += rework_qty
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
				"rework_qty": flt(agg["rework_qty"], 3),
				"total_units": flt(agg["total_units"], 3),
				"actual_spm": actual_spm,
				"standard_spm": standard_spm,
				efficiency_result_field: efficiency_pct,
			}
		)
	return rows
