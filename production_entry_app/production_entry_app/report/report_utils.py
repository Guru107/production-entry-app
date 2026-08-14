from __future__ import annotations

import datetime
import time
from collections import defaultdict
from collections.abc import Iterator

import frappe
from frappe import _
from frappe.query_builder import Case, DocType
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, get_datetime

from production_entry_app.production_entry_app.utils.loss_time import (
	SETUP_TIME_REASON,
	get_loss_duration_minutes,
)
from production_entry_app.production_entry_app.utils.system_precision import (
	get_system_float_precision,
)

_MAX_FG_ITEM_PARENT_MATCHES = 5000
_DEFAULT_REPORT_CHUNK_SIZE = 1000
_DEFAULT_MAX_STOCK_ENTRY_ROWS = 100000
_DEFAULT_INTERACTIVE_REPORT_TIMEOUT_SEC = 5.0
_SUPPORTED_STOCK_ENTRY_ORDER_BY = frozenset({"name asc", "posting_date asc, name asc"})
_STOCK_ENTRY_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
	"custom_pea_workstation": ("custom_pea_workstation", "custom_workstation"),
	"custom_pea_shift": ("custom_pea_shift", "custom_shift"),
	"custom_pea_operator": ("custom_pea_operator", "custom_operator"),
}


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


def get_stock_entry_alias_fields(base_fields: list[str], alias_keys: tuple[str, ...]) -> list[str]:
	meta = frappe.get_meta("Stock Entry")
	fields = list(base_fields)
	for key in alias_keys:
		for fieldname in _STOCK_ENTRY_FIELD_ALIASES.get(key, (key,)):
			if fieldname == key or meta.has_field(fieldname):
				fields.append(fieldname)
	return list(dict.fromkeys(fields))


def row_matches_stock_entry_alias_filters(row: dict, filters: dict, alias_keys: tuple[str, ...]) -> bool:
	for key in alias_keys:
		filter_value = get_stock_entry_alias_filter_value(filters, key)
		if filter_value and get_stock_entry_alias_value(row, key) != filter_value:
			return False
	return True


def get_stock_entry_alias_filter_value(filters: dict, key: str) -> str | None:
	for fieldname in _STOCK_ENTRY_FIELD_ALIASES.get(key, (key,)):
		value = filters.get(fieldname)
		if value:
			return value
	return None


def get_stock_entry_alias_value(row: dict, key: str, default: str | None = None) -> str | None:
	for fieldname in _STOCK_ENTRY_FIELD_ALIASES.get(key, (key,)):
		value = row.get(fieldname)
		if value:
			return value
	return default


def new_interactive_report_timeout_guard(
	report_label: str,
	timeout_sec: float = _DEFAULT_INTERACTIVE_REPORT_TIMEOUT_SEC,
):
	if not _should_enforce_interactive_report_timeout():
		return lambda: None

	effective_timeout_sec = max(float(timeout_sec or 0), 0)
	start = time.perf_counter()

	def guard() -> None:
		if effective_timeout_sec <= 0:
			return
		elapsed_sec = time.perf_counter() - start
		if elapsed_sec <= effective_timeout_sec:
			return
		frappe.throw(
			_(
				"{0} exceeded the interactive execution budget of {1} seconds. Narrow filters by date, shift, workstation, operator, or BOM and retry."
			).format(report_label, f"{effective_timeout_sec:.1f}")
		)

	return guard


def _should_enforce_interactive_report_timeout() -> bool:
	if not getattr(frappe.local, "request", None):
		return False
	return bool(cint(frappe.form_dict.get("ignore_prepared_report")))


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
				stock_entry_detail.custom_pea_is_rejection_item.isnull()
				| (stock_entry_detail.custom_pea_is_rejection_item == 0)
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


def iter_stock_entries_in_chunks(
	filters: dict,
	fields: list[str],
	order_by: str = "name asc",
	chunk_size: int = _DEFAULT_REPORT_CHUNK_SIZE,
	max_rows: int = _DEFAULT_MAX_STOCK_ENTRY_ROWS,
) -> Iterator[list[dict]]:
	"""Yield Stock Entry rows in deterministic chunks to avoid blanket reads."""
	normalized_order_by = _normalize_stock_entry_order_by(order_by)
	_validate_stock_entry_chunk_fields(fields, normalized_order_by)
	effective_chunk_size = max(int(chunk_size or _DEFAULT_REPORT_CHUNK_SIZE), 1)
	processed_rows = 0
	last_row: dict | None = None
	while True:
		rows = _fetch_stock_entry_chunk(
			filters=filters,
			fields=fields,
			order_by=normalized_order_by,
			chunk_size=effective_chunk_size,
			last_row=last_row,
		)
		if not rows:
			break
		processed_rows += len(rows)
		if max_rows > 0 and processed_rows > max_rows:
			frappe.throw(
				_(
					"Report scope exceeds {0} Stock Entries. Narrow filters by date, shift, workstation, operator, or BOM."
				).format(max_rows)
			)
		yield rows
		if len(rows) < effective_chunk_size:
			break
		last_row = rows[-1]


