from __future__ import annotations

import datetime
import time
import tracemalloc
from dataclasses import dataclass
from unittest.mock import patch

import frappe
from frappe import _

from production_entry_app.production_entry_app.overrides.test_stock_entry_hooks import (
	_append_rejection_breakup_rows,
	_create_manufacture_stock_entry,
	_ensure_item_die_tool_fields,
	_ensure_rejection_breakup_custom_field,
	_ensure_rejection_breakup_doctype,
	_ensure_rejection_reason_doctype,
	_ensure_rejection_reasons,
	_ensure_stock_entry_metric_fields,
	_set_shift_buffers,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	bootstrap_manufacturing_test_context,
	ensure_downtime_reason,
	ensure_item,
	ensure_operator,
	ensure_workstation,
)


@dataclass(frozen=True)
class BenchmarkContext:
	company: str
	fg_item: str
	rm_item: str
	operator: str
	workstation: str
	rm_warehouse: str
	fg_warehouse: str
	rejection_warehouse: str


_BENCHMARK_START_DATE = datetime.date(2198, 1, 1)


def run_report_benchmark(
	entry_count: int = 3000,
	day_span: int = 30,
	dataset_key: str = "PHASE2",
) -> dict[str, object]:
	"""Seed benchmark Stock Entries and measure report execution time and peak memory."""
	if entry_count <= 0:
		frappe.throw(_("entry_count must be positive"))
	if day_span <= 0:
		frappe.throw(_("day_span must be positive"))

	context = _prepare_benchmark_context(dataset_key)
	date_range = _seed_benchmark_entries(context, entry_count=entry_count, day_span=day_span)

	return {
		"dataset_key": dataset_key,
		"entry_count": entry_count,
		"day_span": day_span,
		"from_date": date_range["from_date"],
		"to_date": date_range["to_date"],
		"reports": _benchmark_reports(date_range),
	}


def cleanup_report_benchmark(dataset_key: str = "PHASE2") -> dict[str, int | str]:
	"""Remove benchmark Stock Entries and linked child rows for one dataset key."""
	operator = f"Benchmark Operator {dataset_key}"
	workstation = f"Benchmark Workstation {dataset_key}"
	rows = frappe.get_all(
		"Stock Entry",
		filters={
			"purpose": "Manufacture",
			"custom_operator": operator,
			"custom_workstation": workstation,
		},
		fields=["name", "custom_shift"],
	)
	entry_names = [row.get("name") for row in rows if row.get("name")]
	shift_names = sorted({row.get("custom_shift") for row in rows if row.get("custom_shift")})
	if not entry_names:
		return {"dataset_key": dataset_key, "deleted_stock_entries": 0, "deleted_shifts": 0}

	frappe.db.delete("Loss Entry", {"parenttype": "Stock Entry", "parent": ["in", entry_names]})
	frappe.db.delete("Rejection Breakup", {"parenttype": "Stock Entry", "parent": ["in", entry_names]})
	frappe.db.delete("Stock Entry Detail", {"parenttype": "Stock Entry", "parent": ["in", entry_names]})
	frappe.db.delete("Stock Entry", {"name": ["in", entry_names]})

	if shift_names:
		frappe.db.delete("Loss Entry", {"parenttype": "Shift", "parent": ["in", shift_names]})
		frappe.db.delete("Shift", {"name": ["in", shift_names]})

	frappe.db.commit()  # nosemgrep: benchmark cleanup must commit deletes before reseeding/measuring
	return {
		"dataset_key": dataset_key,
		"deleted_stock_entries": len(entry_names),
		"deleted_shifts": len(shift_names),
	}


