from __future__ import annotations

import datetime
import time
from collections import defaultdict
from collections.abc import Iterator
from typing import Any, NamedTuple

import frappe
from frappe import _
from frappe.query_builder import Case, DocType
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, get_datetime
from pypika import Table
from pypika.terms import Criterion

from production_entry_app.production_entry_app.utils.loss_time import (
	SETUP_TIME_REASON,
	get_loss_duration_minutes,
)
from production_entry_app.production_entry_app.utils.stock_entry_type_flags import (
	is_joint_lh_rh_stock_entry_type,
)
from production_entry_app.production_entry_app.utils.system_precision import (
	get_system_float_precision,
)

_MAX_FG_ITEM_PARENT_MATCHES: int = 5000
_MAX_BOM_PARENT_MATCHES: int = 5000
_DEFAULT_REPORT_CHUNK_SIZE: int = 1000
_DEFAULT_MAX_STOCK_ENTRY_ROWS: int = 100000
_DEFAULT_INTERACTIVE_REPORT_TIMEOUT_SEC: float = 5.0
_NO_MATCHING_SHIFT: str = "__no_matching_completed_shift__"
_SUPPORTED_STOCK_ENTRY_ORDER_BY: frozenset[str] = frozenset({"name asc", "posting_date asc, name asc"})
_PRODUCTION_STOCK_ENTRY_OR_FILTERS: tuple[tuple[str, str, Any], ...] = (
	("purpose", "=", "Manufacture"),
	("purpose", "=", "Repack"),
)
_STOCK_ENTRY_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
	"custom_pea_workstation": ("custom_pea_workstation", "custom_workstation"),
	"custom_pea_shift": ("custom_pea_shift", "custom_shift"),
	"custom_pea_operator": ("custom_pea_operator", "custom_operator"),
}


class EntryOutputQuantities(NamedTuple):
	total_qty: float
	ok_qty: float
	rejection_qty: float


def get_report_rows(doctype: str, **kwargs: Any) -> list[dict]:
	"""Read internal report data after Frappe's native Shift report permission check.

	PEA reports use Shift as their reference DocType. Frappe intentionally allows
	Report permission without granting direct read access to every source DocType,
	so report internals must not apply a second, conflicting DocType read check.
	"""
	if not frappe.has_permission("Shift", "report"):
		frappe.throw(
			_("You do not have permission to access Production Entry reports."),
			frappe.PermissionError,
		)
	return frappe.get_all(doctype, **kwargs)


def build_stock_entry_filters(filters: dict, filter_keys: tuple[str, ...]) -> dict:
	db_filters: dict = {"docstatus": 1, "purpose": ["in", ["Manufacture", "Repack"]]}

	for key in filter_keys:
		if key != "bom_no" and filters.get(key):
			db_filters[key] = filters.get(key)

	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	if from_date or to_date:
		shift_filters: dict = {"status": "Completed"}
		if from_date and to_date:
			shift_filters["shift_date"] = ["between", [from_date, to_date]]
		elif from_date:
			shift_filters["shift_date"] = [">=", from_date]
		else:
			shift_filters["shift_date"] = ["<=", to_date]
		shift_names = get_report_rows("Shift", filters=shift_filters, pluck="name")
		requested_shift = filters.get("custom_pea_shift")
		if requested_shift:
			shift_names = [shift_name for shift_name in shift_names if shift_name == requested_shift]
		db_filters["custom_pea_shift"] = ["in", shift_names or [_NO_MATCHING_SHIFT]]

	fg_item = filters.get("fg_item")
	if fg_item:
		_restrict_stock_entry_names(db_filters, get_stock_entries_for_fg_item(fg_item))

	bom_no = filters.get("bom_no")
	if bom_no and "bom_no" in filter_keys:
		_restrict_stock_entry_names(
			db_filters,
			get_stock_entries_for_bom(bom_no, filters=db_filters),
		)

	return db_filters


def get_shift_production_dates(shift_names: list[str] | set[str]) -> dict[str, Any]:
	names = sorted({shift_name for shift_name in shift_names if shift_name})
	if not names:
		return {}
	rows = get_report_rows(
		"Shift",
		filters={"name": ["in", names], "status": "Completed"},
		fields=["name", "shift_date"],
		limit_page_length=0,
	)
	return {row.get("name"): row.get("shift_date") for row in rows if row.get("name")}


