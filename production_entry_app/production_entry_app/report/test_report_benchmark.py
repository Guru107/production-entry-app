from __future__ import annotations

from unittest.mock import Mock, patch

from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.report import report_benchmark


class TestReportBenchmark(FrappeTestCase):
	def test_run_report_benchmark_cleans_seeded_data_by_default(self) -> None:
		context = report_benchmark.BenchmarkContext(
			company="_Test Company",
			fg_item="_Benchmark FG Item PHASE2",
			rm_item="_Benchmark RM Item PHASE2",
			operator="Benchmark Operator PHASE2",
			workstation="Benchmark Workstation PHASE2",
			department="Benchmark Department PHASE2",
			rm_warehouse="RM",
			fg_warehouse="FG",
			rejection_warehouse="REJ",
		)
		with patch.object(report_benchmark, "_prepare_benchmark_context", return_value=context):
			with patch.object(
				report_benchmark,
				"_seed_benchmark_entries",
				return_value={"from_date": "2198-01-01", "to_date": "2198-01-20"},
			):
				with patch.object(
					report_benchmark, "_benchmark_reports", return_value={"operator_efficiency": {}}
				):
					with patch.object(report_benchmark, "cleanup_report_benchmark") as cleanup:
						report_benchmark.run_report_benchmark()

		cleanup.assert_called_once_with("PHASE2")

	def test_run_report_benchmark_keeps_seeded_data_when_requested(self) -> None:
		context = report_benchmark.BenchmarkContext(
			company="_Test Company",
			fg_item="_Benchmark FG Item PHASE2",
			rm_item="_Benchmark RM Item PHASE2",
			operator="Benchmark Operator PHASE2",
			workstation="Benchmark Workstation PHASE2",
			department="Benchmark Department PHASE2",
			rm_warehouse="RM",
			fg_warehouse="FG",
			rejection_warehouse="REJ",
		)
		with patch.object(report_benchmark, "_prepare_benchmark_context", return_value=context):
			with patch.object(
				report_benchmark,
				"_seed_benchmark_entries",
				return_value={"from_date": "2198-01-01", "to_date": "2198-01-20"},
			):
				with patch.object(
					report_benchmark, "_benchmark_reports", return_value={"operator_efficiency": {}}
				):
					with patch.object(report_benchmark, "cleanup_report_benchmark") as cleanup:
						report_benchmark.run_report_benchmark(keep_data=1)

		cleanup.assert_not_called()

	def test_run_report_benchmark_cleans_up_when_setup_fails(self) -> None:
		settings_snapshot = {"buffer": 60}
		restore_snapshot = Mock()
		with patch.object(
			report_benchmark.test_cleanup,
			"capture_manufacturing_settings_snapshot",
			return_value=settings_snapshot,
		):
			with patch.object(
				report_benchmark.test_cleanup,
				"restore_manufacturing_settings_snapshot",
				restore_snapshot,
			):
				with patch.object(
					report_benchmark,
					"_prepare_benchmark_context",
					side_effect=RuntimeError("seed failed"),
				):
					with patch.object(report_benchmark, "cleanup_report_benchmark") as cleanup:
						with self.assertRaisesRegex(RuntimeError, "seed failed"):
							report_benchmark.run_report_benchmark()

		restore_snapshot.assert_called_once_with(settings_snapshot)
		cleanup.assert_called_once_with("PHASE2")
