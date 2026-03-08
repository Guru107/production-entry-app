from __future__ import annotations

import datetime
import math
import time
from statistics import mean
from unittest.mock import patch

import frappe

from production_entry_app.production_entry_app import performance_indexes
from production_entry_app.production_entry_app.overrides.test_stock_entry_hooks import (
	_create_manufacture_stock_entry,
)
from production_entry_app.production_entry_app.report import report_benchmark


def run_stock_entry_write_benchmark(
	iterations: int = 20,
	warmup_iterations: int = 1,
	seed_entries: int = 10000,
	day_span: int = 20,
	dataset_key: str = "WRITEPATH",
	source_dataset_key: str = "PHASE2",
) -> dict[str, object]:
	"""Benchmark Stock Entry save latency with and without overlap indexes."""
	if iterations <= 0:
		frappe.throw("iterations must be positive")
	if warmup_iterations < 0:
		frappe.throw("warmup_iterations cannot be negative")
	if seed_entries <= 0:
		frappe.throw("seed_entries must be positive")
	if day_span <= 0:
		frappe.throw("day_span must be positive")

	context, last_seed_date = _get_existing_benchmark_context(source_dataset_key)
	if context and last_seed_date:
		date_range = {"from_date": "", "to_date": last_seed_date}
	else:
		context = _prepare_write_benchmark_context(dataset_key)
		date_range = report_benchmark._seed_benchmark_entries(
			context,
			entry_count=seed_entries,
			day_span=day_span,
		)
	total_iterations = iterations + warmup_iterations
	benchmark_shifts = _ensure_write_benchmark_shifts(
		context.rejection_warehouse,
		total_iterations,
		date_range["to_date"],
	)

	results: dict[str, dict[str, float | int | str]] = {}
	try:
		results["with_overlap_indexes"] = _run_write_case(
			context=context,
			benchmark_shifts=benchmark_shifts,
			case_name="with_overlap_indexes",
			enable_overlap_indexes=True,
			warmup_iterations=warmup_iterations,
		)
		results["without_overlap_indexes"] = _run_write_case(
			context=context,
			benchmark_shifts=benchmark_shifts,
			case_name="without_overlap_indexes",
			enable_overlap_indexes=False,
			warmup_iterations=warmup_iterations,
		)
	finally:
		performance_indexes.ensure_overlap_indexes()
		frappe.db.commit()

	with_indexes = results["with_overlap_indexes"]
	without_indexes = results["without_overlap_indexes"]
	return {
		"dataset_key": dataset_key,
		"source_dataset_key": source_dataset_key,
		"seed_entries": seed_entries,
		"day_span": day_span,
		"iterations": iterations,
		"warmup_iterations": warmup_iterations,
		"seed_from_date": date_range["from_date"],
		"seed_to_date": date_range["to_date"],
		"cases": results,
		"delta": {
			"avg_ms_pct": _delta_pct(
				with_indexes["avg_elapsed_ms"],
				without_indexes["avg_elapsed_ms"],
			),
			"p95_ms_pct": _delta_pct(
				with_indexes["p95_elapsed_ms"],
				without_indexes["p95_elapsed_ms"],
			),
			"avg_sql_pct": _delta_pct(
				with_indexes["avg_sql_count"],
				without_indexes["avg_sql_count"],
			),
		},
	}


def _run_write_case(
	*,
	context: report_benchmark.BenchmarkContext,
	benchmark_shifts: list[dict[str, str]],
	case_name: str,
	enable_overlap_indexes: bool,
	warmup_iterations: int,
) -> dict[str, float | int | str]:
	if enable_overlap_indexes:
		performance_indexes.ensure_overlap_indexes()
	else:
		performance_indexes.drop_overlap_indexes_if_exists()
	frappe.db.commit()

	elapsed_samples: list[float] = []
	sql_samples: list[int] = []
	created_names: list[str] = []

	for index, benchmark_shift in enumerate(benchmark_shifts):
		sql_count = 0
		original_sql = frappe.db.sql

		def counted_sql(*args, **kwargs):
			nonlocal sql_count
			sql_count += 1
			return original_sql(*args, **kwargs)

		with patch.object(frappe.db, "sql", side_effect=counted_sql):
			start = time.perf_counter()
			stock_entry_name = _save_candidate_entry(
				context=context,
				shift_name=benchmark_shift["shift_name"],
				posting_date=benchmark_shift["posting_date"],
				start_time=benchmark_shift["start_time"],
				end_time=benchmark_shift["end_time"],
			)
			frappe.db.commit()
			elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
			if index >= warmup_iterations:
				elapsed_samples.append(elapsed_ms)
				sql_samples.append(sql_count)
			created_names.append(stock_entry_name)

	for name in created_names:
		frappe.delete_doc("Stock Entry", name, force=True, ignore_permissions=True)
	frappe.db.commit()

	return {
		"case": case_name,
		"iterations": len(elapsed_samples),
		"avg_elapsed_ms": round(mean(elapsed_samples), 2),
		"p95_elapsed_ms": _p95(elapsed_samples),
		"avg_sql_count": round(mean(sql_samples), 2),
		"max_sql_count": max(sql_samples),
	}