def is_production_stock_entry(entry: dict) -> bool:
	if entry.get("purpose") is None and entry.get("custom_pea_joint_lh_rh_production") is None:
		return True
	return entry.get("purpose") == "Manufacture" or is_joint_lh_rh_entry(entry)


def is_joint_lh_rh_entry(entry: dict) -> bool:
	joint_flag = entry.get("custom_pea_joint_lh_rh_production")
	if joint_flag is not None:
		return bool(joint_flag)
	if not entry.get("stock_entry_type") or not hasattr(entry, "flags"):
		return False
	return is_joint_lh_rh_stock_entry_type(entry)


def add_stock_entry_type_flags(entries: list[dict]) -> list[dict]:
	stock_entry_types = sorted(
		{entry.get("stock_entry_type") for entry in entries if entry.get("stock_entry_type")}
	)
	if not stock_entry_types:
		return entries
	rows = frappe.get_all(
		"Stock Entry Type",
		filters={"name": ["in", stock_entry_types]},
		fields=["name", "custom_pea_joint_lh_rh_production"],
		limit_page_length=0,
	)
	joint_flags = {row.get("name"): bool(row.get("custom_pea_joint_lh_rh_production")) for row in rows}
	for entry in entries:
		entry["custom_pea_joint_lh_rh_production"] = int(bool(joint_flags.get(entry.get("stock_entry_type"))))
	return entries