def _prepare_benchmark_context(dataset_key: str) -> BenchmarkContext:
	_ensure_rejection_breakup_doctype()
	_ensure_rejection_reason_doctype()
	_ensure_rejection_reasons()
	_ensure_rejection_breakup_custom_field()
	_ensure_stock_entry_metric_fields()
	_ensure_item_die_tool_fields()
	_set_shift_buffers(start_mins=60, end_mins=60)

	for reason in (
		"Setup Time",
		"Trial",
		"Mtrl Handl",
		"No Operator",
		"No Mtrl",
		"Maint",
		"P. Maint",
		"Tool Break",
		"Other",
		"No Helper",
		"Power Off",
		"Tea Break",
		"Lunch Break",
	):
		ensure_downtime_reason(reason)

	base_context = bootstrap_manufacturing_test_context(f"Report Benchmark {dataset_key}")
	operator = f"Benchmark Operator {dataset_key}"
	workstation = f"Benchmark Workstation {dataset_key}"
	fg_item = f"_Benchmark FG Item {dataset_key}"
	rm_item = f"_Benchmark RM Item {dataset_key}"

	ensure_operator(operator)
	ensure_workstation(workstation, standard_spm=2)
	ensure_item(fg_item)
	ensure_item(rm_item)

	if frappe.get_meta("Warehouse", cached=True).has_field("is_rejected_warehouse"):
		frappe.db.set_value(
			"Warehouse",
			base_context["rejection_warehouse"],
			"is_rejected_warehouse",
			1,
			update_modified=False,
		)

	return BenchmarkContext(
		company=base_context["company"],
		fg_item=fg_item,
		rm_item=rm_item,
		operator=operator,
		workstation=workstation,
		rm_warehouse=base_context["rm_warehouse"],
		fg_warehouse=base_context["fg_warehouse"],
		rejection_warehouse=base_context["rejection_warehouse"],
	)


def _seed_benchmark_entries(
	context: BenchmarkContext,
	*,
	entry_count: int,
	day_span: int,
) -> dict[str, str]:
	start_date = _BENCHMARK_START_DATE

	created = frappe.db.count(
		"Stock Entry",
		filters={
			"purpose": "Manufacture",
			"custom_operator": context.operator,
			"custom_workstation": context.workstation,
		},
	)
	if created >= entry_count:
		last_offset = _get_benchmark_day_offset(entry_count - 1, day_span)
		return {
			"from_date": start_date.isoformat(),
			"to_date": (start_date + datetime.timedelta(days=last_offset)).isoformat(),
		}

	shifts: dict[tuple[str, str], str] = {}
	for index in range(created, entry_count):
		day_offset = _get_benchmark_day_offset(index, day_span)
		slot_index = _get_benchmark_shift_slot(index, day_span)
		shift_label = _get_benchmark_shift_label(index, day_span)
		posting_date = start_date + datetime.timedelta(days=day_offset)
		shift_name = shifts.get((posting_date.isoformat(), shift_label))
		if not shift_name:
			shift_name = _ensure_shift(posting_date, shift_label, context.rejection_warehouse)
			shifts[(posting_date.isoformat(), shift_label)] = shift_name

		start_hour = 8 if shift_label == "1" else 16
		entry_start = datetime.datetime.combine(
			posting_date,
			datetime.time(hour=start_hour + slot_index, minute=0, second=0),
		)
		entry_end = entry_start + datetime.timedelta(minutes=45)
		rejection_qty = 5 if index % 5 == 0 else 0
		loss_rows = (
			[
				{
					"downtime_reason": "Setup Time" if shift_label == "1" else "Maint",
					"start_time": (entry_end + datetime.timedelta(minutes=15)).time().strftime("%H:%M:%S"),
					"end_time": (entry_end + datetime.timedelta(minutes=30)).time().strftime("%H:%M:%S"),
				}
			]
			if index % 3 == 0
			else []
		)
		_create_mock_submitted_entry(
			context=context,
			posting_date=posting_date.isoformat(),
			planned_start=entry_start.strftime("%Y-%m-%d %H:%M:%S"),
			planned_end=entry_end.strftime("%Y-%m-%d %H:%M:%S"),
			actual_start=entry_start.strftime("%Y-%m-%d %H:%M:%S"),
			actual_end=entry_end.strftime("%Y-%m-%d %H:%M:%S"),
			fg_qty=100 + (index % 20),
			rejection_qty=rejection_qty,
			shift_name=shift_name,
			unplanned_losses=loss_rows,
		)

	last_offset = _get_benchmark_day_offset(entry_count - 1, day_span)
	return {
		"from_date": start_date.isoformat(),
		"to_date": (start_date + datetime.timedelta(days=last_offset)).isoformat(),
	}