def _prepare_write_benchmark_context(dataset_key: str) -> report_benchmark.BenchmarkContext:
	with patch(
		"production_entry_app.production_entry_app.report.report_benchmark._set_shift_buffers",
		return_value=None,
	):
		return report_benchmark._prepare_benchmark_context(dataset_key)


def _get_existing_benchmark_context(
	source_dataset_key: str,
) -> tuple[report_benchmark.BenchmarkContext | None, str | None]:
	operator = f"Benchmark Operator {source_dataset_key}"
	workstation = f"Benchmark Workstation {source_dataset_key}"
	entry_rows = frappe.get_all(
		"Stock Entry",
		filters={
			"purpose": "Manufacture",
			"custom_operator": operator,
			"custom_workstation": workstation,
		},
		fields=["name", "company", "custom_shift", "posting_date", "from_warehouse", "to_warehouse"],
		order_by="posting_date desc, name desc",
		limit=1,
	)
	if not entry_rows:
		return None, None

	entry_row = entry_rows[0]
	item_rows = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": entry_row["name"]},
		fields=["item_code", "is_finished_item", "s_warehouse", "t_warehouse"],
		order_by="idx asc",
	)
	fg_row = next((row for row in item_rows if row.get("is_finished_item")), None)
	rm_row = next((row for row in item_rows if not row.get("is_finished_item")), None)
	if not fg_row or not rm_row:
		return None, None

	rejection_warehouse = frappe.db.get_value("Shift", entry_row.get("custom_shift"), "rejection_warehouse")
	context = report_benchmark.BenchmarkContext(
		company=entry_row["company"],
		fg_item=fg_row["item_code"],
		rm_item=rm_row["item_code"],
		operator=operator,
		workstation=workstation,
		rm_warehouse=rm_row.get("s_warehouse") or entry_row.get("from_warehouse"),
		fg_warehouse=fg_row.get("t_warehouse") or entry_row.get("to_warehouse"),
		rejection_warehouse=rejection_warehouse or fg_row.get("t_warehouse") or entry_row.get("to_warehouse"),
	)
	return context, str(entry_row["posting_date"])


def _ensure_write_benchmark_shifts(
	rejection_warehouse: str,
	iterations: int,
	last_seed_date: str,
) -> list[dict[str, str]]:
	start_date = datetime.date.fromisoformat(last_seed_date) + datetime.timedelta(days=1)
	shifts: list[dict[str, str]] = []
	for index in range(iterations):
		shift_date = start_date + datetime.timedelta(days=index)
		shift_name = report_benchmark._ensure_shift(shift_date, "1", rejection_warehouse)
		shifts.append(
			{
				"shift_name": shift_name,
				"posting_date": shift_date.isoformat(),
				"start_time": f"{shift_date.isoformat()} 08:00:00",
				"end_time": f"{shift_date.isoformat()} 08:45:00",
			}
		)
	return shifts


def _save_candidate_entry(
	*,
	context: report_benchmark.BenchmarkContext,
	shift_name: str,
	posting_date: str,
	start_time: str,
	end_time: str,
) -> str:
	stock_entry = _create_manufacture_stock_entry(
		company=context.company,
		fg_item=context.fg_item,
		rm_item=context.rm_item,
		fg_qty=100,
		rm_qty=100,
		fg_warehouse=context.fg_warehouse,
		rm_warehouse=context.rm_warehouse,
	)
	stock_entry.custom_operator = context.operator
	stock_entry.custom_workstation = context.workstation
	stock_entry.custom_shift = shift_name
	stock_entry.custom_standard_spm = 2
	stock_entry.custom_planned_start_date = start_time
	stock_entry.custom_planned_end_date = end_time
	stock_entry.custom_actual_start_date = start_time
	stock_entry.custom_actual_end_date = end_time
	stock_entry.posting_date = posting_date
	stock_entry.posting_time = "08:00:00"
	stock_entry.save(ignore_permissions=True)
	return stock_entry.name


def _p95(samples: list[float]) -> float:
	if not samples:
		return 0.0
	ordered = sorted(samples)
	index = max(math.ceil(len(ordered) * 0.95) - 1, 0)
	return round(ordered[index], 2)


def _delta_pct(with_indexes: float, without_indexes: float) -> float:
	if without_indexes == 0:
		return 0.0
	return round(((without_indexes - with_indexes) / without_indexes) * 100, 2)