def get_entry_output_quantities(
	entry: dict,
	*,
	normal_metrics: dict | None = None,
) -> EntryOutputQuantities:
	"""Return gross, OK, and rejected part quantities with one cross-mode meaning.

	Reports should pass their batched child-row metrics for normal Manufacture
	entries. Document hooks can use the header fields directly.
	"""
	if is_joint_lh_rh_entry(entry):
		total_qty = flt(entry.get("custom_pea_lh_gross_qty")) + flt(entry.get("custom_pea_rh_gross_qty"))
		rejection_qty = flt(entry.get("custom_pea_lh_rejection_qty")) + flt(
			entry.get("custom_pea_rh_rejection_qty")
		)
	elif normal_metrics is not None and (
		flt(normal_metrics.get("good_qty") or 0) > 0
		or flt(normal_metrics.get("total_rejected_qty") or 0) > 0
		or flt(entry.get("fg_completed_qty") or 0) <= 0
	):
		rejection_qty = flt(normal_metrics.get("total_rejected_qty") or 0)
		total_qty = flt(normal_metrics.get("good_qty") or 0) + rejection_qty
	else:
		total_qty = flt(entry.get("fg_completed_qty") or 0)
		rejection_qty = flt(entry.get("custom_pea_rejection_qty") or 0)
	return EntryOutputQuantities(total_qty, max(total_qty - rejection_qty, 0), rejection_qty)


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
	stock_entry_type = DocType("Stock Entry Type")
	rows = (
		frappe.qb.from_(stock_entry_detail)
		.inner_join(stock_entry)
		.on(stock_entry.name == stock_entry_detail.parent)
		.left_join(stock_entry_type)
		.on(stock_entry_type.name == stock_entry.stock_entry_type)
		.select(stock_entry_detail.parent)
		.distinct()
		.where(
			# Keep parent-level constraints here because this helper is reused independently
			# from report filter builders.
			(stock_entry_detail.item_code == item_code)
			& _get_good_output_criterion(stock_entry_detail)
			& (stock_entry.docstatus == 1)
			& (
				(stock_entry.purpose == "Manufacture")
				| (
					(stock_entry.purpose == "Repack")
					& (stock_entry_type.custom_pea_joint_lh_rh_production == 1)
				)
			)
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


def get_stock_entries_for_bom(bom_no: str, *, filters: dict | None = None) -> list[str]:
	"""Return permitted normal or joint Stock Entries linked to a BOM."""
	rows = get_report_rows(
		"Stock Entry",
		filters=dict(filters or {"docstatus": 1}),
		or_filters=[
			["bom_no", "=", bom_no],
			["custom_pea_lh_bom", "=", bom_no],
			["custom_pea_rh_bom", "=", bom_no],
		],
		fields=["name"],
		limit_page_length=_MAX_BOM_PARENT_MATCHES + 1,
	)
	if len(rows) > _MAX_BOM_PARENT_MATCHES:
		frappe.throw(
			_("BOM filter matches more than {0} Stock Entries. Add a date or shift filter and retry.").format(
				_MAX_BOM_PARENT_MATCHES
			)
		)
	return [row.get("name") for row in rows if row.get("name")]


def _restrict_stock_entry_names(db_filters: dict, parent_names: list[str]) -> None:
	matched_names = set(parent_names)
	existing = db_filters.get("name")
	if isinstance(existing, list | tuple) and len(existing) == 2 and existing[0] == "in":
		matched_names.intersection_update(existing[1])
	db_filters["name"] = ["in", sorted(matched_names) or [""]]


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
	query_fields = list(fields)
	for fieldname in (
		"purpose",
		"stock_entry_type",
		"custom_pea_shift",
		"custom_pea_total_strokes",
		"custom_pea_lh_gross_qty",
		"custom_pea_lh_rejection_qty",
		"custom_pea_rh_gross_qty",
		"custom_pea_rh_rejection_qty",
	):
		if fieldname not in query_fields:
			query_fields.append(fieldname)
	effective_chunk_size = max(int(chunk_size or _DEFAULT_REPORT_CHUNK_SIZE), 1)
	processed_rows = 0
	last_row: dict | None = None
	while True:
		raw_rows = _fetch_stock_entry_chunk(
			filters=filters,
			fields=query_fields,
			order_by=normalized_order_by,
			chunk_size=effective_chunk_size,
			last_row=last_row,
		)
		if not raw_rows:
			break
		processed_rows += len(raw_rows)
		if max_rows > 0 and processed_rows > max_rows:
			frappe.throw(
				_(
					"Report scope exceeds {0} Stock Entries. Narrow filters by date, shift, workstation, operator, or BOM."
				).format(max_rows)
			)
		add_stock_entry_type_flags(raw_rows)
		rows = [row for row in raw_rows if is_production_stock_entry(row)]
		production_dates = get_shift_production_dates(
			{row.get("custom_pea_shift") for row in rows if row.get("custom_pea_shift")}
		)
		for row in rows:
			production_date = production_dates.get(row.get("custom_pea_shift"))
			if production_date:
				row["production_date"] = production_date
		if rows:
			yield rows
		if len(raw_rows) < effective_chunk_size:
			break
		last_row = raw_rows[-1]


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
	query_filters = _as_list_filters(filters)

	if order_by == "name asc":
		if last_row:
			last_name = last_row.get("name")
			if not last_name:
				frappe.throw(_("Missing Stock Entry name for keyset pagination."))
			query_filters.append(["name", ">", last_name])
		return get_report_rows(
			"Stock Entry",
			filters=query_filters,
			or_filters=_PRODUCTION_STOCK_ENTRY_OR_FILTERS,
			fields=fields,
			order_by=order_by,
			limit_page_length=chunk_size,
		)

	if last_row:
		last_posting_date = last_row.get("posting_date")
		last_name = last_row.get("name")
		if last_posting_date is None or not last_name:
			frappe.throw(_("Missing Stock Entry posting date or name for keyset pagination."))
		same_day_rows = get_report_rows(
			"Stock Entry",
			filters=[
				*query_filters,
				["posting_date", "=", last_posting_date],
				["name", ">", last_name],
			],
			or_filters=_PRODUCTION_STOCK_ENTRY_OR_FILTERS,
			fields=fields,
			order_by=order_by,
			limit_page_length=chunk_size,
		)
		remaining = chunk_size - len(same_day_rows)
		if remaining <= 0:
			return same_day_rows
		later_rows = get_report_rows(
			"Stock Entry",
			filters=[*query_filters, ["posting_date", ">", last_posting_date]],
			or_filters=_PRODUCTION_STOCK_ENTRY_OR_FILTERS,
			fields=fields,
			order_by=order_by,
			limit_page_length=remaining,
		)
		return [*same_day_rows, *later_rows]

	return get_report_rows(
		"Stock Entry",
		filters=query_filters,
		or_filters=_PRODUCTION_STOCK_ENTRY_OR_FILTERS,
		fields=fields,
		order_by=order_by,
		limit_page_length=chunk_size,
	)


def _as_list_filters(filters: dict) -> list[list]:
	result = []
	for fieldname, value in filters.items():
		if isinstance(value, list | tuple) and len(value) == 2:
			result.append([fieldname, value[0], value[1]])
		else:
			result.append([fieldname, "=", value])
	return result


def get_entry_qty_maps(
	stock_entry_names: list[str],
) -> tuple[dict[str, float], dict[str, float]]:
	if not stock_entry_names:
		return {}, {}

	parent_metrics = get_parent_quantity_metrics(stock_entry_names)

	good_qty_map: dict[str, float] = {}
	for parent, metrics in parent_metrics.items():
		good_qty_map[parent] = flt(metrics.get("good_qty") or 0)

	rejection_qty_map: dict[str, float] = {}
	for parent, metrics in parent_metrics.items():
		rejection_qty_map[parent] = flt(metrics.get("rejection_qty") or 0)

	return good_qty_map, rejection_qty_map


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
			_get_good_output_criterion(stock_entry_detail),
			stock_entry_detail.qty * stock_entry_detail.conversion_factor,
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
			rejection_breakup.output_side,
			rejection_breakup.item_code,
			Sum(rejection_breakup.qty).as_("qty"),
		)
		.where(rejection_breakup.parenttype == "Stock Entry")
		.where(rejection_breakup.parent.isin(stock_entry_names))
		.groupby(
			rejection_breakup.parent,
			rejection_breakup.rejection_reason,
			rejection_breakup.output_side,
			rejection_breakup.item_code,
		)
	)
	if is_rework is True:
		query = query.where(rejection_breakup.is_rework == 1)
	elif is_rework is False:
		query = query.where(rejection_breakup.is_rework.isnull() | (rejection_breakup.is_rework == 0))
	return query.run(as_dict=True)