def _normalize_stock_entry_order_by(order_by: str) -> str:
	normalized_order_by = ", ".join(
		part.strip().lower() for part in str(order_by or "name asc").split(",") if part.strip()
	)
	if normalized_order_by not in _SUPPORTED_STOCK_ENTRY_ORDER_BY:
		frappe.throw(_("Unsupported Stock Entry report ordering: {0}").format(order_by or "name asc"))
	return normalized_order_by


def _validate_stock_entry_chunk_fields(fields: list[str], order_by: str) -> None:
	required_fields = ("name",) if order_by == "name asc" else ("posting_date", "name")
	missing_fields = [field for field in required_fields if field not in fields]
	if missing_fields:
		frappe.throw(
			_("Stock Entry chunking requires order fields in selected columns: {0}").format(
				", ".join(missing_fields)
			)
		)


def _fetch_stock_entry_chunk(
	filters: dict,
	fields: list[str],
	order_by: str,
	chunk_size: int,
	last_row: dict | None = None,
) -> list[dict]:
	permission_filters = _as_permission_aware_filters(filters)

	if order_by == "name asc":
		if last_row:
			last_name = last_row.get("name")
			if not last_name:
				frappe.throw(_("Missing Stock Entry name for keyset pagination."))
			permission_filters.append(["name", ">", last_name])
		return frappe.get_list(
			"Stock Entry",
			filters=permission_filters,
			fields=fields,
			order_by=order_by,
			limit_page_length=chunk_size,
		)

	if last_row:
		last_posting_date = last_row.get("posting_date")
		last_name = last_row.get("name")
		if last_posting_date is None or not last_name:
			frappe.throw(_("Missing Stock Entry posting date or name for keyset pagination."))
		same_day_rows = frappe.get_list(
			"Stock Entry",
			filters=[
				*permission_filters,
				["posting_date", "=", last_posting_date],
				["name", ">", last_name],
			],
			fields=fields,
			order_by=order_by,
			limit_page_length=chunk_size,
		)
		remaining = chunk_size - len(same_day_rows)
		if remaining <= 0:
			return same_day_rows
		later_rows = frappe.get_list(
			"Stock Entry",
			filters=[*permission_filters, ["posting_date", ">", last_posting_date]],
			fields=fields,
			order_by=order_by,
			limit_page_length=remaining,
		)
		return [*same_day_rows, *later_rows]

	return frappe.get_list(
		"Stock Entry",
		filters=permission_filters,
		fields=fields,
		order_by=order_by,
		limit_page_length=chunk_size,
	)


def _as_permission_aware_filters(filters: dict) -> list[list]:
	result = []
	for fieldname, value in filters.items():
		if isinstance(value, list | tuple) and len(value) == 2:
			result.append([fieldname, value[0], value[1]])
		else:
			result.append([fieldname, "=", value])
	return result


def get_entry_qty_maps(
	stock_entry_names: list[str],
	include_fg_item: bool = False,
) -> tuple[dict[str, float], dict[str, float], dict[str, str]]:
	if not stock_entry_names:
		return {}, {}, {}

	parent_metrics = get_parent_quantity_metrics(stock_entry_names)

	good_qty_map: dict[str, float] = {}
	fg_item_map: dict[str, str] = {}
	for parent, metrics in parent_metrics.items():
		good_qty_map[parent] = flt(metrics.get("good_qty") or 0)

	if include_fg_item:
		stock_entry_detail = DocType("Stock Entry Detail")
		good_rows = (
			frappe.qb.from_(stock_entry_detail)
			.select(
				stock_entry_detail.parent,
				stock_entry_detail.item_code,
				Sum(stock_entry_detail.qty).as_("qty"),
			)
			.where(stock_entry_detail.parent.isin(stock_entry_names))
			.where(stock_entry_detail.is_finished_item == 1)
			.where(
				stock_entry_detail.custom_pea_is_rejection_item.isnull()
				| (stock_entry_detail.custom_pea_is_rejection_item == 0)
			)
			.groupby(stock_entry_detail.parent, stock_entry_detail.item_code)
		).run(as_dict=True)
		for row in good_rows:
			parent = row.get("parent")
			if not parent:
				continue
			if row.get("item_code"):
				fg_item_map[parent] = row.get("item_code")

	rejection_qty_map: dict[str, float] = {}
	for parent, metrics in parent_metrics.items():
		rejection_qty_map[parent] = flt(metrics.get("rejection_qty") or 0)

	return good_qty_map, rejection_qty_map, fg_item_map


