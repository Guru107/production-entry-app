from __future__ import annotations

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import write_benchmark


class TestWriteBenchmark(FrappeTestCase):
	def test_p95_returns_expected_percentile(self) -> None:
		self.assertEqual(write_benchmark._p95([10.0, 20.0, 30.0, 40.0, 50.0]), 50.0)
		self.assertEqual(write_benchmark._p95([]), 0.0)

	def test_delta_pct_reports_improvement_over_without_indexes(self) -> None:
		self.assertEqual(write_benchmark._delta_pct(80.0, 100.0), 20.0)
		self.assertEqual(write_benchmark._delta_pct(100.0, 100.0), 0.0)
		self.assertEqual(write_benchmark._delta_pct(100.0, 0.0), 0.0)

	def test_run_stock_entry_write_benchmark_cleans_owned_seed_data_by_default(self) -> None:
		context = write_benchmark.report_benchmark.BenchmarkContext(
			company="_Test Company",
			fg_item="FG",
			rm_item="RM",
			operator="Benchmark Operator WRITEPATH",
			workstation="Benchmark Workstation WRITEPATH",
			rm_warehouse="RM-WH",
			fg_warehouse="FG-WH",
			rejection_warehouse="REJ-WH",
		)
		with (
			patch(
				"production_entry_app.production_entry_app.write_benchmark.test_cleanup.capture_manufacturing_settings_snapshot",
				return_value={},
			),
			patch(
				"production_entry_app.production_entry_app.write_benchmark.test_cleanup.restore_manufacturing_settings_snapshot"
			),
			patch(
				"production_entry_app.production_entry_app.write_benchmark._get_existing_benchmark_context",
				return_value=(None, None),
			),
			patch(
				"production_entry_app.production_entry_app.write_benchmark._prepare_write_benchmark_context",
				return_value=context,
			),
			patch(
				"production_entry_app.production_entry_app.write_benchmark.report_benchmark._seed_benchmark_entries",
				return_value={"from_date": "2198-01-01", "to_date": "2198-01-20"},
			),
			patch(
				"production_entry_app.production_entry_app.write_benchmark._ensure_write_benchmark_shifts",
				return_value=[],
			),
			patch(
				"production_entry_app.production_entry_app.write_benchmark._run_write_case",
				side_effect=[
					{"avg_elapsed_ms": 10.0, "p95_elapsed_ms": 10.0, "avg_sql_count": 10, "max_sql_count": 10},
					{"avg_elapsed_ms": 20.0, "p95_elapsed_ms": 20.0, "avg_sql_count": 20, "max_sql_count": 20},
				],
			),
			patch(
				"production_entry_app.production_entry_app.write_benchmark._cleanup_write_benchmark_shifts"
			),
			patch(
				"production_entry_app.production_entry_app.write_benchmark.report_benchmark.cleanup_report_benchmark"
			) as cleanup_report_benchmark,
			patch("production_entry_app.production_entry_app.write_benchmark.performance_indexes.ensure_overlap_indexes"),
			patch("production_entry_app.production_entry_app.write_benchmark.frappe.db.commit"),
		):
			write_benchmark.run_stock_entry_write_benchmark(iterations=1, warmup_iterations=0)

		cleanup_report_benchmark.assert_called_once_with("WRITEPATH")

	def test_run_stock_entry_write_benchmark_cleans_created_source_dataset_by_default(self) -> None:
		context = write_benchmark.report_benchmark.BenchmarkContext(
			company="_Test Company",
			fg_item="_Benchmark FG Item WRITEPATH",
			rm_item="_Benchmark RM Item WRITEPATH",
			operator="Benchmark Operator WRITEPATH",
			workstation="Benchmark Workstation WRITEPATH",
			rm_warehouse="RM",
			fg_warehouse="FG",
			rejection_warehouse="REJ",
		)
		case_result = {"avg_elapsed_ms": 1.0, "p95_elapsed_ms": 1.0, "avg_sql_count": 1.0}
		with patch.object(write_benchmark, "_get_existing_benchmark_context", return_value=(None, None)):
			with patch.object(write_benchmark, "_prepare_write_benchmark_context", return_value=context):
				with patch.object(
					write_benchmark.report_benchmark,
					"_seed_benchmark_entries",
					return_value={"from_date": "2198-01-01", "to_date": "2198-01-20"},
				):
					with patch.object(
						write_benchmark,
						"_ensure_write_benchmark_shifts",
						return_value=[{"shift_name": "SHIFT-2198-01-21.Shift-1"}],
					):
						with patch.object(write_benchmark, "_run_write_case", side_effect=[case_result, case_result]):
							with patch.object(write_benchmark, "_cleanup_write_benchmark_shifts") as cleanup_shifts:
								with patch.object(
									write_benchmark.report_benchmark, "cleanup_report_benchmark"
								) as cleanup_benchmark:
									with patch.object(
										write_benchmark.performance_indexes, "ensure_overlap_indexes"
									):
										with patch("production_entry_app.production_entry_app.write_benchmark.frappe.db.commit"):
											write_benchmark.run_stock_entry_write_benchmark()

		cleanup_shifts.assert_called_once_with([{"shift_name": "SHIFT-2198-01-21.Shift-1"}])
		cleanup_benchmark.assert_called_once_with("WRITEPATH")

	def test_run_stock_entry_write_benchmark_keeps_created_source_dataset_when_requested(self) -> None:
		context = write_benchmark.report_benchmark.BenchmarkContext(
			company="_Test Company",
			fg_item="_Benchmark FG Item WRITEPATH",
			rm_item="_Benchmark RM Item WRITEPATH",
			operator="Benchmark Operator WRITEPATH",
			workstation="Benchmark Workstation WRITEPATH",
			rm_warehouse="RM",
			fg_warehouse="FG",
			rejection_warehouse="REJ",
		)
		case_result = {"avg_elapsed_ms": 1.0, "p95_elapsed_ms": 1.0, "avg_sql_count": 1.0}
		with patch.object(write_benchmark, "_get_existing_benchmark_context", return_value=(None, None)):
			with patch.object(write_benchmark, "_prepare_write_benchmark_context", return_value=context):
				with patch.object(
					write_benchmark.report_benchmark,
					"_seed_benchmark_entries",
					return_value={"from_date": "2198-01-01", "to_date": "2198-01-20"},
				):
					with patch.object(
						write_benchmark,
						"_ensure_write_benchmark_shifts",
						return_value=[{"shift_name": "SHIFT-2198-01-21.Shift-1"}],
					):
						with patch.object(write_benchmark, "_run_write_case", side_effect=[case_result, case_result]):
							with patch.object(write_benchmark, "_cleanup_write_benchmark_shifts"):
								with patch.object(
									write_benchmark.report_benchmark, "cleanup_report_benchmark"
								) as cleanup_benchmark:
									with patch.object(
										write_benchmark.performance_indexes, "ensure_overlap_indexes"
									):
										with patch("production_entry_app.production_entry_app.write_benchmark.frappe.db.commit"):
											write_benchmark.run_stock_entry_write_benchmark(keep_data=1)

		cleanup_benchmark.assert_not_called()
