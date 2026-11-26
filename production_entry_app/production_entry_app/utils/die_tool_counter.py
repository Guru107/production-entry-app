from __future__ import annotations

import datetime
import time

import frappe
from erpnext.stock.utils import get_combine_datetime
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Case, Order
from frappe.query_builder import DocType as QBDocType
from frappe.query_builder.functions import Coalesce, CustomFunction, IfNull, Sum
from frappe.query_builder.terms import ParameterizedValueWrapper
from frappe.utils import cint, cstr, get_datetime

from production_entry_app.production_entry_app.joint_production import (
	is_paired_production,
)
from production_entry_app.production_entry_app.utils.die_tool_item import DIE_TOOL_ITEM_FIELD

WARNING_THRESHOLD_PCT_DEFAULT: float = 90.0


def resolve_warning_threshold(value: float | None) -> float:
	"""A configured 0 is a valid threshold; only a missing value falls back to the default."""
	return WARNING_THRESHOLD_PCT_DEFAULT if value is None else float(value)


def resolve_die_tool_item_code(doc: Document, *, persisted_only: bool = False) -> str | None:
	"""Return the Item whose Die Tool Counter should receive this entry's strokes."""
	prescribed = cstr(doc.get(DIE_TOOL_ITEM_FIELD)).strip()
	if persisted_only and doc.name:
		prescribed = cstr(frappe.db.get_value(doc.doctype, doc.name, DIE_TOOL_ITEM_FIELD)).strip()
	if prescribed:
		return prescribed
	if is_paired_production(doc):
		return None
	if doc.get("purpose") == "Manufacture":
		return _get_fg_item_code(doc)
	return None


def update_counter_for_stock_entry(doc: Document, direction: int = 1) -> None:
	item_code = resolve_die_tool_item_code(doc, persisted_only=direction < 0)
	if not item_code:
		return
	if direction < 0:
		# No die-tool flag re-check: the recompute counts what the remaining submitted entries say.
		recompute_counter(item_code)
		return
	if not is_die_tool_enabled(item_code):
		return

	total_strokes = float(doc.get("custom_pea_total_strokes") or 0)
	if total_strokes <= 0:
		return

	_increment_counter(item_code, total_strokes, get_combine_datetime(doc.posting_date, doc.posting_time))


def _increment_counter(item_code: str, strokes: float, posted_at: datetime.datetime) -> None:
	counter_name = _ensure_counter_exists(item_code)
	die_tool_counter = QBDocType("Die Tool Counter")
	# Strokes posted at or before the last maintenance belong to the previous die life.
	counted = (
		Case()
		.when(die_tool_counter.last_reset_on.isnull() | (die_tool_counter.last_reset_on < posted_at), strokes)
		.else_(0)
	)

	# stroke_capacity rides on this UPDATE: the row is being written anyway, so a separate
	# set_value would be a wasted round-trip on every submit.
	frappe.qb.update(die_tool_counter).set(
		die_tool_counter.current_stroke_count, die_tool_counter.current_stroke_count + counted
	).set(
		die_tool_counter.stroke_capacity,
		float(frappe.db.get_value("Item", item_code, "custom_pea_stroke_capacity") or 0),
	).where(die_tool_counter.name == counter_name).run()


def recompute_counter(item_code: str) -> float | None:
	"""Set the counter to the strokes of submitted entries posted after the latest active maintenance.

	Returns the new count, or None when the item has no Die Tool Counter.
	"""
	die_tool_counter = QBDocType("Die Tool Counter")
	counter_query = (
		frappe.qb.from_(die_tool_counter)
		.select(die_tool_counter.current_stroke_count)
		.where(die_tool_counter.name == item_code)
	)
	seen = counter_query.run()
	# The row lock makes concurrent submits wait for this recompute, but under REPEATABLE READ the
	# sum below reads this transaction's snapshot: an increment committed after it would be lost.
	if counter_query.for_update().run() != seen:
		frappe.throw(
			_("Die Tool Counter {0} changed while this was saving. Please try again.").format(item_code),
			frappe.QueryDeadlockError,
		)
	if not seen:
		return None

	log = QBDocType("Die Tool Maintenance Log")
	latest_log = (
		frappe.qb.from_(log)
		.select(log.maintenance_date, log.modified_by)
		.where((log.die_tool_item == item_code) & (log.docstatus == 1))
		.orderby(log.maintenance_date, order=Order.desc)
		.limit(1)
		.run(as_dict=True)
	)
	last_reset = latest_log[0] if latest_log else frappe._dict()
	strokes = _sum_strokes_since(item_code, last_reset.maintenance_date)

	frappe.qb.update(die_tool_counter).set(die_tool_counter.current_stroke_count, strokes).set(
		die_tool_counter.last_reset_on, last_reset.maintenance_date
	).set(die_tool_counter.last_reset_by, last_reset.modified_by).where(
		die_tool_counter.name == item_code
	).run()
	return strokes