def get_parent_quantity_metrics(
	stock_entry_names: list[str],
	*,
	include_rework: bool = False,
) -> dict[str, dict[str, float]]:
	if not stock_entry_names:
		return {}

	stock_entry_detail = DocType("Stock Entry Detail")
	good_qty_case = (
		Case()
		.when(
			(stock_entry_detail.is_finished_item == 1)
			& (
				stock_entry_detail.custom_pea_is_rejection_item.isnull()
				| (stock_entry_detail.custom_pea_is_rejection_item == 0)
			),
			stock_entry_detail.qty,
		)
		.else_(0)
	)
	qty_rows = (
		frappe.qb.from_(stock_entry_detail)
		.select(
			stock_entry_detail.parent,
			Sum(good_qty_case).as_("good_qty"),
		)
		.where(stock_entry_detail.parent.isin(stock_entry_names))
		.groupby(stock_entry_detail.parent)
	).run(as_dict=True)

	parent_metrics: dict[str, dict[str, float]] = {
		name: {
			"good_qty": 0.0,
			"rejection_qty": 0.0,
			"rework_qty": 0.0,
			"total_rejected_qty": 0.0,
		}
		for name in stock_entry_names
	}
	for row in qty_rows:
		parent = row.get("parent")
		if not parent:
			continue
		parent_metrics.setdefault(
			parent,
			{"good_qty": 0.0, "rejection_qty": 0.0, "rework_qty": 0.0, "total_rejected_qty": 0.0},
		)
		parent_metrics[parent]["good_qty"] = flt(row.get("good_qty") or 0)

	rejection_breakup = DocType("Rejection Breakup")
	rejection_rows = (
		frappe.qb.from_(rejection_breakup)
		.select(
			rejection_breakup.parent,
			rejection_breakup.is_rework,
			Sum(rejection_breakup.qty).as_("qty"),
		)
		.where(rejection_breakup.parenttype == "Stock Entry")
		.where(rejection_breakup.parent.isin(stock_entry_names))
		.groupby(rejection_breakup.parent, rejection_breakup.is_rework)
	).run(as_dict=True)
	for row in rejection_rows:
		parent = row.get("parent")
		if not parent:
			continue
		parent_metrics.setdefault(
			parent,
			{"good_qty": 0.0, "rejection_qty": 0.0, "rework_qty": 0.0, "total_rejected_qty": 0.0},
		)
		qty = flt(row.get("qty") or 0)
		parent_metrics[parent]["total_rejected_qty"] = (
			flt(parent_metrics[parent].get("total_rejected_qty") or 0) + qty
		)
		if row.get("is_rework"):
			parent_metrics[parent]["rework_qty"] = qty
		else:
			parent_metrics[parent]["rejection_qty"] = qty

	if not include_rework:
		for metrics in parent_metrics.values():
			metrics["rework_qty"] = 0.0

	return parent_metrics


def get_parent_breakup_reason_rows(
	stock_entry_names: list[str],
	*,
	is_rework: bool | None = None,
) -> list[dict]:
	if not stock_entry_names:
		return []

	rejection_breakup = DocType("Rejection Breakup")
	query = (
		frappe.qb.from_(rejection_breakup)
		.select(
			rejection_breakup.parent,
			rejection_breakup.rejection_reason,
			Sum(rejection_breakup.qty).as_("qty"),
		)
		.where(rejection_breakup.parenttype == "Stock Entry")
		.where(rejection_breakup.parent.isin(stock_entry_names))
		.groupby(rejection_breakup.parent, rejection_breakup.rejection_reason)
	)
	if is_rework is True:
		query = query.where(rejection_breakup.is_rework == 1)
	elif is_rework is False:
		query = query.where(rejection_breakup.is_rework.isnull() | (rejection_breakup.is_rework == 0))
	return query.run(as_dict=True)