def get_finished_item_maps(stock_entry_names: list[str]) -> tuple[dict[str, str], dict[str, str]]:
	if not stock_entry_names:
		return {}, {}

	stock_entry_detail = DocType("Stock Entry Detail")
	rows = (
		frappe.qb.from_(stock_entry_detail)
		.select(stock_entry_detail.parent, stock_entry_detail.item_code)
		.where(stock_entry_detail.parent.isin(stock_entry_names))
		.where(_get_good_output_criterion(stock_entry_detail))
		.orderby(stock_entry_detail.parent, stock_entry_detail.idx)
	).run(as_dict=True)
	items_by_parent: dict[str, list[str]] = defaultdict(list)
	for row in rows:
		parent = row.get("parent")
		item_code = row.get("item_code")
		if parent and item_code and item_code not in items_by_parent[parent]:
			items_by_parent[parent].append(item_code)
	return (
		{parent: item_codes[0] for parent, item_codes in items_by_parent.items()},
		{parent: " + ".join(item_codes) for parent, item_codes in items_by_parent.items()},
	)


def get_item_bom_quality_facts(entries: list[dict], *, is_rework: bool) -> list[dict]:
	"""Return normal or joint output facts for item/BOM quality reports."""
	entry_names = [entry.get("name") for entry in entries if entry.get("name")]
	if not entry_names:
		return []

	parent_metrics = get_parent_quantity_metrics(entry_names, include_rework=is_rework)
	item_by_entry, _item_labels = get_finished_item_maps(entry_names)
	breakup_rows = get_parent_breakup_reason_rows(entry_names, is_rework=is_rework)
	joint_items = _get_joint_output_item_map(entry_names)
	quality_by_output: dict[tuple[str, str], float] = defaultdict(float)
	reasons_by_output: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
	breakup_items: dict[tuple[str, str], str] = {}
	joint_entry_names = {entry.get("name") for entry in entries if is_joint_lh_rh_entry(entry)}

	for breakup in breakup_rows:
		parent = breakup.get("parent")
		if not parent:
			continue
		side = breakup.get("output_side") if parent in joint_entry_names else ""
		if parent in joint_entry_names and side not in ("LH", "RH"):
			continue
		key = (parent, side or "")
		qty = flt(breakup.get("qty") or 0)
		quality_by_output[key] += qty
		if breakup.get("item_code"):
			breakup_items[key] = breakup.get("item_code")
		reason = breakup.get("rejection_reason")
		if reason and qty > 0:
			reasons = reasons_by_output[key]
			reasons[reason] = flt(reasons.get(reason) or 0) + qty

	facts: list[dict] = []
	for entry in entries:
		parent = entry.get("name")
		if not parent:
			continue
		if is_joint_lh_rh_entry(entry):
			for side in ("LH", "RH"):
				key = (parent, side)
				facts.append(
					{
						"parent": parent,
						"item_code": joint_items.get(key) or breakup_items.get(key),
						"bom_no": entry.get(f"custom_pea_{side.lower()}_bom"),
						"total_qty": flt(entry.get(f"custom_pea_{side.lower()}_gross_qty") or 0),
						"quality_qty": flt(quality_by_output.get(key) or 0),
						"reason_totals": reasons_by_output.get(key) or {},
					}
				)
			continue

		metrics = parent_metrics.get(parent, {})
		total_qty = flt(entry.get("fg_completed_qty") or 0)
		if total_qty <= 0:
			total_qty = flt(metrics.get("good_qty") or 0) + flt(metrics.get("total_rejected_qty") or 0)
		facts.append(
			{
				"parent": parent,
				"item_code": item_by_entry.get(parent),
				"bom_no": entry.get("bom_no"),
				"total_qty": total_qty,
				"quality_qty": flt(quality_by_output.get((parent, "")) or 0),
				"reason_totals": reasons_by_output.get((parent, "")) or {},
			}
		)
	return facts


