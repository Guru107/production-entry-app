from __future__ import annotations

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