def get_finished_item_map(stock_entry_names: list[str]) -> dict[str, str]:
	if not stock_entry_names:
		return {}

	stock_entry_detail = DocType("Stock Entry Detail")
	rows = (
		frappe.qb.from_(stock_entry_detail)
		.select(stock_entry_detail.parent, stock_entry_detail.item_code)
		.where(stock_entry_detail.parent.isin(stock_entry_names))
		.where(stock_entry_detail.is_finished_item == 1)
		.where(
			stock_entry_detail.custom_pea_is_rejection_item.isnull()
			| (stock_entry_detail.custom_pea_is_rejection_item == 0)
		)
	).run(as_dict=True)
	return {
		row.get("parent"): row.get("item_code") for row in rows if row.get("parent") and row.get("item_code")
	}


def get_parent_loss_metrics(stock_entry_names: list[str]) -> dict[str, dict[str, float]]:
	"""Return setup and non-setup loss minutes keyed by Stock Entry name."""
	if not stock_entry_names:
		return {}

	parent_metrics: dict[str, dict[str, float]] = {
		name: {"setup_mins": 0.0, "loss_mins": 0.0} for name in stock_entry_names
	}
	loss_rows = frappe.get_all(
		"Loss Entry",
		filters={"parenttype": "Stock Entry", "parent": ["in", stock_entry_names]},
		fields=["parent", "downtime_reason", "start_time", "end_time"],
	)
	for row in loss_rows:
		parent = row.get("parent")
		if not parent:
			continue
		duration_mins = get_loss_duration_minutes(row.get("start_time"), row.get("end_time"))
		if duration_mins <= 0:
			continue
		parent_metrics.setdefault(parent, {"setup_mins": 0.0, "loss_mins": 0.0})
		if row.get("downtime_reason") == SETUP_TIME_REASON:
			parent_metrics[parent]["setup_mins"] = parent_metrics[parent]["setup_mins"] + duration_mins
		else:
			parent_metrics[parent]["loss_mins"] = parent_metrics[parent]["loss_mins"] + duration_mins
	return parent_metrics


def get_rework_qty_map(stock_entry_names: list[str]) -> dict[str, float]:
	"""Return {entry_name: rework_qty} from Rejection Breakup rows where is_rework=1."""
	return {
		parent: flt(metrics.get("rework_qty") or 0)
		for parent, metrics in get_parent_quantity_metrics(stock_entry_names, include_rework=True).items()
	}


def get_loss_time_maps(entry_names: list[str]) -> tuple[dict[str, float], dict[str, float]]:
	"""Return setup and non-setup loss minutes keyed by Stock Entry name."""
	parent_loss_metrics = get_parent_loss_metrics(entry_names)
	return (
		{parent: flt(metrics.get("setup_mins") or 0) for parent, metrics in parent_loss_metrics.items()},
		{parent: flt(metrics.get("loss_mins") or 0) for parent, metrics in parent_loss_metrics.items()},
	)


def get_duration_minutes(start_value, end_value) -> float:
	if not start_value or not end_value:
		return 0
	start_dt = get_datetime(start_value)
	end_dt = get_datetime(end_value)
	if not isinstance(start_dt, datetime.datetime) or not isinstance(end_dt, datetime.datetime):
		return 0
	duration = (end_dt - start_dt).total_seconds() / 60
	return flt(duration if duration > 0 else 0)


def get_entry_total_strokes(
	entry: dict,
	good_qty_map: dict[str, float] | None = None,
	rejection_qty_map: dict[str, float] | None = None,
	total_rejected_qty_map: dict[str, float] | None = None,
) -> tuple[float, float]:
	"""Return (total_strokes, rejection_qty) for one stock entry row."""
	entry_name = entry.get("name")
	rejection_qty = 0.0
	if entry_name and rejection_qty_map is not None:
		rejection_qty = flt(rejection_qty_map.get(entry_name) or 0)
	total_rejected_qty = flt(entry.get("custom_pea_rejection_qty") or 0)
	if entry_name and total_rejected_qty_map is not None:
		total_rejected_qty = flt(total_rejected_qty_map.get(entry_name) or 0)

	fg_completed_qty = flt(entry.get("fg_completed_qty") or 0)
	if fg_completed_qty > 0:
		return fg_completed_qty, rejection_qty
	if entry_name and good_qty_map is not None:
		return flt(good_qty_map.get(entry_name) or 0) + total_rejected_qty, rejection_qty
	return rejection_qty, rejection_qty


