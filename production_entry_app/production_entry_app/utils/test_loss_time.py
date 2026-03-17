from __future__ import annotations

import datetime

from frappe.query_builder import DocType
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.loss_time import (
	build_interval_overlap_criterion,
	build_interval_overlap_filters,
	get_interval_minutes,
	get_loss_duration_minutes,
	resolve_time_interval_in_window,
)


class TestLossTime(FrappeTestCase):
	def test_resolve_interval_treats_equal_start_end_as_zero_duration(self) -> None:
		window_start = datetime.datetime(2026, 3, 3, 8, 0, 0)
		window_end = datetime.datetime(2026, 3, 3, 12, 0, 0)

		interval = resolve_time_interval_in_window("10:00:00", "10:00:00", window_start, window_end)

		self.assertIsNone(interval)

	def test_resolve_interval_keeps_cross_midnight_behavior(self) -> None:
		window_start = datetime.datetime(2026, 3, 3, 23, 30, 0)
		window_end = datetime.datetime(2026, 3, 4, 1, 0, 0)

		interval = resolve_time_interval_in_window("23:45:00", "00:15:00", window_start, window_end)

		self.assertIsNotNone(interval)
		start_dt, end_dt = interval
		self.assertEqual(start_dt, datetime.datetime(2026, 3, 3, 23, 45, 0))
		self.assertEqual(end_dt, datetime.datetime(2026, 3, 4, 0, 15, 0))

	def test_build_interval_overlap_filters_uses_half_open_window(self) -> None:
		window_start = datetime.datetime(2026, 3, 3, 8, 0, 0)
		window_end = datetime.datetime(2026, 3, 3, 12, 0, 0)

		self.assertEqual(
			build_interval_overlap_filters("from_time", "to_time", window_start, window_end),
			[
				["from_time", "<", window_end],
				["to_time", ">", window_start],
			],
		)

	def test_build_interval_overlap_criterion_uses_half_open_window(self) -> None:
		downtime_entry = DocType("Downtime Entry")
		window_start = datetime.datetime(2026, 3, 3, 8, 0, 0)
		window_end = datetime.datetime(2026, 3, 3, 12, 0, 0)

		criterion = build_interval_overlap_criterion(
			downtime_entry.from_time,
			downtime_entry.to_time,
			window_start,
			window_end,
		)

		criterion_sql = str(criterion)
		self.assertIn("from_time", criterion_sql)
		self.assertIn("to_time", criterion_sql)
		self.assertIn("<", criterion_sql)
		self.assertIn(">", criterion_sql)

	def test_get_loss_duration_minutes_preserves_raw_fractional_minutes(self) -> None:
		expected_minutes = 20 / 60
		derived_abs_tol = 1e-6

		self.assertAlmostEqual(
			get_loss_duration_minutes("10:00:00", "10:00:20"),
			expected_minutes,
			delta=derived_abs_tol,
		)

	def test_get_interval_minutes_preserves_raw_fractional_minutes(self) -> None:
		start_dt = datetime.datetime(2026, 3, 3, 10, 0, 0)
		end_dt = datetime.datetime(2026, 3, 3, 10, 0, 20)
		expected_minutes = 20 / 60
		derived_abs_tol = 1e-6

		self.assertAlmostEqual(
			get_interval_minutes(start_dt, end_dt),
			expected_minutes,
			delta=derived_abs_tol,
		)

	def test_get_loss_duration_minutes_preserves_raw_cross_midnight_fractional_minutes(self) -> None:
		expected_minutes = 40 / 60
		derived_abs_tol = 1e-6

		self.assertAlmostEqual(
			get_loss_duration_minutes("23:59:40", "00:00:20"),
			expected_minutes,
			delta=derived_abs_tol,
		)