def _sum_strokes_since(item_code: str, since: datetime.datetime | None) -> float:
	"""Mirror resolve_die_tool_item_code in SQL: the prescribed die tool, else the FG item of a
	non-paired Manufacture entry. Rework entries never post strokes (on_submit skips them)."""
	se = QBDocType("Stock Entry")
	se_type = QBDocType("Stock Entry Type")
	se_detail = QBDocType("Stock Entry Detail")
	first_fg_item = (
		frappe.qb.from_(se_detail)
		.select(se_detail.item_code)
		.where(
			(se_detail.parent == se.name)
			& (se_detail.parenttype == "Stock Entry")
			& (se_detail.is_finished_item == 1)
		)
		.orderby(se_detail.idx)
		.limit(1)
	)
	resolves_to_item = (se[DIE_TOOL_ITEM_FIELD] == item_code) | (
		(IfNull(se[DIE_TOOL_ITEM_FIELD], "") == "")
		& (se.purpose == "Manufacture")
		& (IfNull(se_type.custom_pea_joint_lh_rh_production, 0) == 0)
		& (IfNull(se_type.custom_pea_joint_production, 0) == 0)
		# A subquery on the left would compare as a QueryBuilder (always False), so wrap the value.
		& (ParameterizedValueWrapper(item_code) == first_fg_item)
	)
	query = (
		frappe.qb.from_(se)
		.left_join(se_type)
		.on(se_type.name == se.stock_entry_type)
		.select(Coalesce(Sum(se.custom_pea_total_strokes), 0))
		.where((se.docstatus == 1) & (IfNull(se_type.custom_pea_rework_entry, 0) == 0) & resolves_to_item)
	)
	if since:
		since = get_datetime(since)
		timestamp = CustomFunction("TIMESTAMP", ["date_col", "time_col"])
		# posting_date bound first so the posting_date index narrows the scan.
		query = query.where(se.posting_date >= since.date()).where(
			timestamp(se.posting_date, se.posting_time) > since
		)
	return float(query.run()[0][0] or 0)


def get_counter_health(
	current_strokes: float,
	stroke_capacity: float,
	warning_threshold_pct: float = WARNING_THRESHOLD_PCT_DEFAULT,
) -> tuple[float, int]:
	utilization_pct = ((current_strokes / stroke_capacity) * 100) if stroke_capacity > 0 else 0
	is_maintenance_due = 1 if stroke_capacity > 0 and utilization_pct >= warning_threshold_pct else 0
	return utilization_pct, is_maintenance_due


def _ensure_counter_exists(item_code: str) -> str:
	if frappe.db.exists("Die Tool Counter", item_code):
		return item_code

	doc = frappe.get_doc(
		{
			"doctype": "Die Tool Counter",
			"die_tool_item": item_code,
			"current_stroke_count": 0,
		}
	)

	# Idempotent insert for concurrent requests: ignore duplicate if another request wins the race.
	doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
	if frappe.db.exists("Die Tool Counter", item_code):
		return item_code
	existing_name = frappe.db.get_value("Die Tool Counter", {"die_tool_item": item_code}, "name")
	return existing_name or doc.name


def _get_or_create_counter(item_code: str):
	return frappe.get_doc("Die Tool Counter", _ensure_counter_exists(item_code))


def get_counter_snapshot(item_code: str, retries: int = 2) -> frappe._dict | None:
	if not item_code or not frappe.db.exists("Item", item_code):
		return None

	attempts = max(int(retries), 0) + 1
	for attempt in range(attempts):
		row = frappe.db.get_value(
			"Die Tool Counter",
			{"die_tool_item": item_code},
			["name", "current_stroke_count", "stroke_capacity", "warning_threshold_pct"],
			as_dict=True,
		)
		if row:
			return row
		if attempt < attempts - 1:
			time.sleep(0.02)
	return None


def is_die_tool_enabled(item_code: str | None) -> bool:
	if not item_code:
		return False

	item_meta = frappe.get_meta("Item", cached=True)
	if not item_meta.has_field("custom_pea_has_die_tool"):
		return True

	has_die_tool = frappe.db.get_value("Item", item_code, "custom_pea_has_die_tool")
	if has_die_tool is None:
		return True
	return cint(has_die_tool) == 1


def _get_fg_item_code(doc) -> str | None:
	if doc.get("fg_item"):
		return doc.get("fg_item")
	for row in doc.get("items", []):
		if row.get("is_finished_item"):
			return row.get("item_code")
	return None