def get_item_bom_quality_hotspot_rows(
	filters: dict,
	*,
	is_rework: bool,
	quantity_field: str,
	rate_field: str,
	timeout_guard: Any,
) -> list[dict]:
	"""Aggregate item/BOM quality facts for the rejection and rework hotspot reports."""
	stock_entry_filters = build_stock_entry_filters(
		filters,
		filter_keys=("custom_pea_workstation", "custom_pea_shift", "custom_pea_operator", "bom_no"),
	)
	requested_bom = filters.get("bom_no")
	agg: dict[tuple[str, str], dict] = {}
	has_entries = False
	for entries in iter_stock_entries_in_chunks(
		stock_entry_filters,
		[
			"name",
			"fg_completed_qty",
			"custom_pea_rejection_qty",
			"custom_pea_rework_qty",
			"bom_no",
			"custom_pea_lh_bom",
			"custom_pea_lh_gross_qty",
			"custom_pea_rh_bom",
			"custom_pea_rh_gross_qty",
		],
	):
		timeout_guard()
		has_entries = True
		for fact in get_item_bom_quality_facts(entries, is_rework=is_rework):
			if requested_bom and fact.get("bom_no") != requested_bom:
				continue
			group = (fact.get("item_code") or _("Unknown"), fact.get("bom_no") or "")
			row = agg.setdefault(
				group,
				{"entries": set(), "total_qty": 0.0, "quality_qty": 0.0, "reason_totals": {}},
			)
			row["entries"].add(fact.get("parent"))
			row["total_qty"] += flt(fact.get("total_qty") or 0)
			row["quality_qty"] += flt(fact.get("quality_qty") or 0)
			for reason, qty in (fact.get("reason_totals") or {}).items():
				row["reason_totals"][reason] = flt(row["reason_totals"].get(reason) or 0) + flt(qty)

	if not has_entries:
		return []

	rows: list[dict] = []
	for (item_code, bom_no), values in agg.items():
		total_qty = flt(values["total_qty"])
		quality_qty = flt(values["quality_qty"])
		reasons = values.get("reason_totals") or {}
		dominant_reason = ""
		if reasons:
			reason, qty = sorted(reasons.items(), key=lambda item: (-flt(item[1]), item[0]))[0]
			dominant_reason = f"{reason} ({format_numeric_summary(qty)})"
		rows.append(
			{
				"item_code": item_code,
				"bom_no": bom_no,
				"entries": len(values["entries"]),
				"total_qty": total_qty,
				quantity_field: quality_qty,
				rate_field: flt((quality_qty / total_qty) * 100) if total_qty > 0 else 0,
				"dominant_reason": dominant_reason,
			}
		)
	rows.sort(key=lambda row: (-flt(row[quantity_field]), row["item_code"], row["bom_no"] or ""))
	return rows