def _get_benchmark_day_offset(index: int, day_span: int) -> int:
	slots_per_shift = 8
	cycle_size = day_span * 2 * slots_per_shift
	cycle = index // cycle_size
	return (index % day_span) + (cycle * day_span)


def _get_benchmark_shift_slot(index: int, day_span: int) -> int:
	return (index // (day_span * 2)) % 8


def _get_benchmark_shift_label(index: int, day_span: int) -> str:
	return "1" if (index // day_span) % 2 == 0 else "2"


def _ensure_shift(shift_date: datetime.date, shift_label: str, rejection_warehouse: str) -> str:
	shift_name = f"SHIFT-{shift_date.isoformat()}.Shift-{shift_label}"
	if frappe.db.exists("Shift", shift_name):
		frappe.db.set_value("Shift", shift_name, "status", "Running", update_modified=False)
		return shift_name

	shift = frappe.get_doc(
		{
			"doctype": "Shift",
			"shift_label": shift_label,
			"shift_duration": "8",
			"shift_date": shift_date.isoformat(),
			"planned_start_time": "08:00:00" if shift_label == "1" else "16:00:00",
			"rejection_warehouse": rejection_warehouse,
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Shift", shift.name, "status", "Running", update_modified=False)
	return shift.name


def _create_mock_submitted_entry(
	*,
	context: BenchmarkContext,
	posting_date: str,
	planned_start: str,
	planned_end: str,
	actual_start: str,
	actual_end: str,
	fg_qty: float,
	rejection_qty: float,
	shift_name: str,
	unplanned_losses: list[dict] | None = None,
) -> str:
	stock_entry = _create_manufacture_stock_entry(
		company=context.company,
		fg_item=context.fg_item,
		rm_item=context.rm_item,
		fg_qty=fg_qty,
		rm_qty=fg_qty,
		custom_rejection_qty=rejection_qty,
		fg_warehouse=context.fg_warehouse,
		rm_warehouse=context.rm_warehouse,
	)
	stock_entry.custom_operator = context.operator
	stock_entry.custom_workstation = context.workstation
	stock_entry.custom_shift = shift_name
	stock_entry.custom_standard_spm = 2
	stock_entry.custom_planned_start_date = planned_start
	stock_entry.custom_planned_end_date = planned_end
	stock_entry.custom_actual_start_date = actual_start
	stock_entry.custom_actual_end_date = actual_end
	stock_entry.posting_date = posting_date
	stock_entry.posting_time = "09:00:00"

	if rejection_qty > 0:
		_append_rejection_breakup_rows(
			stock_entry,
			[{"rejection_reason": "Burr", "qty": rejection_qty, "remark": "Benchmark row"}],
		)
	for row in unplanned_losses or []:
		stock_entry.append(
			"custom_unplanned_losses",
			{
				"downtime_reason": row.get("downtime_reason"),
				"start_time": row.get("start_time"),
				"end_time": row.get("end_time"),
				"remark": row.get("remark"),
				"shift": shift_name,
			},
		)

	stock_entry.save(ignore_permissions=True)
	frappe.db.set_value("Stock Entry", stock_entry.name, "posting_date", posting_date, update_modified=False)
	frappe.db.set_value("Stock Entry", stock_entry.name, "docstatus", 1, update_modified=False)
	return stock_entry.name


def _benchmark_reports(date_range: dict[str, str]) -> dict[str, dict[str, float | int]]:
	default_filters = {"from_date": date_range["from_date"], "to_date": date_range["to_date"]}
	report_specs = {
		"operator_efficiency": (
			"production_entry_app.production_entry_app.report.operator_efficiency_report.operator_efficiency_report",
			default_filters,
		),
		"workstation_efficiency": (
			"production_entry_app.production_entry_app.report.workstation_efficiency_report.workstation_efficiency_report",
			default_filters,
		),
		"production_oee": (
			"production_entry_app.production_entry_app.report.production_oee_report.production_oee_report",
			default_filters,
		),
		"rejection_pareto": (
			"production_entry_app.production_entry_app.report.rejection_pareto_report.rejection_pareto_report",
			default_filters,
		),
		"rework_pareto": (
			"production_entry_app.production_entry_app.report.rework_pareto_report.rework_pareto_report",
			default_filters,
		),
		"workstation_rejection_matrix": (
			"production_entry_app.production_entry_app.report.workstation_rejection_reason_matrix.workstation_rejection_reason_matrix",
			{**default_filters, "top_n_reasons": 5},
		),
		"workstation_rework_matrix": (
			"production_entry_app.production_entry_app.report.workstation_rework_reason_matrix.workstation_rework_reason_matrix",
			{**default_filters, "top_n_reasons": 5},
		),
		"item_bom_rejection_hotspots": (
			"production_entry_app.production_entry_app.report.item_bom_rejection_hotspots.item_bom_rejection_hotspots",
			default_filters,
		),
		"item_bom_rework_hotspots": (
			"production_entry_app.production_entry_app.report.item_bom_rework_hotspots.item_bom_rework_hotspots",
			default_filters,
		),
	}
	results: dict[str, dict[str, float | int]] = {}
	for key, (module_path, filters) in report_specs.items():
		report_module = frappe.get_module(module_path)
		sql_count = 0
		chunk_fetch_count = 0
		original_sql = frappe.db.sql
		original_get_all = frappe.get_all
		original_db_get_all = frappe.db.get_all

		def counted_sql(*args, **kwargs):
			nonlocal sql_count
			sql_count += 1
			return original_sql(*args, **kwargs)

		def counted_fetch_chunk(*args, **kwargs):
			nonlocal chunk_fetch_count
			chunk_fetch_count += 1
			return original_fetch_chunk(*args, **kwargs)

		def counted_get_all(*args, **kwargs):
			nonlocal chunk_fetch_count
			doctype = args[0] if args else kwargs.get("doctype")
			if doctype == "Stock Entry":
				chunk_fetch_count += 1
			return original_get_all(*args, **kwargs)

		def counted_db_get_all(*args, **kwargs):
			nonlocal chunk_fetch_count
			doctype = args[0] if args else kwargs.get("doctype")
			if doctype == "Stock Entry":
				chunk_fetch_count += 1
			return original_db_get_all(*args, **kwargs)

		from production_entry_app.production_entry_app.report import report_utils

		tracemalloc.start()
		start = time.perf_counter()
		with patch.object(frappe.db, "sql", side_effect=counted_sql):
			if hasattr(report_utils, "_fetch_stock_entry_chunk"):
				original_fetch_chunk = report_utils._fetch_stock_entry_chunk
				with patch.object(report_utils, "_fetch_stock_entry_chunk", side_effect=counted_fetch_chunk):
					columns, rows = _extract_columns_rows(report_module.execute(filters))
			else:
				with patch.object(frappe, "get_all", side_effect=counted_get_all):
					with patch.object(frappe.db, "get_all", side_effect=counted_db_get_all):
						columns, rows = _extract_columns_rows(report_module.execute(filters))
		elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
		_current, peak = tracemalloc.get_traced_memory()
		tracemalloc.stop()
		results[key] = {
			"elapsed_ms": elapsed_ms,
			"peak_memory_kb": round(peak / 1024, 2),
			"row_count": len(rows),
			"column_count": len(columns),
			"sql_count": sql_count,
			"stock_entry_chunk_fetches": chunk_fetch_count,
		}
	return results


def _extract_columns_rows(execute_result: tuple) -> tuple[list[dict], list[dict]]:
	if not execute_result:
		return [], []
	return execute_result[0], execute_result[1]