def get_entry_production_minutes(
	entry: dict,
	setup_mins: float = 0.0,
	loss_mins: float = 0.0,
) -> float:
	"""Return production minutes using custom_pea_production_time_mins when present."""
	production_time_value = entry.get("custom_pea_production_time_mins")
	if production_time_value is not None:
		return flt(max(production_time_value, 0))

	duration_mins = get_entry_raw_duration_minutes(entry)
	return max(duration_mins - flt(setup_mins) - flt(loss_mins), 0)


def get_entry_raw_duration_minutes(entry: dict) -> float:
	"""Return wall-clock duration minutes from stored field or start/end fallback."""
	duration_mins = flt(entry.get("custom_pea_actual_duration_mins") or 0)
	if duration_mins > 0:
		return duration_mins
	return get_duration_minutes(
		entry.get("custom_pea_actual_start_date"),
		entry.get("custom_pea_actual_end_date"),
	)


def format_numeric_summary(value: float) -> str:
	"""Format a number for human-readable inline display in report text (e.g. dominant reason qty)."""
	return frappe.format_value(
		value,
		df={"fieldtype": "Float", "precision": get_report_float_precision()},
	)


def apply_system_precision(columns: list[dict]) -> list[dict]:
	precision = get_report_float_precision()
	for column in columns:
		if column.get("fieldtype") in {"Float", "Percent"}:
			column["precision"] = precision
	return columns


def get_report_float_precision() -> int:
	cached_precision = getattr(frappe.local, "_pea_report_float_precision", None)
	if cached_precision is None:
		cached_precision = get_system_float_precision()
		frappe.local._pea_report_float_precision = cached_precision
	return cached_precision


def new_efficiency_aggregates() -> defaultdict:
	return defaultdict(
		lambda: {
			"entries": 0,
			"good_qty": 0.0,
			"rejection_qty": 0.0,
			"rework_qty": 0.0,
			"total_units": 0.0,
			"duration_mins": 0.0,
			"standard_spm": 0.0,
			"actual_spm_sum": 0.0,
		}
	)


def accumulate_efficiency_aggregate(
	aggregates: defaultdict,
	entry: dict,
	group_field: str,
	group_label_default: str = "Unassigned",
) -> None:
	group_value = entry.get(group_field) or group_label_default
	good_qty = flt(entry.get("_good_qty") or 0)
	rejection_qty = flt(entry.get("_rejection_qty") or 0)
	rework_qty = flt(entry.get("_rework_qty") or 0)
	total_units = good_qty + rejection_qty
	production_time_mins = entry.get("_production_time_mins")
	duration_mins = flt(
		production_time_mins if production_time_mins is not None else (entry.get("_duration_mins") or 0),
	)
	standard_spm = flt(entry.get("custom_pea_standard_spm") or 0)

	agg = aggregates[group_value]
	agg["entries"] += 1
	agg["good_qty"] += good_qty
	agg["rejection_qty"] += rejection_qty
	agg["rework_qty"] += rework_qty
	agg["total_units"] += total_units
	agg["duration_mins"] += duration_mins
	agg["actual_spm_sum"] += flt(entry.get("custom_pea_actual_spm") or 0)
	if standard_spm > 0 and agg["standard_spm"] <= 0:
		agg["standard_spm"] = standard_spm


def aggregate_efficiency_by_field(
	entries: list[dict],
	group_field: str,
	group_label_default: str = "Unassigned",
) -> dict[str, dict]:
	aggregates = new_efficiency_aggregates()
	for entry in entries:
		accumulate_efficiency_aggregate(aggregates, entry, group_field, group_label_default)
	return aggregates


def build_efficiency_rows(
	aggregates: dict[str, dict],
	group_result_field: str,
	efficiency_result_field: str,
) -> list[dict]:
	rows = []
	for group_value, agg in sorted(aggregates.items()):
		entry_count = int(agg["entries"])
		duration_mins = flt(agg["duration_mins"])
		actual_spm = (agg["total_units"] / duration_mins) if duration_mins > 0 else 0
		standard_spm = flt(agg["standard_spm"])
		if duration_mins <= 0 and entry_count:
			actual_spm = agg["actual_spm_sum"] / entry_count
		efficiency_pct = ((actual_spm / standard_spm) * 100) if standard_spm > 0 else 0
		rows.append(
			{
				group_result_field: group_value,
				"entries": entry_count,
				"good_qty": flt(agg["good_qty"]),
				"rejection_qty": flt(agg["rejection_qty"]),
				"rework_qty": flt(agg["rework_qty"]),
				"total_units": flt(agg["total_units"]),
				"actual_spm": actual_spm,
				"standard_spm": standard_spm,
				efficiency_result_field: efficiency_pct,
			}
		)
	return rows