def _get_joint_output_item_map(stock_entry_names: list[str]) -> dict[tuple[str, str], str]:
	if not stock_entry_names:
		return {}
	stock_entry_detail = DocType("Stock Entry Detail")
	rows = (
		frappe.qb.from_(stock_entry_detail)
		.select(
			stock_entry_detail.parent,
			stock_entry_detail.custom_pea_joint_output_side,
			stock_entry_detail.item_code,
		)
		.where(stock_entry_detail.parent.isin(stock_entry_names))
		.where(stock_entry_detail.custom_pea_joint_output_side.isin(("LH", "RH")))
		.where(_get_non_scrap_item_criterion(stock_entry_detail))
	).run(as_dict=True)
	return {
		(row.get("parent"), row.get("custom_pea_joint_output_side")): row.get("item_code")
		for row in rows
		if row.get("parent") and row.get("custom_pea_joint_output_side") and row.get("item_code")
	}


def _get_good_output_criterion(stock_entry_detail: Table) -> Criterion:
	return (
		(stock_entry_detail.is_finished_item == 1)
		& (
			stock_entry_detail.custom_pea_is_rejection_item.isnull()
			| (stock_entry_detail.custom_pea_is_rejection_item == 0)
		)
		& _get_non_scrap_item_criterion(stock_entry_detail)
	)


def is_good_output_row(row: Any) -> bool:
	"""Return whether a Stock Entry Detail row represents finished good output."""
	# Keep this in-memory predicate aligned with _get_good_output_criterion().
	return (
		bool(row.get("is_finished_item"))
		and not row.get("custom_pea_is_rejection_item")
		and _is_non_scrap_row(row)
	)


def _is_non_scrap_row(row: Any) -> bool:
	return (
		not row.get("is_scrap_item")
		and not row.get("is_legacy_scrap_item")
		and row.get("type") != "Scrap"
		and row.get("secondary_item_type") != "Scrap"
	)


def _get_non_scrap_item_criterion(stock_entry_detail: Table) -> Criterion:
	meta = frappe.get_meta("Stock Entry Detail", cached=True)
	criterion = stock_entry_detail.name.isnotnull()
	if meta.has_field("is_scrap_item"):
		criterion &= stock_entry_detail.is_scrap_item.isnull() | (stock_entry_detail.is_scrap_item == 0)
	if meta.has_field("type"):
		criterion &= stock_entry_detail.type.isnull() | (stock_entry_detail.type != "Scrap")
	if meta.has_field("secondary_item_type"):
		criterion &= stock_entry_detail.secondary_item_type.isnull() | (
			stock_entry_detail.secondary_item_type != "Scrap"
		)
	if meta.has_field("is_legacy_scrap_item"):
		criterion &= stock_entry_detail.is_legacy_scrap_item.isnull() | (
			stock_entry_detail.is_legacy_scrap_item == 0
		)
	return criterion


def get_parent_loss_metrics(stock_entry_names: list[str]) -> dict[str, dict[str, float]]:
	"""Return setup and non-setup loss minutes keyed by Stock Entry name."""
	if not stock_entry_names:
		return {}

	parent_metrics: dict[str, dict[str, float]] = {
		name: {"setup_mins": 0.0, "loss_mins": 0.0} for name in stock_entry_names
	}
	loss_rows = get_report_rows(
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
	rejection_qty_map: dict[str, float] | None = None,
) -> tuple[float, float]:
	"""Return (total_strokes, rejection_qty) for one stock entry row."""
	entry_name = entry.get("name")
	rejection_qty = 0.0
	if entry_name and rejection_qty_map is not None:
		rejection_qty = flt(rejection_qty_map.get(entry_name) or 0)

	return flt(entry.get("custom_pea_total_strokes") or 0), rejection_qty


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
			"total_strokes": 0.0,
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
	total_strokes = flt(entry.get("_total_strokes") or 0)
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
	agg["total_strokes"] += total_strokes
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
		actual_spm = (agg["total_strokes"] / duration_mins) if duration_mins > 0 else 0
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
